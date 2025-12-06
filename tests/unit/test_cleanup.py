"""
Tests for cleanup service.
"""

import pytest
import pytest_asyncio
from datetime import datetime, timedelta, timezone
import tempfile
import os

from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker, AsyncSession

from pylon.models import ApiKey, RequestLog, Base
from pylon.services.cleanup import CleanupService
from pylon.config import DataRetentionConfig


@pytest_asyncio.fixture
async def db_session_factory():
    """Create a temporary database session factory for testing."""
    with tempfile.TemporaryDirectory() as tmpdir:
        db_path = os.path.join(tmpdir, "test.db")
        engine = create_async_engine(f"sqlite+aiosqlite:///{db_path}", echo=False)

        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)

        async_session = async_sessionmaker(
            bind=engine, class_=AsyncSession, expire_on_commit=False
        )

        yield async_session

        await engine.dispose()


@pytest_asyncio.fixture
async def sample_logs(db_session_factory):
    """Create sample request logs with various ages."""
    async with db_session_factory() as session:
        # Create an API key
        api_key = ApiKey(
            id="test-key",
            key_hash="hash",
            key_prefix="sk-t",
        )
        session.add(api_key)
        await session.commit()

        now = datetime.now(timezone.utc)

        # Create logs with different ages
        logs = [
            # Recent logs (within retention period)
            RequestLog(
                api_key_id="test-key",
                api_identifier="POST /v1/chat",
                request_path="/v1/chat",
                request_method="POST",
                response_status=200,
                request_time=now - timedelta(days=1),
                response_time_ms=100,
                client_ip="127.0.0.1",
            ),
            RequestLog(
                api_key_id="test-key",
                api_identifier="POST /v1/chat",
                request_path="/v1/chat",
                request_method="POST",
                response_status=200,
                request_time=now - timedelta(days=7),
                response_time_ms=100,
                client_ip="127.0.0.1",
            ),
            # Old logs (beyond 30 day retention)
            RequestLog(
                api_key_id="test-key",
                api_identifier="POST /v1/chat",
                request_path="/v1/chat",
                request_method="POST",
                response_status=200,
                request_time=now - timedelta(days=31),
                response_time_ms=100,
                client_ip="127.0.0.1",
            ),
            RequestLog(
                api_key_id="test-key",
                api_identifier="POST /v1/chat",
                request_path="/v1/chat",
                request_method="POST",
                response_status=200,
                request_time=now - timedelta(days=60),
                response_time_ms=100,
                client_ip="127.0.0.1",
            ),
            RequestLog(
                api_key_id="test-key",
                api_identifier="POST /v1/chat",
                request_path="/v1/chat",
                request_method="POST",
                response_status=200,
                request_time=now - timedelta(days=90),
                response_time_ms=100,
                client_ip="127.0.0.1",
            ),
        ]

        session.add_all(logs)
        await session.commit()

        return logs


class TestCleanupService:
    """Tests for CleanupService."""

    @pytest.mark.asyncio
    async def test_cleanup_old_logs(self, db_session_factory, sample_logs):
        """Test that old logs are deleted."""
        config = DataRetentionConfig(days=30, cleanup_interval_hours=24)
        service = CleanupService(db_session_factory, config)

        # Run cleanup
        deleted_count = await service.cleanup_old_logs()

        # Should delete 3 logs (31, 60, 90 days old)
        assert deleted_count == 3

        # Verify remaining logs
        async with db_session_factory() as session:
            from sqlalchemy import select, func
            result = await session.execute(select(func.count(RequestLog.id)))
            remaining = result.scalar()
            assert remaining == 2

    @pytest.mark.asyncio
    async def test_cleanup_with_shorter_retention(self, db_session_factory, sample_logs):
        """Test cleanup with shorter retention period."""
        config = DataRetentionConfig(days=5, cleanup_interval_hours=24)
        service = CleanupService(db_session_factory, config)

        # Run cleanup
        deleted_count = await service.cleanup_old_logs()

        # Should delete 4 logs (7, 31, 60, 90 days old)
        assert deleted_count == 4

        # Verify remaining logs
        async with db_session_factory() as session:
            from sqlalchemy import select, func
            result = await session.execute(select(func.count(RequestLog.id)))
            remaining = result.scalar()
            assert remaining == 1

    @pytest.mark.asyncio
    async def test_cleanup_empty_database(self, db_session_factory):
        """Test cleanup on empty database."""
        config = DataRetentionConfig(days=30, cleanup_interval_hours=24)
        service = CleanupService(db_session_factory, config)

        # Run cleanup on empty database
        deleted_count = await service.cleanup_old_logs()

        assert deleted_count == 0

    @pytest.mark.asyncio
    async def test_start_stop_service(self, db_session_factory):
        """Test starting and stopping the cleanup service."""
        config = DataRetentionConfig(days=30, cleanup_interval_hours=24)
        service = CleanupService(db_session_factory, config)

        # Start service
        service.start()
        assert service._task is not None
        assert service._running is True

        # Stop service
        await service.stop()
        assert service._task is None
        assert service._running is False

    @pytest.mark.asyncio
    async def test_double_start(self, db_session_factory):
        """Test that double start doesn't create multiple tasks."""
        config = DataRetentionConfig(days=30, cleanup_interval_hours=24)
        service = CleanupService(db_session_factory, config)

        service.start()
        first_task = service._task

        service.start()  # Should not create new task
        assert service._task is first_task

        await service.stop()
