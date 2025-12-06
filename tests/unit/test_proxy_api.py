"""
Tests for proxy API routes.
"""

import pytest
import pytest_asyncio
from unittest.mock import AsyncMock, MagicMock, patch
from datetime import datetime, timezone
import tempfile
import os

from fastapi import FastAPI
from fastapi.testclient import TestClient
from httpx import Response as HttpxResponse
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker, AsyncSession

from pylon.models import ApiKey, Base
from pylon.services.proxy import ProxyService
from pylon.services.rate_limiter import RateLimiter, RateLimitStatus, RateLimitResult
from pylon.api import proxy as proxy_api
from pylon.utils.crypto import generate_api_key, hash_api_key, get_api_key_prefix
from pylon.config import RateLimitConfig, RateLimitRule


@pytest.fixture
def mock_proxy_service():
    """Create a mock proxy service."""
    service = AsyncMock(spec=ProxyService)
    service.health_check = AsyncMock(return_value=True)
    return service


@pytest.fixture
def mock_rate_limiter():
    """Create a mock rate limiter."""
    limiter = AsyncMock(spec=RateLimiter)
    limiter.check_rate_limit = AsyncMock(
        return_value=RateLimitStatus(result=RateLimitResult.ALLOWED)
    )
    limiter.acquire = AsyncMock()
    limiter.release = AsyncMock()
    limiter.get_stats = MagicMock(return_value={"queue_size": 0, "global_concurrent": 0})
    return limiter


@pytest_asyncio.fixture
async def db_engine():
    """Create a temporary database engine for testing."""
    with tempfile.TemporaryDirectory() as tmpdir:
        db_path = os.path.join(tmpdir, "test.db")
        engine = create_async_engine(f"sqlite+aiosqlite:///{db_path}", echo=False)

        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)

        yield engine

        await engine.dispose()


@pytest_asyncio.fixture
async def session_factory(db_engine):
    """Create a session factory for testing."""
    return async_sessionmaker(
        bind=db_engine, class_=AsyncSession, expire_on_commit=False
    )


@pytest_asyncio.fixture
async def valid_api_key(session_factory):
    """Create a valid API key in the database."""
    raw_key = generate_api_key()
    async with session_factory() as session:
        api_key = ApiKey(
            key_hash=hash_api_key(raw_key),
            key_prefix=get_api_key_prefix(raw_key),
            description="Test key",
        )
        session.add(api_key)
        await session.commit()
        await session.refresh(api_key)
        return raw_key, api_key.id


@pytest.fixture
def app(mock_proxy_service, mock_rate_limiter, session_factory):
    """Create a test FastAPI application."""
    app = FastAPI()
    app.include_router(proxy_api.router)

    # Set dependencies
    proxy_api.set_dependencies(mock_proxy_service, mock_rate_limiter, session_factory)

    return app


@pytest.fixture
def client(app):
    """Create a test client."""
    return TestClient(app)


class TestHealthCheck:
    """Tests for health check endpoint."""

    def test_health_check_success(self, client, mock_proxy_service, mock_rate_limiter):
        """Test health check returns OK when downstream is healthy."""
        mock_proxy_service.health_check.return_value = True
        mock_rate_limiter.get_stats.return_value = {
            "queue_size": 5,
            "global_concurrent": 3,
        }

        response = client.get("/health")

        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "ok"
        assert data["downstream"] == "ok"
        assert data["queue_size"] == 5
        assert data["active_connections"] == 3

    def test_health_check_downstream_error(self, client, mock_proxy_service):
        """Test health check when downstream is unhealthy."""
        mock_proxy_service.health_check.return_value = False

        response = client.get("/health")

        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "ok"
        assert data["downstream"] == "error"


