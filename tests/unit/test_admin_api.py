"""
Tests for admin API routes.
"""

import pytest
import pytest_asyncio
from unittest.mock import MagicMock
import tempfile
import os

from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker, AsyncSession

from pylon.models import ApiKey, Base
from pylon.services.admin_auth import AdminAuthService
from pylon.config import AdminConfig
from pylon.utils.crypto import hash_password
from pylon.api import admin as admin_api


@pytest.fixture
def admin_config():
    """Create admin config with test password."""
    return AdminConfig(
        password_hash=hash_password("test_password"),
        jwt_secret="test_jwt_secret_key_12345",
        jwt_expire_hours=24,
    )


@pytest.fixture
def admin_auth_service(admin_config):
    """Create admin auth service."""
    return AdminAuthService(admin_config)


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


@pytest.fixture
def mock_rate_limiter():
    """Create a mock rate limiter."""
    limiter = MagicMock()
    limiter.get_stats.return_value = {
        "global_concurrent": 5,
        "global_sse_connections": 2,
        "global_requests_this_minute": 100,
        "queue_size": 3,
    }
    return limiter


@pytest.fixture
def app(admin_auth_service, session_factory, mock_rate_limiter):
    """Create a test FastAPI application."""
    app = FastAPI()
    app.include_router(admin_api.router)

    # Set dependencies
    admin_api.set_dependencies(admin_auth_service, session_factory, mock_rate_limiter)

    return app


@pytest.fixture
def client(app):
    """Create a test client."""
    return TestClient(app)


@pytest.fixture
def auth_token(client):
    """Get a valid auth token."""
    response = client.post("/login", json={"password": "test_password"})
    return response.json()["token"]


@pytest.fixture
def auth_headers(auth_token):
    """Get auth headers."""
    return {"Authorization": f"Bearer {auth_token}"}


class TestLogin:
    """Tests for login endpoint."""

    def test_login_success(self, client):
        """Test successful login."""
        response = client.post("/login", json={"password": "test_password"})

        assert response.status_code == 200
        data = response.json()
        assert "token" in data
        assert data["expires_in_hours"] == 24

    def test_login_wrong_password(self, client):
        """Test login with wrong password."""
        response = client.post("/login", json={"password": "wrong_password"})

        assert response.status_code == 401
        assert response.json()["detail"]["error"] == "unauthorized"

    def test_login_empty_password(self, client):
        """Test login with empty password."""
        response = client.post("/login", json={"password": ""})

        assert response.status_code == 401


class TestHealthCheck:
    """Tests for health check endpoint."""

    def test_health_check_no_auth(self, client):
        """Test health check doesn't require auth."""
        response = client.get("/health")

        assert response.status_code == 200
        assert response.json()["status"] == "ok"


class TestApiKeyList:
    """Tests for listing API keys."""

    def test_list_keys_requires_auth(self, client):
        """Test that listing keys requires authentication."""
        response = client.get("/api-keys")
        assert response.status_code == 401

    def test_list_keys_empty(self, client, auth_headers):
        """Test listing when no keys exist."""
        response = client.get("/api-keys", headers=auth_headers)

        assert response.status_code == 200
        assert response.json() == []

    def test_list_keys_with_keys(self, client, auth_headers):
        """Test listing after creating keys."""
        # Create a key first
        client.post(
            "/api-keys",
            json={"description": "Test key"},
            headers=auth_headers,
        )

        response = client.get("/api-keys", headers=auth_headers)

        assert response.status_code == 200
        keys = response.json()
        assert len(keys) == 1
        assert keys[0]["description"] == "Test key"


class TestApiKeyCreate:
    """Tests for creating API keys."""

    def test_create_key_requires_auth(self, client):
        """Test that creating keys requires authentication."""
        response = client.post("/api-keys", json={"description": "Test"})
        assert response.status_code == 401

    def test_create_basic_key(self, client, auth_headers):
        """Test creating a basic key."""
        response = client.post(
            "/api-keys",
            json={"description": "Test key"},
            headers=auth_headers,
        )

        assert response.status_code == 200
        data = response.json()
        assert data["key"].startswith("sk-")
        assert data["description"] == "Test key"
        assert data["priority"] == "normal"
        assert "id" in data

    def test_create_key_with_priority(self, client, auth_headers):
        """Test creating key with priority."""
        response = client.post(
            "/api-keys",
            json={"description": "High priority", "priority": "high"},
            headers=auth_headers,
        )

        assert response.status_code == 200
        assert response.json()["priority"] == "high"

    def test_create_key_invalid_priority(self, client, auth_headers):
        """Test creating key with invalid priority."""
        response = client.post(
            "/api-keys",
            json={"description": "Test", "priority": "invalid"},
            headers=auth_headers,
        )

        assert response.status_code == 400
        assert response.json()["detail"]["error"] == "invalid_priority"

    def test_create_key_with_expiration(self, client, auth_headers):
        """Test creating key with expiration."""
        response = client.post(
            "/api-keys",
            json={"description": "Expiring key", "expires_in_days": 30},
            headers=auth_headers,
        )

        assert response.status_code == 200
        assert response.json()["expires_at"] is not None


