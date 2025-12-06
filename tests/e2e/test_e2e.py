"""
End-to-end tests for Pylon proxy.
"""

import pytest


class TestAuthentication:
    """Tests for API key authentication."""

    @pytest.mark.asyncio
    async def test_request_without_api_key(self, pylon_servers, http_client):
        """Request without API key should return 401."""
        response = await http_client.get(f"{pylon_servers['proxy']}/api/hello")
        assert response.status_code == 401

    @pytest.mark.asyncio
    async def test_request_with_invalid_api_key(self, pylon_servers, http_client):
        """Request with invalid API key should return 401."""
        response = await http_client.get(
            f"{pylon_servers['proxy']}/api/hello",
            headers={"Authorization": "Bearer sk-invalid-key-12345678901234567890"}
        )
        assert response.status_code == 401

    @pytest.mark.asyncio
    async def test_request_with_valid_api_key(self, pylon_servers, http_client, api_key):
        """Request with valid API key should succeed."""
        response = await http_client.get(
            f"{pylon_servers['proxy']}/api/hello",
            headers={"Authorization": f"Bearer {api_key}"}
        )
        assert response.status_code == 200
        assert response.json() == {"message": "hello"}


class TestProxyForwarding:
    """Tests for proxy request forwarding."""

    @pytest.mark.asyncio
    async def test_get_request(self, pylon_servers, http_client, api_key):
        """GET request should be forwarded correctly."""
        response = await http_client.get(
            f"{pylon_servers['proxy']}/api/hello",
            headers={"Authorization": f"Bearer {api_key}"}
        )
        assert response.status_code == 200
        assert response.json() == {"message": "hello"}

    @pytest.mark.asyncio
    async def test_post_request(self, pylon_servers, http_client, api_key):
        """POST request should be forwarded correctly."""
        response = await http_client.post(
            f"{pylon_servers['proxy']}/api/echo",
            json={"test": "data", "number": 42},
            headers={"Authorization": f"Bearer {api_key}"}
        )
        assert response.status_code == 200
        assert response.json() == {"test": "data", "number": 42}

    @pytest.mark.asyncio
    async def test_downstream_error(self, pylon_servers, http_client, api_key):
        """Downstream error should be forwarded."""
        response = await http_client.get(
            f"{pylon_servers['proxy']}/api/error",
            headers={"Authorization": f"Bearer {api_key}"}
        )
        assert response.status_code == 500


class TestHealthCheck:
    """Tests for health check endpoint."""

    @pytest.mark.asyncio
    async def test_proxy_health(self, pylon_servers, http_client):
        """Proxy health check should not require auth."""
        response = await http_client.get(f"{pylon_servers['proxy']}/health")
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "ok"

    @pytest.mark.asyncio
    async def test_admin_health(self, pylon_servers, http_client):
        """Admin health check should not require auth."""
        response = await http_client.get(f"{pylon_servers['admin']}/health")
        assert response.status_code == 200
        assert response.json()["status"] == "ok"


class TestAdminApi:
    """Tests for admin API."""

    @pytest.mark.asyncio
    async def test_login_success(self, pylon_servers, http_client):
        """Admin login with correct password."""
        response = await http_client.post(
            f"{pylon_servers['admin']}/login",
            json={"password": "test123"}
        )
        assert response.status_code == 200
        data = response.json()
        assert "token" in data
        assert data["expires_in_hours"] == 24

    @pytest.mark.asyncio
    async def test_login_wrong_password(self, pylon_servers, http_client):
        """Admin login with wrong password."""
        response = await http_client.post(
            f"{pylon_servers['admin']}/login",
            json={"password": "wrongpassword"}
        )
        assert response.status_code == 401

    @pytest.mark.asyncio
    async def test_api_keys_requires_auth(self, pylon_servers, http_client):
        """API keys endpoint requires authentication."""
        response = await http_client.get(f"{pylon_servers['admin']}/api-keys")
        assert response.status_code == 401

    @pytest.mark.asyncio
    async def test_list_api_keys(self, pylon_servers, http_client, admin_token, api_key):
        """List API keys."""
        response = await http_client.get(
            f"{pylon_servers['admin']}/api-keys",
            headers={"Authorization": f"Bearer {admin_token}"}
        )
        assert response.status_code == 200
        keys = response.json()
        assert len(keys) >= 1

    @pytest.mark.asyncio
    async def test_create_api_key(self, pylon_servers, http_client, admin_token):
        """Create new API key."""
        response = await http_client.post(
            f"{pylon_servers['admin']}/api-keys",
            json={"description": "New test key", "priority": "high"},
            headers={"Authorization": f"Bearer {admin_token}"}
        )
        assert response.status_code == 200
        data = response.json()
        assert data["key"].startswith("sk-")
        assert data["description"] == "New test key"
        assert data["priority"] == "high"


class TestMonitor:
    """Tests for monitoring endpoint."""

    @pytest.mark.asyncio
    async def test_monitor_data(self, pylon_servers, http_client, admin_token):
        """Get monitor data."""
        response = await http_client.get(
            f"{pylon_servers['admin']}/monitor",
            headers={"Authorization": f"Bearer {admin_token}"}
        )
        assert response.status_code == 200
        data = response.json()
        assert "global_concurrent" in data
        assert "global_sse_connections" in data
        assert "global_requests_this_minute" in data
        assert "queue_size" in data


class TestStats:
    """Tests for statistics endpoints."""

    @pytest.mark.asyncio
    async def test_stats_summary(self, pylon_servers, http_client, admin_token, api_key):
        """Get stats summary after making some requests."""
        # Make a request first
        await http_client.get(
            f"{pylon_servers['proxy']}/api/hello",
            headers={"Authorization": f"Bearer {api_key}"}
        )

        # Get stats
        response = await http_client.get(
            f"{pylon_servers['admin']}/stats/summary",
            headers={"Authorization": f"Bearer {admin_token}"}
        )
        assert response.status_code == 200
        data = response.json()
        assert "total_requests" in data
        assert "success_rate" in data

    @pytest.mark.asyncio
    async def test_stats_users(self, pylon_servers, http_client, admin_token):
        """Get stats by user."""
        response = await http_client.get(
            f"{pylon_servers['admin']}/stats/users",
            headers={"Authorization": f"Bearer {admin_token}"}
        )
        assert response.status_code == 200
        assert isinstance(response.json(), list)

    @pytest.mark.asyncio
    async def test_stats_apis(self, pylon_servers, http_client, admin_token):
        """Get stats by API."""
        response = await http_client.get(
            f"{pylon_servers['admin']}/stats/apis",
            headers={"Authorization": f"Bearer {admin_token}"}
        )
        assert response.status_code == 200
        assert isinstance(response.json(), list)
