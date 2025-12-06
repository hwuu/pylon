"""
API Key model.
"""

import uuid
from datetime import datetime, timezone
from enum import Enum
from typing import Optional

from sqlalchemy import String, DateTime, Text, Enum as SQLEnum
from sqlalchemy.orm import Mapped, mapped_column

from pylon.models.database import Base


def _utcnow():
    """Get current UTC time."""
    return datetime.now(timezone.utc)


class Priority(str, Enum):
    """API Key priority levels."""

    HIGH = "high"
    NORMAL = "normal"
    LOW = "low"


class ApiKey(Base):
    """API Key model for user authentication."""

    __tablename__ = "api_keys"

    id: Mapped[str] = mapped_column(
        String(36), primary_key=True, default=lambda: str(uuid.uuid4())
    )
    key_hash: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    key_prefix: Mapped[str] = mapped_column(String(10))
    description: Mapped[str] = mapped_column(String(255), default="")
    priority: Mapped[Priority] = mapped_column(
        SQLEnum(Priority), default=Priority.NORMAL
    )
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow)
    expires_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    revoked_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    rate_limit_config: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    @property
    def is_expired(self) -> bool:
        """Check if the API key is expired."""
        if self.expires_at is None:
            return False
        now = datetime.now(timezone.utc)
        # Handle naive datetime (no timezone info)
        if self.expires_at.tzinfo is None:
            return now.replace(tzinfo=None) > self.expires_at
        return now > self.expires_at

    @property
    def is_revoked(self) -> bool:
        """Check if the API key is revoked."""
        return self.revoked_at is not None

    @property
    def is_valid(self) -> bool:
        """Check if the API key is valid (not expired and not revoked)."""
        return not self.is_expired and not self.is_revoked

    def __repr__(self) -> str:
        return f"<ApiKey(id={self.id}, prefix={self.key_prefix}, priority={self.priority.value})>"