class TestApiKeyGet:
    """Tests for getting a single API key."""

    def test_get_key(self, client, auth_headers):
        """Test getting a key by ID."""
        # Create a key
        create_response = client.post(
            "/api-keys",
            json={"description": "Test key"},
            headers=auth_headers,
        )
        key_id = create_response.json()["id"]

        # Get it
        response = client.get(f"/api-keys/{key_id}", headers=auth_headers)

        assert response.status_code == 200
        assert response.json()["id"] == key_id

    def test_get_nonexistent_key(self, client, auth_headers):
        """Test getting a non-existent key."""
        response = client.get("/api-keys/nonexistent-id", headers=auth_headers)

        assert response.status_code == 404


class TestApiKeyUpdate:
    """Tests for updating API keys."""

    def test_update_description(self, client, auth_headers):
        """Test updating key description."""
        # Create a key
        create_response = client.post(
            "/api-keys",
            json={"description": "Original"},
            headers=auth_headers,
        )
        key_id = create_response.json()["id"]

        # Update it
        response = client.put(
            f"/api-keys/{key_id}",
            json={"description": "Updated"},
            headers=auth_headers,
        )

        assert response.status_code == 200
        assert response.json()["description"] == "Updated"


class TestApiKeyRevoke:
    """Tests for revoking API keys."""

    def test_revoke_key(self, client, auth_headers):
        """Test revoking a key."""
        # Create a key
        create_response = client.post(
            "/api-keys",
            json={"description": "Test"},
            headers=auth_headers,
        )
        key_id = create_response.json()["id"]

        # Revoke it
        response = client.post(f"/api-keys/{key_id}/revoke", headers=auth_headers)

        assert response.status_code == 200
        assert response.json()["revoked_at"] is not None
        assert response.json()["is_valid"] is False


class TestApiKeyRefresh:
    """Tests for refreshing API keys."""

    def test_refresh_key(self, client, auth_headers):
        """Test refreshing a key."""
        # Create a key
        create_response = client.post(
            "/api-keys",
            json={"description": "Test"},
            headers=auth_headers,
        )
        key_id = create_response.json()["id"]
        original_key = create_response.json()["key"]

        # Refresh it
        response = client.post(f"/api-keys/{key_id}/refresh", headers=auth_headers)

        assert response.status_code == 200
        data = response.json()
        assert data["id"] == key_id
        assert data["key"] != original_key
        assert data["key"].startswith("sk-")


class TestApiKeyDelete:
    """Tests for deleting API keys."""

    def test_delete_key(self, client, auth_headers):
        """Test deleting a key."""
        # Create a key
        create_response = client.post(
            "/api-keys",
            json={"description": "Test"},
            headers=auth_headers,
        )
        key_id = create_response.json()["id"]

        # Delete it
        response = client.delete(f"/api-keys/{key_id}", headers=auth_headers)

        assert response.status_code == 200

        # Verify it's gone
        get_response = client.get(f"/api-keys/{key_id}", headers=auth_headers)
        assert get_response.status_code == 404


class TestApiKeyCount:
    """Tests for API key count statistics."""

    def test_count_empty(self, client, auth_headers):
        """Test count when no keys exist."""
        response = client.get("/api-keys/count", headers=auth_headers)

        assert response.status_code == 200
        data = response.json()
        assert data["total"] == 0
        assert data["active"] == 0


class TestMonitor:
    """Tests for monitoring endpoint."""

    def test_monitor_data(self, client, auth_headers, mock_rate_limiter):
        """Test getting monitoring data."""
        response = client.get("/monitor", headers=auth_headers)

        assert response.status_code == 200
        data = response.json()
        assert data["global_concurrent"] == 5
        assert data["global_sse_connections"] == 2
        assert data["global_requests_this_minute"] == 100
