"""
Tests for authentication service.
"""

import pytest
import pytest_asyncio
from datetime import datetime, timedelta, timezone
import tempfile
import os

from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker, AsyncSession

from pylon.models import ApiKey, Priority, Base
from pylon.services.auth import AuthService, extract_api_key_from_header
from pylon.utils.crypto import generate_api_key, hash_api_key, get_api_key_prefix


@pytest_asyncio.fixture
async def async_db_session():
    """Create a temporary async database session for testing."""
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


class TestExtractApiKeyFromHeader:
    """Tests for extract_api_key_from_header function."""

    def test_valid_bearer_token(self):
        """Test extracting valid bearer token."""
        header = "Bearer sk-a1b2c3d4e5f6"
        result = extract_api_key_from_header(header)
        assert result == "sk-a1b2c3d4e5f6"

    def test_bearer_case_insensitive(self):
        """Test that bearer scheme is case insensitive."""
        assert extract_api_key_from_header("bearer sk-test") == "sk-test"
        assert extract_api_key_from_header("BEARER sk-test") == "sk-test"
        assert extract_api_key_from_header("BeArEr sk-test") == "sk-test"

    def test_none_header(self):
        """Test with None header."""
        assert extract_api_key_from_header(None) is None

    def test_empty_header(self):
        """Test with empty header."""
        assert extract_api_key_from_header("") is None

    def test_missing_scheme(self):
        """Test with missing scheme."""
        assert extract_api_key_from_header("sk-test") is None

    def test_wrong_scheme(self):
        """Test with wrong scheme."""
        assert extract_api_key_from_header("Basic sk-test") is None
        assert extract_api_key_from_header("Token sk-test") is None

    def test_missing_token(self):
        """Test with missing token."""
        assert extract_api_key_from_header("Bearer") is None
        assert extract_api_key_from_header("Bearer ") is None

    def test_token_with_spaces(self):
        """Test token with extra spaces."""
        assert extract_api_key_from_header("Bearer  sk-test  ") == "sk-test"


class TestAuthService:
    """Tests for AuthService class."""

    @pytest.mark.asyncio
    async def test_validate_valid_api_key(self, async_db_session):
        """Test validating a valid API key."""
        # Create an API key
        raw_key = generate_api_key()
        api_key = ApiKey(
            key_hash=hash_api_key(raw_key),
            key_prefix=get_api_key_prefix(raw_key),
            description="Test key",
        )
        async_db_session.add(api_key)
        await async_db_session.commit()

        # Validate
        auth_service = AuthService(async_db_session)
        result = await auth_service.validate_api_key(raw_key)

        assert result is not None
        assert result.id == api_key.id
        assert result.description == "Test key"

    @pytest.mark.asyncio
    async def test_validate_invalid_api_key(self, async_db_session):
        """Test validating an invalid API key."""
        auth_service = AuthService(async_db_session)
        result = await auth_service.validate_api_key("sk-nonexistent")

        assert result is None

    @pytest.mark.asyncio
    async def test_validate_empty_api_key(self, async_db_session):
        """Test validating empty API key."""
        auth_service = AuthService(async_db_session)

        assert await auth_service.validate_api_key("") is None
        assert await auth_service.validate_api_key(None) is None

    @pytest.mark.asyncio
    async def test_validate_expired_api_key(self, async_db_session):
        """Test validating an expired API key."""
        raw_key = generate_api_key()
        api_key = ApiKey(
            key_hash=hash_api_key(raw_key),
            key_prefix=get_api_key_prefix(raw_key),
            expires_at=datetime.now(timezone.utc) - timedelta(days=1),
        )
        async_db_session.add(api_key)
        await async_db_session.commit()

        auth_service = AuthService(async_db_session)
        result = await auth_service.validate_api_key(raw_key)

        assert result is None

    @pytest.mark.asyncio
    async def test_validate_revoked_api_key(self, async_db_session):
        """Test validating a revoked API key."""
        raw_key = generate_api_key()
        api_key = ApiKey(
            key_hash=hash_api_key(raw_key),
            key_prefix=get_api_key_prefix(raw_key),
            revoked_at=datetime.now(timezone.utc),
        )
        async_db_session.add(api_key)
        await async_db_session.commit()

        auth_service = AuthService(async_db_session)
        result = await auth_service.validate_api_key(raw_key)

        assert result is None

    @pytest.mark.asyncio
    async def test_get_api_key_by_id(self, async_db_session):
        """Test getting API key by ID."""
        raw_key = generate_api_key()
        api_key = ApiKey(
            key_hash=hash_api_key(raw_key),
            key_prefix=get_api_key_prefix(raw_key),
            description="Test key",
        )
        async_db_session.add(api_key)
        await async_db_session.commit()

        auth_service = AuthService(async_db_session)
        result = await auth_service.get_api_key_by_id(api_key.id)

        assert result is not None
        assert result.id == api_key.id

    @pytest.mark.asyncio
    async def test_get_api_key_by_id_not_found(self, async_db_session):
        """Test getting non-existent API key by ID."""
        auth_service = AuthService(async_db_session)
        result = await auth_service.get_api_key_by_id("nonexistent-id")

        assert result is None