class TestProxyAuthentication:
    """Tests for proxy authentication."""

    def test_missing_authorization_header(self, client):
        """Test request without Authorization header."""
        response = client.get("/v1/models")

        assert response.status_code == 401
        data = response.json()
        assert data["detail"]["error"] == "unauthorized"

    def test_invalid_authorization_scheme(self, client):
        """Test request with invalid authorization scheme."""
        response = client.get("/v1/models", headers={"Authorization": "Basic invalid"})

        assert response.status_code == 401
        data = response.json()
        assert data["detail"]["error"] == "unauthorized"

    def test_invalid_api_key(self, client):
        """Test request with non-existent API key."""
        response = client.get(
            "/v1/models", headers={"Authorization": "Bearer sk-nonexistent"}
        )

        assert response.status_code == 401
        data = response.json()
        assert data["detail"]["error"] == "unauthorized"

    @pytest.mark.asyncio
    async def test_valid_api_key(
        self, client, valid_api_key, mock_proxy_service
    ):
        """Test request with valid API key."""
        raw_key, _ = valid_api_key

        # Mock the proxy response
        mock_response = MagicMock(spec=HttpxResponse)
        mock_response.status_code = 200
        mock_response.content = b'{"models": []}'
        mock_response.headers = {"Content-Type": "application/json"}
        mock_proxy_service.forward_request.return_value = mock_response

        response = client.get(
            "/v1/models", headers={"Authorization": f"Bearer {raw_key}"}
        )

        assert response.status_code == 200
        mock_proxy_service.forward_request.assert_called_once()


class TestProxyRateLimiting:
    """Tests for proxy rate limiting."""

    @pytest.mark.asyncio
    async def test_rate_limit_exceeded(
        self, client, valid_api_key, mock_rate_limiter
    ):
        """Test request when rate limit is exceeded."""
        raw_key, _ = valid_api_key

        mock_rate_limiter.check_rate_limit.return_value = RateLimitStatus(
            result=RateLimitResult.USER_LIMIT_EXCEEDED,
            message="Rate limit exceeded",
        )

        response = client.get(
            "/v1/models", headers={"Authorization": f"Bearer {raw_key}"}
        )

        assert response.status_code == 429
        data = response.json()
        assert data["detail"]["error"] == "rate_limit_exceeded"

    @pytest.mark.asyncio
    async def test_global_rate_limit_exceeded(
        self, client, valid_api_key, mock_rate_limiter
    ):
        """Test request when global rate limit is exceeded."""
        raw_key, _ = valid_api_key

        mock_rate_limiter.check_rate_limit.return_value = RateLimitStatus(
            result=RateLimitResult.GLOBAL_LIMIT_EXCEEDED,
            message="System busy",
        )

        response = client.get(
            "/v1/models", headers={"Authorization": f"Bearer {raw_key}"}
        )

        assert response.status_code == 429
        data = response.json()
        assert "System busy" in data["detail"]["message"]


