"""
Pytest fixtures for end-to-end tests.
"""

import pytest
import pytest_asyncio
import asyncio
import tempfile
import os
import time
from multiprocessing import Process

import httpx
import uvicorn

from tests.mock_server.app import app as mock_app


def run_mock_server(port: int):
    """Run mock server in a subprocess."""
    uvicorn.run(mock_app, host="127.0.0.1", port=port, log_level="warning")


def run_pylon(config_path: str, proxy_port: int, admin_port: int):
    """Run Pylon in a subprocess."""
    import sys
    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(__file__))))

    from pylon.config import load_config
    from pylon.main import run_servers

    config = load_config(config_path)
    # Override ports
    config.server.proxy_port = proxy_port
    config.server.admin_port = admin_port

    asyncio.run(run_servers(config))


@pytest.fixture(scope="session")
def mock_server_port():
    """Port for mock downstream server."""
    return 19999


@pytest.fixture(scope="session")
def proxy_port():
    """Port for Pylon proxy server."""
    return 18000


@pytest.fixture(scope="session")
def admin_port():
    """Port for Pylon admin server."""
    return 18001


@pytest.fixture(scope="session")
def mock_server(mock_server_port):
    """Start mock downstream server."""
    process = Process(target=run_mock_server, args=(mock_server_port,))
    process.start()

    # Wait for server to start
    time.sleep(1)

    yield f"http://127.0.0.1:{mock_server_port}"

    process.terminate()
    process.join(timeout=5)


@pytest.fixture(scope="session")
def test_config(mock_server_port, proxy_port, admin_port):
    """Create test configuration file."""
    with tempfile.TemporaryDirectory() as tmpdir:
        config_content = f"""
server:
  proxy_port: {proxy_port}
  admin_port: {admin_port}
  host: "127.0.0.1"

downstream:
  base_url: "http://127.0.0.1:{mock_server_port}"
  timeout: 30

database:
  type: "sqlite"
  path: "{tmpdir}/test.db"

admin:
  password_hash: "$2b$12$LQv3c1yqBWVHxkd0LHAkCOYz6TtxMQJqhN8/X4.VTtYcKF7xK8FGi"  # password: test123
  jwt_secret: "test-secret-key"
  jwt_expire_hours: 24

rate_limit:
  global:
    max_concurrent: 10
    max_requests_per_minute: 100
    max_sse_connections: 5
  default_user:
    max_concurrent: 2
    max_requests_per_minute: 20
    max_sse_connections: 1

queue:
  max_size: 10
  timeout: 5

sse:
  idle_timeout: 10

data_retention:
  days: 30
  cleanup_interval_hours: 24
"""
        config_path = os.path.join(tmpdir, "config.yaml")
        with open(config_path, "w") as f:
            f.write(config_content)

        yield config_path, tmpdir


@pytest.fixture(scope="session")
def pylon_servers(mock_server, test_config, proxy_port, admin_port):
    """Start Pylon servers."""
    config_path, tmpdir = test_config

    process = Process(
        target=run_pylon,
        args=(config_path, proxy_port, admin_port)
    )
    process.start()

    # Wait for servers to start
    time.sleep(2)

    yield {
        "proxy": f"http://127.0.0.1:{proxy_port}",
        "admin": f"http://127.0.0.1:{admin_port}",
    }

    process.terminate()
    process.join(timeout=5)


@pytest_asyncio.fixture
async def http_client():
    """Async HTTP client."""
    async with httpx.AsyncClient(timeout=30.0) as client:
        yield client


@pytest_asyncio.fixture
async def admin_token(pylon_servers, http_client):
    """Get admin JWT token."""
    response = await http_client.post(
        f"{pylon_servers['admin']}/login",
        json={"password": "test123"}
    )
    assert response.status_code == 200
    return response.json()["token"]


@pytest_asyncio.fixture
async def api_key(pylon_servers, http_client, admin_token):
    """Create and return an API key."""
    response = await http_client.post(
        f"{pylon_servers['admin']}/api-keys",
        json={"description": "Test key"},
        headers={"Authorization": f"Bearer {admin_token}"}
    )
    assert response.status_code == 200
    return response.json()["key"]
