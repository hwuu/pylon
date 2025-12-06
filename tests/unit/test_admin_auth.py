"""
Tests for admin authentication service.
"""

import pytest
from datetime import datetime, timedelta, timezone

from pylon.services.admin_auth import AdminAuthService
from pylon.config import AdminConfig
from pylon.utils.crypto import hash_password


class TestAdminAuthService:
    """Tests for AdminAuthService class."""

    @pytest.fixture
    def admin_config(self):
        """Create admin config with test password."""
        password = "test_password_123"
        return AdminConfig(
            password_hash=hash_password(password),
            jwt_secret="test_jwt_secret_key",
            jwt_expire_hours=24,
        )

    @pytest.fixture
    def auth_service(self, admin_config):
        """Create auth service."""
        return AdminAuthService(admin_config)

    def test_authenticate_success(self, auth_service):
        """Test successful authentication."""
        token = auth_service.authenticate("test_password_123")
        assert token is not None
        assert isinstance(token, str)
        assert len(token) > 0

    def test_authenticate_wrong_password(self, auth_service):
        """Test authentication with wrong password."""
        token = auth_service.authenticate("wrong_password")
        assert token is None

    def test_authenticate_empty_password(self, auth_service):
        """Test authentication with empty password."""
        token = auth_service.authenticate("")
        assert token is None

    def test_authenticate_no_password_hash_configured(self):
        """Test authentication when no password hash is configured."""
        config = AdminConfig(password_hash="", jwt_secret="secret")
        service = AdminAuthService(config)
        token = service.authenticate("any_password")
        assert token is None

    def test_verify_token_valid(self, auth_service):
        """Test verifying a valid token."""
        token = auth_service.authenticate("test_password_123")
        assert token is not None

        is_valid = auth_service.verify_token(token)
        assert is_valid is True

    def test_verify_token_invalid(self, auth_service):
        """Test verifying an invalid token."""
        is_valid = auth_service.verify_token("invalid.token.here")
        assert is_valid is False

    def test_verify_token_empty(self, auth_service):
        """Test verifying empty token."""
        is_valid = auth_service.verify_token("")
        assert is_valid is False

    def test_verify_token_no_secret_configured(self):
        """Test verification when no secret is configured."""
        config = AdminConfig(password_hash="hash", jwt_secret="")
        service = AdminAuthService(config)
        is_valid = service.verify_token("some.token.here")
        assert is_valid is False

    def test_verify_token_wrong_secret(self, admin_config):
        """Test verification with wrong secret."""
        service1 = AdminAuthService(admin_config)
        token = service1.authenticate("test_password_123")

        # Create service with different secret
        config2 = AdminConfig(
            password_hash=admin_config.password_hash,
            jwt_secret="different_secret",
        )
        service2 = AdminAuthService(config2)

        is_valid = service2.verify_token(token)
        assert is_valid is False


class TestExtractTokenFromHeader:
    """Tests for extract_token_from_header method."""

    @pytest.fixture
    def auth_service(self):
        """Create auth service."""
        config = AdminConfig(
            password_hash="hash",
            jwt_secret="secret",
        )
        return AdminAuthService(config)

    def test_valid_bearer_token(self, auth_service):
        """Test extracting valid bearer token."""
        token = auth_service.extract_token_from_header("Bearer my_token_123")
        assert token == "my_token_123"

    def test_bearer_case_insensitive(self, auth_service):
        """Test bearer scheme is case insensitive."""
        assert auth_service.extract_token_from_header("bearer token") == "token"
        assert auth_service.extract_token_from_header("BEARER token") == "token"
        assert auth_service.extract_token_from_header("BeArEr token") == "token"

    def test_none_header(self, auth_service):
        """Test with None header."""
        assert auth_service.extract_token_from_header(None) is None

    def test_empty_header(self, auth_service):
        """Test with empty header."""
        assert auth_service.extract_token_from_header("") is None

    def test_missing_scheme(self, auth_service):
        """Test with missing scheme."""
        assert auth_service.extract_token_from_header("my_token") is None

    def test_wrong_scheme(self, auth_service):
        """Test with wrong scheme."""
        assert auth_service.extract_token_from_header("Basic token") is None

    def test_missing_token(self, auth_service):
        """Test with missing token."""
        assert auth_service.extract_token_from_header("Bearer") is None
        assert auth_service.extract_token_from_header("Bearer ") is None

    def test_token_with_spaces(self, auth_service):
        """Test token with extra spaces."""
        token = auth_service.extract_token_from_header("Bearer  my_token  ")
        assert token == "my_token"
