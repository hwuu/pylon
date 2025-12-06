"""
Data cleanup service for removing expired request logs.
"""

import asyncio
import logging
from datetime import datetime, timezone, timedelta

from sqlalchemy import delete
from sqlalchemy.ext.asyncio import AsyncSession

from pylon.models.request_log import RequestLog
from pylon.config import DataRetentionConfig


logger = logging.getLogger(__name__)


class CleanupService:
    """Service for cleaning up expired data."""

    def __init__(
        self,
        session_factory,
        config: DataRetentionConfig,
    ):
        self.session_factory = session_factory
        self.config = config
        self._task: asyncio.Task | None = None
        self._running = False

    async def cleanup_old_logs(self) -> int:
        """
        Delete request logs older than retention period.

        Returns:
            Number of deleted records.
        """
        cutoff_time = datetime.now(timezone.utc) - timedelta(days=self.config.days)

        async with self.session_factory() as session:
            # Delete old logs
            result = await session.execute(
                delete(RequestLog).where(RequestLog.request_time < cutoff_time)
            )
            await session.commit()

            deleted_count = result.rowcount
            if deleted_count > 0:
                logger.info(f"Cleaned up {deleted_count} request logs older than {self.config.days} days")

            return deleted_count

    async def _cleanup_loop(self):
        """Background cleanup loop."""
        interval_seconds = self.config.cleanup_interval_hours * 3600

        while self._running:
            try:
                await self.cleanup_old_logs()
            except Exception as e:
                logger.error(f"Cleanup failed: {e}")

            # Wait for next interval
            await asyncio.sleep(interval_seconds)

    def start(self):
        """Start the background cleanup task."""
        if self._task is not None:
            logger.warning("Cleanup service is already running")
            return

        self._running = True
        self._task = asyncio.create_task(self._cleanup_loop())
        logger.info(
            f"Cleanup service started (retention: {self.config.days} days, "
            f"interval: {self.config.cleanup_interval_hours} hours)"
        )

    async def stop(self):
        """Stop the background cleanup task."""
        if self._task is None:
            return

        self._running = False
        self._task.cancel()

        try:
            await self._task
        except asyncio.CancelledError:
            pass

        self._task = None
        logger.info("Cleanup service stopped")