class TestProxyForwarding:
    """Tests for proxy request forwarding."""

    @pytest.mark.asyncio
    async def test_forward_get_request(
        self, client, valid_api_key, mock_proxy_service
    ):
        """Test forwarding GET request."""
        raw_key, _ = valid_api_key

        mock_response = MagicMock(spec=HttpxResponse)
        mock_response.status_code = 200
        mock_response.content = b'{"data": "test"}'
        mock_response.headers = {"Content-Type": "application/json"}
        mock_proxy_service.forward_request.return_value = mock_response

        response = client.get(
            "/v1/models", headers={"Authorization": f"Bearer {raw_key}"}
        )

        assert response.status_code == 200
        assert response.json() == {"data": "test"}

        # Verify forward_request was called correctly
        call_args = mock_proxy_service.forward_request.call_args
        assert call_args.kwargs["method"] == "GET"
        assert call_args.kwargs["path"] == "/v1/models"

    @pytest.mark.asyncio
    async def test_forward_post_request_with_body(
        self, client, valid_api_key, mock_proxy_service
    ):
        """Test forwarding POST request with body."""
        raw_key, _ = valid_api_key

        mock_response = MagicMock(spec=HttpxResponse)
        mock_response.status_code = 200
        mock_response.content = b'{"id": "123"}'
        mock_response.headers = {"Content-Type": "application/json"}
        mock_proxy_service.forward_request.return_value = mock_response

        response = client.post(
            "/v1/chat/completions",
            headers={
                "Authorization": f"Bearer {raw_key}",
                "Content-Type": "application/json",
            },
            json={"model": "gpt-4", "messages": []},
        )

        assert response.status_code == 200

        call_args = mock_proxy_service.forward_request.call_args
        assert call_args.kwargs["method"] == "POST"
        assert call_args.kwargs["path"] == "/v1/chat/completions"
        assert call_args.kwargs["content"] is not None

    @pytest.mark.asyncio
    async def test_forward_with_query_params(
        self, client, valid_api_key, mock_proxy_service
    ):
        """Test forwarding request with query parameters."""
        raw_key, _ = valid_api_key

        mock_response = MagicMock(spec=HttpxResponse)
        mock_response.status_code = 200
        mock_response.content = b'{"results": []}'
        mock_response.headers = {"Content-Type": "application/json"}
        mock_proxy_service.forward_request.return_value = mock_response

        response = client.get(
            "/v1/models?limit=10&offset=0",
            headers={"Authorization": f"Bearer {raw_key}"},
        )

        assert response.status_code == 200

        call_args = mock_proxy_service.forward_request.call_args
        assert call_args.kwargs["query_params"] == {"limit": "10", "offset": "0"}

    @pytest.mark.asyncio
    async def test_downstream_error_propagated(
        self, client, valid_api_key, mock_proxy_service
    ):
        """Test that downstream errors are propagated."""
        raw_key, _ = valid_api_key

        mock_response = MagicMock(spec=HttpxResponse)
        mock_response.status_code = 500
        mock_response.content = b'{"error": "Internal server error"}'
        mock_response.headers = {"Content-Type": "application/json"}
        mock_proxy_service.forward_request.return_value = mock_response

        response = client.get(
            "/v1/models", headers={"Authorization": f"Bearer {raw_key}"}
        )

        assert response.status_code == 500

    @pytest.mark.asyncio
    async def test_rate_limiter_slot_released_after_request(
        self, client, valid_api_key, mock_proxy_service, mock_rate_limiter
    ):
        """Test that rate limiter slot is released after request completes."""
        raw_key, key_id = valid_api_key

        mock_response = MagicMock(spec=HttpxResponse)
        mock_response.status_code = 200
        mock_response.content = b'{}'
        mock_response.headers = {}
        mock_proxy_service.forward_request.return_value = mock_response

        client.get("/v1/models", headers={"Authorization": f"Bearer {raw_key}"})

        # Verify acquire and release were both called
        mock_rate_limiter.acquire.assert_called_once()
        mock_rate_limiter.release.assert_called_once()


class TestResponseHeaders:
    """Tests for response header handling."""

    @pytest.mark.asyncio
    async def test_hop_by_hop_headers_filtered(
        self, client, valid_api_key, mock_proxy_service
    ):
        """Test that hop-by-hop headers are filtered from response."""
        raw_key, _ = valid_api_key

        mock_response = MagicMock(spec=HttpxResponse)
        mock_response.status_code = 200
        mock_response.content = b'{}'
        mock_response.headers = {
            "Content-Type": "application/json",
            "Connection": "keep-alive",
            "Transfer-Encoding": "chunked",
            "X-Custom-Header": "custom-value",
        }
        mock_proxy_service.forward_request.return_value = mock_response

        response = client.get(
            "/v1/models", headers={"Authorization": f"Bearer {raw_key}"}
        )

        assert "connection" not in response.headers
        assert "transfer-encoding" not in response.headers
        assert response.headers.get("x-custom-header") == "custom-value"


class TestSSEDetection:
    """Tests for SSE request detection."""

    def test_detect_sse_by_accept_header(self):
        """Test detection of SSE request by Accept header."""
        from pylon.api.proxy import _is_sse_request
        from unittest.mock import MagicMock

        request = MagicMock()
        request.headers = {"accept": "text/event-stream"}

        assert _is_sse_request(request, b"") is True

    def test_detect_sse_by_stream_true_in_body(self):
        """Test detection of SSE request by stream: true in body."""
        from pylon.api.proxy import _is_sse_request
        from unittest.mock import MagicMock
        import json

        request = MagicMock()
        request.headers = {"accept": "application/json"}
        body = json.dumps({"model": "gpt-4", "stream": True}).encode()

        assert _is_sse_request(request, body) is True

    def test_not_sse_when_stream_false(self):
        """Test non-SSE request when stream: false."""
        from pylon.api.proxy import _is_sse_request
        from unittest.mock import MagicMock
        import json

        request = MagicMock()
        request.headers = {"accept": "application/json"}
        body = json.dumps({"model": "gpt-4", "stream": False}).encode()

        assert _is_sse_request(request, body) is False

    def test_not_sse_for_regular_request(self):
        """Test non-SSE detection for regular request."""
        from pylon.api.proxy import _is_sse_request
        from unittest.mock import MagicMock

        request = MagicMock()
        request.headers = {"accept": "application/json"}

        assert _is_sse_request(request, b"{}") is False


