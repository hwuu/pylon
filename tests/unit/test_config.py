"""
Tests for configuration loader.
"""

import pytest
from pathlib import Path
import tempfile

from pylon.config import (
    load_config,
    Config,
    ServerConfig,
    DownstreamConfig,
    RateLimitRule,
)


class TestLoadConfig:
    """Tests for load_config function."""

    def test_load_minimal_config(self):
        """Test loading a minimal config file."""
        config_content = """
server:
  proxy_port: 9000
downstream:
  base_url: "http://example.com"
"""
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".yaml", delete=False, encoding="utf-8"
        ) as f:
            f.write(config_content)
            f.flush()

            config = load_config(f.name)

            assert config.server.proxy_port == 9000
            assert config.server.admin_port == 8001  # default
            assert config.downstream.base_url == "http://example.com"

        Path(f.name).unlink()

    def test_load_full_config(self):
        """Test loading a full config file."""
        config_content = """
server:
  proxy_port: 8000
  admin_port: 8001
  host: "127.0.0.1"

downstream:
  base_url: "https://api.example.com"
  timeout: 60

database:
  type: "sqlite"
  path: "./test.db"

admin:
  password_hash: "$2b$12$test"
  jwt_secret: "test-secret"
  jwt_expire_hours: 12

rate_limit:
  global:
    max_concurrent: 100
    max_requests_per_minute: 1000
    max_sse_connections: 50
  default_user:
    max_concurrent: 10
    max_requests_per_minute: 100
    max_sse_connections: 5
  apis:
    "POST /v1/chat":
      max_requests_per_minute: 50

queue:
  max_size: 200
  timeout: 60

sse:
  idle_timeout: 120

data_retention:
  days: 60
  cleanup_interval_hours: 12

logging:
  level: "DEBUG"
"""
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".yaml", delete=False, encoding="utf-8"
        ) as f:
            f.write(config_content)
            f.flush()

            config = load_config(f.name)

            # Server
            assert config.server.proxy_port == 8000
            assert config.server.admin_port == 8001
            assert config.server.host == "127.0.0.1"

            # Downstream
            assert config.downstream.base_url == "https://api.example.com"
            assert config.downstream.timeout == 60

            # Database
            assert config.database.type == "sqlite"
            assert config.database.path == "./test.db"

            # Admin
            assert config.admin.password_hash == "$2b$12$test"
            assert config.admin.jwt_secret == "test-secret"
            assert config.admin.jwt_expire_hours == 12

            # Rate limit
            assert config.rate_limit.global_limit.max_concurrent == 100
            assert config.rate_limit.global_limit.max_requests_per_minute == 1000
            assert config.rate_limit.default_user.max_concurrent == 10
            assert "POST /v1/chat" in config.rate_limit.apis
            assert config.rate_limit.apis["POST /v1/chat"].max_requests_per_minute == 50

            # Queue
            assert config.queue.max_size == 200
            assert config.queue.timeout == 60

            # SSE
            assert config.sse.idle_timeout == 120

            # Data retention
            assert config.data_retention.days == 60
            assert config.data_retention.cleanup_interval_hours == 12

            # Logging
            assert config.logging.level == "DEBUG"

        Path(f.name).unlink()

    def test_config_file_not_found(self):
        """Test that FileNotFoundError is raised for missing config."""
        with pytest.raises(FileNotFoundError):
            load_config("/nonexistent/path/config.yaml")

    def test_default_values(self):
        """Test that default values are used when not specified."""
        config_content = """
downstream:
  base_url: "http://example.com"
"""
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".yaml", delete=False, encoding="utf-8"
        ) as f:
            f.write(config_content)
            f.flush()

            config = load_config(f.name)

            # Check defaults
            assert config.server.proxy_port == 8000
            assert config.server.admin_port == 8001
            assert config.queue.max_size == 100
            assert config.queue.timeout == 30
            assert config.sse.idle_timeout == 60
            assert config.data_retention.days == 30

        Path(f.name).unlink()

    def test_empty_apis_config(self):
        """Test loading config with empty apis section."""
        config_content = """
downstream:
  base_url: "http://example.com"
rate_limit:
  apis: {}
"""
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".yaml", delete=False, encoding="utf-8"
        ) as f:
            f.write(config_content)
            f.flush()

            config = load_config(f.name)
            assert config.rate_limit.apis == {}

        Path(f.name).unlink()
