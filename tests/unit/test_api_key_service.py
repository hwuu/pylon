"""
Tests for API key management service.
"""

import pytest
import pytest_asyncio
from datetime import datetime, timedelta, timezone
import tempfile
import os

from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker, AsyncSession

from pylon.models import ApiKey, Priority, Base
from pylon.services.api_key_service import ApiKeyService


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
async def api_key_service(db_session):
    """Create API key service."""
    return ApiKeyService(db_session)


class TestCreateApiKey:
    """Tests for creating API keys."""

    @pytest.mark.asyncio
    async def test_create_basic_key(self, api_key_service):
        """Test creating a basic API key."""
        raw_key, api_key = await api_key_service.create_api_key(
            description="Test key"
        )

        assert raw_key.startswith("sk-")
        assert len(raw_key) == 35  # sk- + 32 chars
        assert api_key.description == "Test key"
        assert api_key.priority == Priority.NORMAL
        assert api_key.expires_at is None
        assert api_key.revoked_at is None

    @pytest.mark.asyncio
    async def test_create_key_with_priority(self, api_key_service):
        """Test creating key with specific priority."""
        _, api_key = await api_key_service.create_api_key(
            description="High priority key",
            priority=Priority.HIGH,
        )

        assert api_key.priority == Priority.HIGH

    @pytest.mark.asyncio
    async def test_create_key_with_expiration(self, api_key_service):
        """Test creating key with expiration."""
        _, api_key = await api_key_service.create_api_key(
            description="Expiring key",
            expires_in_days=30,
        )

        assert api_key.expires_at is not None
        # Should expire in approximately 30 days
        # Note: SQLite returns naive datetime, so we compare without timezone
        expected = datetime.now(timezone.utc).replace(tzinfo=None) + timedelta(days=30)
        expires_at = api_key.expires_at
        if expires_at.tzinfo is not None:
            expires_at = expires_at.replace(tzinfo=None)
        diff = abs((expires_at - expected).total_seconds())
        assert diff < 60  # Within 1 minute

    @pytest.mark.asyncio
    async def test_create_key_with_rate_limit(self, api_key_service):
        """Test creating key with custom rate limit."""
        _, api_key = await api_key_service.create_api_key(
            description="Limited key",
            rate_limit_config={"max_concurrent": 2, "max_requests_per_minute": 30},
        )

        assert api_key.rate_limit_config is not None
        import json
        config = json.loads(api_key.rate_limit_config)
        assert config["max_concurrent"] == 2


class TestListApiKeys:
    """Tests for listing API keys."""

    @pytest.mark.asyncio
    async def test_list_empty(self, api_key_service):
        """Test listing when no keys exist."""
        keys = await api_key_service.list_api_keys()
        assert keys == []

    @pytest.mark.asyncio
    async def test_list_active_keys(self, api_key_service):
        """Test listing active keys."""
        await api_key_service.create_api_key(description="Key 1")
        await api_key_service.create_api_key(description="Key 2")

        keys = await api_key_service.list_api_keys()
        assert len(keys) == 2

    @pytest.mark.asyncio
    async def test_list_excludes_revoked(self, api_key_service):
        """Test that revoked keys are excluded by default."""
        _, key1 = await api_key_service.create_api_key(description="Active")
        _, key2 = await api_key_service.create_api_key(description="Revoked")
        await api_key_service.revoke_api_key(key2.id)

        keys = await api_key_service.list_api_keys()
        assert len(keys) == 1
        assert keys[0].description == "Active"

    @pytest.mark.asyncio
    async def test_list_includes_revoked(self, api_key_service):
        """Test listing with revoked keys included."""
        await api_key_service.create_api_key(description="Active")
        _, key2 = await api_key_service.create_api_key(description="Revoked")
        await api_key_service.revoke_api_key(key2.id)

        keys = await api_key_service.list_api_keys(include_revoked=True)
        assert len(keys) == 2


class TestGetApiKey:
    """Tests for getting a single API key."""

    @pytest.mark.asyncio
    async def test_get_existing_key(self, api_key_service):
        """Test getting an existing key."""
        _, created = await api_key_service.create_api_key(description="Test")

        fetched = await api_key_service.get_api_key(created.id)
        assert fetched is not None
        assert fetched.id == created.id
        assert fetched.description == "Test"

    @pytest.mark.asyncio
    async def test_get_nonexistent_key(self, api_key_service):
        """Test getting a non-existent key."""
        fetched = await api_key_service.get_api_key("nonexistent-id")
        assert fetched is None


