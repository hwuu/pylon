"""
Tests for statistics service.
"""

import pytest
import pytest_asyncio
from datetime import datetime, timedelta, timezone
import tempfile
import os

from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker, AsyncSession

from pylon.models import ApiKey, RequestLog, Base
from pylon.services.stats import StatsService


@pytest_asyncio.fixture
async def db_session():
    """Create a temporary database session for testing."""
    with tempfile.TemporaryDirectory() as tmpdir:
        db_path = os.path.join(tmpdir, "test.db")
        engine = create_async_engine(f"sqlite+aiosqlite:///{db_path}", echo=False)

        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)

        async_session = async_sessionmaker(
            bind=engine, class_=AsyncSession, expire_on_commit=False
        )

        async with async_session() as session:
            yield session

        await engine.dispose()


@pytest_asyncio.fixture
async def stats_service(db_session):
    """Create stats service."""
    return StatsService(db_session)


@pytest_asyncio.fixture
async def sample_data(db_session):
    """Create sample data for testing."""
    # Create API keys
    key1 = ApiKey(
        id="key-1",
        key_hash="hash1",
        key_prefix="sk-1",
        description="User 1",
    )
    key2 = ApiKey(
        id="key-2",
        key_hash="hash2",
        key_prefix="sk-2",
        description="User 2",
    )
    db_session.add_all([key1, key2])
    await db_session.commit()

    # Create request logs
    now = datetime.now(timezone.utc)

    logs = [
        # User 1 - success requests
        RequestLog(
            api_key_id="key-1",
            api_identifier="POST /v1/chat",
            request_path="/v1/chat/completions",
            request_method="POST",
            response_status=200,
            request_time=now - timedelta(hours=1),
            response_time_ms=100,
            client_ip="127.0.0.1",
            is_sse=False,
            sse_message_count=0,
        ),
        RequestLog(
            api_key_id="key-1",
            api_identifier="POST /v1/chat",
            request_path="/v1/chat/completions",
            request_method="POST",
            response_status=200,
            request_time=now - timedelta(hours=2),
            response_time_ms=200,
            client_ip="127.0.0.1",
            is_sse=False,
            sse_message_count=0,
        ),
        # User 1 - SSE request
        RequestLog(
            api_key_id="key-1",
            api_identifier="POST /v1/chat",
            request_path="/v1/chat/completions",
            request_method="POST",
            response_status=200,
            request_time=now - timedelta(hours=3),
            response_time_ms=5000,
            client_ip="127.0.0.1",
            is_sse=True,
            sse_message_count=50,
        ),
        # User 1 - rate limited
        RequestLog(
            api_key_id="key-1",
            api_identifier="POST /v1/chat",
            request_path="/v1/chat/completions",
            request_method="POST",
            response_status=429,
            request_time=now - timedelta(hours=4),
            response_time_ms=10,
            client_ip="127.0.0.1",
            is_sse=False,
            sse_message_count=0,
        ),
        # User 2 - success request
        RequestLog(
            api_key_id="key-2",
            api_identifier="GET /v1/models",
            request_path="/v1/models",
            request_method="GET",
            response_status=200,
            request_time=now - timedelta(hours=1),
            response_time_ms=50,
            client_ip="192.168.1.1",
            is_sse=False,
            sse_message_count=0,
        ),
        # User 2 - error request
        RequestLog(
            api_key_id="key-2",
            api_identifier="POST /v1/chat",
            request_path="/v1/chat/completions",
            request_method="POST",
            response_status=500,
            request_time=now - timedelta(hours=2),
            response_time_ms=150,
            client_ip="192.168.1.1",
            is_sse=False,
            sse_message_count=0,
        ),
    ]

    db_session.add_all(logs)
    await db_session.commit()

    return {"key1": key1, "key2": key2, "logs": logs}


