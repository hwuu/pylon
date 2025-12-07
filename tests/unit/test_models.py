"""
Tests for database models.
"""

import pytest
from datetime import datetime, timedelta, timezone
import tempfile
import os

from pylon.models import ApiKey, Priority, RequestLog, Base
from pylon.models.database import create_db_engine, create_session_factory
from pylon.config import DatabaseConfig


@pytest.fixture
def db_session():
    """Create a temporary database session for testing."""
    with tempfile.TemporaryDirectory() as tmpdir:
        db_path = os.path.join(tmpdir, "test.db")
        # Use the new DatabaseConfig format with url
        config = DatabaseConfig(url=f"sqlite:///{db_path}")
        engine = create_db_engine(config)
        Base.metadata.create_all(engine)
        Session = create_session_factory(engine)
        session = Session()
        try:
            yield session
        finally:
            session.close()
            engine.dispose()


class TestApiKey:
    """Tests for ApiKey model."""

    def test_create_api_key(self, db_session):
        """Test creating an API key."""
        api_key = ApiKey(
            key_hash="abc123def456",
            key_prefix="sk-abc",
            description="Test key",
            priority=Priority.NORMAL,
        )
        db_session.add(api_key)
        db_session.commit()

        # Retrieve and verify
        retrieved = db_session.query(ApiKey).filter_by(key_hash="abc123def456").first()
        assert retrieved is not None
        assert retrieved.key_prefix == "sk-abc"
        assert retrieved.description == "Test key"
        assert retrieved.priority == Priority.NORMAL
        assert retrieved.is_valid is True

    def test_api_key_is_expired(self, db_session):
        """Test API key expiration check."""
        now = datetime.now(timezone.utc)

        # Not expired
        api_key1 = ApiKey(
            key_hash="key1",
            key_prefix="sk-1",
            expires_at=now + timedelta(days=1),
        )
        assert api_key1.is_expired is False
        assert api_key1.is_valid is True

        # Expired
        api_key2 = ApiKey(
            key_hash="key2",
            key_prefix="sk-2",
            expires_at=now - timedelta(days=1),
        )
        assert api_key2.is_expired is True
        assert api_key2.is_valid is False

        # No expiration
        api_key3 = ApiKey(
            key_hash="key3",
            key_prefix="sk-3",
            expires_at=None,
        )
        assert api_key3.is_expired is False
        assert api_key3.is_valid is True

    def test_api_key_is_revoked(self, db_session):
        """Test API key revocation check."""
        now = datetime.now(timezone.utc)

        # Not revoked
        api_key1 = ApiKey(
            key_hash="key1",
            key_prefix="sk-1",
        )
        assert api_key1.is_revoked is False
        assert api_key1.is_valid is True

        # Revoked
        api_key2 = ApiKey(
            key_hash="key2",
            key_prefix="sk-2",
            revoked_at=now,
        )
        assert api_key2.is_revoked is True
        assert api_key2.is_valid is False

    def test_api_key_priority(self, db_session):
        """Test API key priorities."""
        high_key = ApiKey(
            key_hash="high_key",
            key_prefix="sk-h",
            priority=Priority.HIGH,
        )
        low_key = ApiKey(
            key_hash="low_key",
            key_prefix="sk-l",
            priority=Priority.LOW,
        )

        db_session.add_all([high_key, low_key])
        db_session.commit()

        retrieved_high = db_session.query(ApiKey).filter_by(key_hash="high_key").first()
        retrieved_low = db_session.query(ApiKey).filter_by(key_hash="low_key").first()

        assert retrieved_high.priority == Priority.HIGH
        assert retrieved_low.priority == Priority.LOW


class TestRequestLog:
    """Tests for RequestLog model."""

    def test_create_request_log(self, db_session):
        """Test creating a request log."""
        # First create an API key
        api_key = ApiKey(
            key_hash="test_key",
            key_prefix="sk-t",
        )
        db_session.add(api_key)
        db_session.commit()

        # Create a request log
        log = RequestLog(
            api_key_id=api_key.id,
            api_identifier="POST /v1/chat",
            request_path="/v1/chat/completions",
            request_method="POST",
            response_status=200,
            response_time_ms=150,
            client_ip="127.0.0.1",
            is_sse=False,
            sse_message_count=0,
        )
        db_session.add(log)
        db_session.commit()

        # Retrieve and verify
        retrieved = db_session.query(RequestLog).filter_by(api_key_id=api_key.id).first()
        assert retrieved is not None
        assert retrieved.api_identifier == "POST /v1/chat"
        assert retrieved.response_status == 200
        assert retrieved.response_time_ms == 150
        assert retrieved.is_sse is False

    def test_sse_request_log(self, db_session):
        """Test creating an SSE request log."""
        api_key = ApiKey(
            key_hash="sse_key",
            key_prefix="sk-s",
        )
        db_session.add(api_key)
        db_session.commit()

        log = RequestLog(
            api_key_id=api_key.id,
            api_identifier="GET /v1/stream",
            request_path="/v1/stream",
            request_method="GET",
            response_status=200,
            response_time_ms=5000,
            client_ip="127.0.0.1",
            is_sse=True,
            sse_message_count=50,
        )
        db_session.add(log)
        db_session.commit()

        retrieved = db_session.query(RequestLog).filter_by(is_sse=True).first()
        assert retrieved is not None
        assert retrieved.is_sse is True
        assert retrieved.sse_message_count == 50