class TestUpdateApiKey:
    """Tests for updating API keys."""

    @pytest.mark.asyncio
    async def test_update_description(self, api_key_service):
        """Test updating key description."""
        _, key = await api_key_service.create_api_key(description="Original")

        updated = await api_key_service.update_api_key(
            key.id, description="Updated"
        )

        assert updated is not None
        assert updated.description == "Updated"

    @pytest.mark.asyncio
    async def test_update_priority(self, api_key_service):
        """Test updating key priority."""
        _, key = await api_key_service.create_api_key(priority=Priority.NORMAL)

        updated = await api_key_service.update_api_key(
            key.id, priority=Priority.HIGH
        )

        assert updated.priority == Priority.HIGH

    @pytest.mark.asyncio
    async def test_update_nonexistent_key(self, api_key_service):
        """Test updating a non-existent key."""
        updated = await api_key_service.update_api_key(
            "nonexistent-id", description="New"
        )
        assert updated is None


class TestRevokeApiKey:
    """Tests for revoking API keys."""

    @pytest.mark.asyncio
    async def test_revoke_key(self, api_key_service):
        """Test revoking a key."""
        _, key = await api_key_service.create_api_key(description="Test")
        assert key.revoked_at is None

        revoked = await api_key_service.revoke_api_key(key.id)

        assert revoked is not None
        assert revoked.revoked_at is not None

    @pytest.mark.asyncio
    async def test_revoke_nonexistent_key(self, api_key_service):
        """Test revoking a non-existent key."""
        revoked = await api_key_service.revoke_api_key("nonexistent-id")
        assert revoked is None


class TestRefreshApiKey:
    """Tests for refreshing API keys."""

    @pytest.mark.asyncio
    async def test_refresh_key(self, api_key_service):
        """Test refreshing a key generates new key but keeps ID."""
        original_raw, original_key = await api_key_service.create_api_key(
            description="Test"
        )
        original_key_hash = original_key.key_hash
        original_key_id = original_key.id

        result = await api_key_service.refresh_api_key(original_key_id)

        assert result is not None
        new_raw, refreshed_key = result

        # Same ID, different key
        assert refreshed_key.id == original_key_id
        assert new_raw != original_raw
        assert new_raw.startswith("sk-")
        assert refreshed_key.key_hash != original_key_hash

    @pytest.mark.asyncio
    async def test_refresh_nonexistent_key(self, api_key_service):
        """Test refreshing a non-existent key."""
        result = await api_key_service.refresh_api_key("nonexistent-id")
        assert result is None


class TestDeleteApiKey:
    """Tests for deleting API keys."""

    @pytest.mark.asyncio
    async def test_delete_key(self, api_key_service):
        """Test deleting a key."""
        _, key = await api_key_service.create_api_key(description="Test")

        deleted = await api_key_service.delete_api_key(key.id)
        assert deleted is True

        # Should no longer exist
        fetched = await api_key_service.get_api_key(key.id)
        assert fetched is None

    @pytest.mark.asyncio
    async def test_delete_nonexistent_key(self, api_key_service):
        """Test deleting a non-existent key."""
        deleted = await api_key_service.delete_api_key("nonexistent-id")
        assert deleted is False


class TestGetApiKeyCount:
    """Tests for API key statistics."""

    @pytest.mark.asyncio
    async def test_count_empty(self, api_key_service):
        """Test count when no keys exist."""
        counts = await api_key_service.get_api_key_count()
        assert counts["total"] == 0
        assert counts["active"] == 0

    @pytest.mark.asyncio
    async def test_count_with_keys(self, api_key_service):
        """Test count with various key states."""
        # Create active keys
        await api_key_service.create_api_key(description="Active 1")
        await api_key_service.create_api_key(description="Active 2")

        # Create and revoke a key
        _, revoked = await api_key_service.create_api_key(description="Revoked")
        await api_key_service.revoke_api_key(revoked.id)

        counts = await api_key_service.get_api_key_count()
        assert counts["total"] == 3
        assert counts["active"] == 2
        assert counts["revoked"] == 1