class TestGetGlobalStats:
    """Tests for global statistics."""

    @pytest.mark.asyncio
    async def test_empty_stats(self, stats_service):
        """Test statistics with no data."""
        stats = await stats_service.get_global_stats()

        assert stats["total_requests"] == 0
        assert stats["total_sse_messages"] == 0
        assert stats["success_rate"] == 0
        assert stats["avg_response_time_ms"] == 0

    @pytest.mark.asyncio
    async def test_global_stats(self, stats_service, sample_data):
        """Test global statistics calculation."""
        stats = await stats_service.get_global_stats()

        # 6 total requests
        assert stats["total_requests"] == 6
        # 50 SSE messages from one request
        assert stats["total_sse_messages"] == 50
        # Total count = 6 + 50
        assert stats["total_count"] == 56
        # 4 success (200) out of 6 = 66.67%
        assert stats["success_rate"] == pytest.approx(66.67, rel=0.01)
        # 1 SSE connection
        assert stats["sse_connections"] == 1
        # 1 rate limited request
        assert stats["rate_limited_count"] == 1

    @pytest.mark.asyncio
    async def test_stats_with_time_range(self, stats_service, sample_data):
        """Test statistics with time range filter."""
        now = datetime.now(timezone.utc)

        # Only get last 1.5 hours (should include 2 requests: hour 1 from each user)
        stats = await stats_service.get_global_stats(
            start_time=now - timedelta(hours=1, minutes=30),
            end_time=now,
        )

        # Should only include 2 requests (hour 1 from user1 and user2)
        assert stats["total_requests"] == 2


class TestGetUserStats:
    """Tests for user statistics."""

    @pytest.mark.asyncio
    async def test_user_stats(self, stats_service, sample_data):
        """Test statistics for a specific user."""
        stats = await stats_service.get_user_stats("key-1")

        assert stats["api_key_id"] == "key-1"
        assert stats["total_requests"] == 4
        assert stats["total_sse_messages"] == 50
        assert stats["sse_connections"] == 1
        assert stats["rate_limited_count"] == 1

    @pytest.mark.asyncio
    async def test_user_stats_empty(self, stats_service):
        """Test statistics for non-existent user."""
        stats = await stats_service.get_user_stats("nonexistent")

        assert stats["total_requests"] == 0


class TestGetApiStats:
    """Tests for API statistics."""

    @pytest.mark.asyncio
    async def test_api_stats(self, stats_service, sample_data):
        """Test statistics for a specific API."""
        stats = await stats_service.get_api_stats("POST /v1/chat")

        assert stats["api_identifier"] == "POST /v1/chat"
        assert stats["total_requests"] == 5  # 4 from user1 + 1 from user2
        assert stats["total_sse_messages"] == 50

    @pytest.mark.asyncio
    async def test_api_stats_models(self, stats_service, sample_data):
        """Test statistics for models API."""
        stats = await stats_service.get_api_stats("GET /v1/models")

        assert stats["total_requests"] == 1
        assert stats["success_rate"] == 100.0


class TestGetUsersSummary:
    """Tests for users summary."""

    @pytest.mark.asyncio
    async def test_users_summary(self, stats_service, sample_data):
        """Test getting summary grouped by user."""
        summary = await stats_service.get_users_summary()

        assert len(summary) == 2

        # Results ordered by request count descending
        # User 1 has 4 requests
        assert summary[0]["api_key_id"] == "key-1"
        assert summary[0]["total_requests"] == 4

        # User 2 has 2 requests
        assert summary[1]["api_key_id"] == "key-2"
        assert summary[1]["total_requests"] == 2


class TestGetApisSummary:
    """Tests for APIs summary."""

    @pytest.mark.asyncio
    async def test_apis_summary(self, stats_service, sample_data):
        """Test getting summary grouped by API."""
        summary = await stats_service.get_apis_summary()

        assert len(summary) == 2

        # Results ordered by request count descending
        # POST /v1/chat has 5 requests
        chat_api = next(s for s in summary if s["api_identifier"] == "POST /v1/chat")
        assert chat_api["total_requests"] == 5

        # GET /v1/models has 1 request
        models_api = next(s for s in summary if s["api_identifier"] == "GET /v1/models")
        assert models_api["total_requests"] == 1