class TestPylonErrorEvent:
    """Tests for pylon_error SSE event generation."""

    def test_create_pylon_error_event(self):
        """Test creating pylon_error SSE event."""
        from pylon.api.proxy import _create_pylon_error_event
        import json

        event = _create_pylon_error_event("test_error", "Test message")

        assert event.startswith("event: pylon_error\n")
        assert "data:" in event
        assert event.endswith("\n\n")

        # Parse the data
        data_line = [line for line in event.split("\n") if line.startswith("data:")][0]
        data = json.loads(data_line[5:])  # Remove "data:" prefix
        assert data["code"] == "test_error"
        assert data["message"] == "Test message"


class TestSSERequest:
    """Tests for SSE request handling."""

    @pytest.mark.asyncio
    async def test_sse_request_uses_sse_rate_limit(
        self, client, valid_api_key, mock_proxy_service, mock_rate_limiter
    ):
        """Test that SSE requests use SSE rate limiting."""
        raw_key, _ = valid_api_key

        # Mock streaming response
        async def mock_stream(*args, **kwargs):
            yield (b"", 200, {"Content-Type": "text/event-stream"})
            yield (b"data: test\n\n", 0, {})

        mock_proxy_service.forward_request_stream = mock_stream

        response = client.post(
            "/v1/chat/completions",
            headers={
                "Authorization": f"Bearer {raw_key}",
                "Accept": "text/event-stream",
            },
            json={"model": "gpt-4", "messages": [], "stream": True},
        )

        # Verify SSE rate limiting was used
        call_args = mock_rate_limiter.check_rate_limit.call_args
        assert call_args.kwargs.get("is_sse") is True

        acquire_args = mock_rate_limiter.acquire.call_args
        assert acquire_args.kwargs.get("is_sse") is True

    @pytest.mark.asyncio
    async def test_sse_response_headers(
        self, client, valid_api_key, mock_proxy_service, mock_rate_limiter
    ):
        """Test SSE response has correct headers."""
        raw_key, _ = valid_api_key

        async def mock_stream(*args, **kwargs):
            yield (b"", 200, {"Content-Type": "text/event-stream"})
            yield (b"data: test\n\n", 0, {})

        mock_proxy_service.forward_request_stream = mock_stream

        response = client.post(
            "/v1/chat/completions",
            headers={
                "Authorization": f"Bearer {raw_key}",
                "Accept": "text/event-stream",
            },
            json={"model": "gpt-4", "messages": [], "stream": True},
        )

        assert response.headers.get("content-type") == "text/event-stream; charset=utf-8"
        assert response.headers.get("cache-control") == "no-cache"

    @pytest.mark.asyncio
    async def test_sse_downstream_error_returns_pylon_error(
        self, client, valid_api_key, mock_proxy_service, mock_rate_limiter
    ):
        """Test that downstream error in SSE returns pylon_error event."""
        raw_key, _ = valid_api_key

        async def mock_stream(*args, **kwargs):
            yield (b"", 500, {"Content-Type": "application/json"})

        mock_proxy_service.forward_request_stream = mock_stream

        response = client.post(
            "/v1/chat/completions",
            headers={
                "Authorization": f"Bearer {raw_key}",
                "Accept": "text/event-stream",
            },
            json={"model": "gpt-4", "messages": [], "stream": True},
        )

        content = response.text
        assert "event: pylon_error" in content
        assert "downstream_error" in content
