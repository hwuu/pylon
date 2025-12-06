"""
Request log model.
"""

from datetime import datetime, timezone

from sqlalchemy import String, DateTime, Integer, Boolean, ForeignKey
from sqlalchemy.orm import Mapped, mapped_column

from pylon.models.database import Base


def _utcnow():
    """Get current UTC time."""
    return datetime.now(timezone.utc)


class RequestLog(Base):
    """Request log model for tracking API usage."""

    __tablename__ = "request_logs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    api_key_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("api_keys.id"), index=True
    )
    api_identifier: Mapped[str] = mapped_column(String(255), index=True)
    request_path: Mapped[str] = mapped_column(String(2048))
    request_method: Mapped[str] = mapped_column(String(10))
    response_status: Mapped[int] = mapped_column(Integer)
    request_time: Mapped[datetime] = mapped_column(DateTime, default=_utcnow, index=True)
    response_time_ms: Mapped[int] = mapped_column(Integer)
    client_ip: Mapped[str] = mapped_column(String(45))
    is_sse: Mapped[bool] = mapped_column(Boolean, default=False)
    sse_message_count: Mapped[int] = mapped_column(Integer, default=0)

    def __repr__(self) -> str:
        return (
            f"<RequestLog(id={self.id}, api_key_id={self.api_key_id}, "
            f"api={self.api_identifier}, status={self.response_status})>"
        )
