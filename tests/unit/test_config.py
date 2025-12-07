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
    DatabaseConfig,
    AdminConfig,
    LoggingConfig,
)


class TestLoadConfig:
    """Tests for load_config function."""

    def test_load_minimal_config(self):
        """Test loading a minimal config file."""
        config_content = """
server:
  proxy_port: 9000
"""
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".yaml", delete=False, encoding="utf-8"
        ) as f:
            f.write(config_content)
            f.flush()

            config = load_config(f.name)

            assert config.server.proxy_port == 9000
            assert config.server.admin_port == 8001  # default

        Path(f.name).unlink()

    def test_load_full_config(self):
        """Test loading a full config file."""
        config_content = """
server:
  proxy_port: 8000
  admin_port: 8001
  host: "127.0.0.1"

database:
  url: "sqlite+aiosqlite:///./test.db"

admin:
  password_hash: "$2b$12$test"
  jwt_secret: "test-secret"
  jwt_expire_hours: 12

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

            # Database
            assert config.database.url == "sqlite+aiosqlite:///./test.db"

            # Admin
            assert config.admin.password_hash == "$2b$12$test"
            assert config.admin.jwt_secret == "test-secret"
            assert config.admin.jwt_expire_hours == 12

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
server:
  proxy_port: 8000
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
            assert config.database.url == "sqlite+aiosqlite:///./data/pylon.db"
            assert config.admin.jwt_expire_hours == 24
            assert config.logging.level == "INFO"

        Path(f.name).unlink()
