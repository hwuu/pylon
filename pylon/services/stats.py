"""
Statistics service for request log analysis.
"""

from datetime import datetime, timezone, timedelta
from typing import Optional, List

from sqlalchemy import select, func, and_, case
from sqlalchemy.ext.asyncio import AsyncSession

from pylon.models.request_log import RequestLog


class StatsService:
    """Service for computing statistics from request logs."""

    def __init__(self, session: AsyncSession):
        self.session = session

    def _get_default_time_range(
        self,
        start_time: Optional[datetime],
        end_time: Optional[datetime],
    ) -> tuple[datetime, datetime]:
        """Get default time range if not specified."""
        if end_time is None:
            end_time = datetime.now(timezone.utc)
        if start_time is None:
            start_time = end_time - timedelta(days=7)
        return start_time, end_time

    def _build_base_query_conditions(
        self,
        start_time: datetime,
        end_time: datetime,
        api_key_id: Optional[str] = None,
        api_identifier: Optional[str] = None,
    ):
        """Build base query conditions for filtering."""
        conditions = [
            RequestLog.request_time >= start_time,
            RequestLog.request_time <= end_time,
        ]
        if api_key_id:
            conditions.append(RequestLog.api_key_id == api_key_id)
        if api_identifier:
            conditions.append(RequestLog.api_identifier == api_identifier)
        return conditions

    async def get_stats(
        self,
        start_time: Optional[datetime] = None,
        end_time: Optional[datetime] = None,
        api_key_id: Optional[str] = None,
        api_identifier: Optional[str] = None,
    ) -> dict:
        """
        Get statistics for the given filters.

        Args:
            start_time: Start of time range (default: 7 days ago)
            end_time: End of time range (default: now)
            api_key_id: Filter by specific API key
            api_identifier: Filter by specific API identifier

        Returns:
            Dictionary with statistics
        """
        start_time, end_time = self._get_default_time_range(start_time, end_time)
        conditions = self._build_base_query_conditions(
            start_time, end_time, api_key_id, api_identifier
        )

        # Build aggregation query
        query = select(
            func.count(RequestLog.id).label("total_requests"),
            func.sum(RequestLog.sse_message_count).label("total_sse_messages"),
            func.avg(RequestLog.response_time_ms).label("avg_response_time_ms"),
            func.count(case((RequestLog.is_sse == True, 1))).label("sse_connections"),
            func.count(
                case(
                    (
                        and_(
                            RequestLog.response_status >= 200,
                            RequestLog.response_status < 300,
                        ),
                        1,
                    )
                )
            ).label("success_count"),
            func.count(
                case((RequestLog.response_status == 429, 1))
            ).label("rate_limited_count"),
        ).where(and_(*conditions))

        result = await self.session.execute(query)
        row = result.one()

        total_requests = row.total_requests or 0
        success_count = row.success_count or 0
        total_sse_messages = row.total_sse_messages or 0

        return {
            "start_time": start_time.isoformat(),
            "end_time": end_time.isoformat(),
            "total_requests": total_requests,
            "total_sse_messages": total_sse_messages,
            "total_count": total_requests + total_sse_messages,
            "success_rate": round(success_count / total_requests * 100, 2) if total_requests > 0 else 0,
            "avg_response_time_ms": round(row.avg_response_time_ms or 0, 2),
            "sse_connections": row.sse_connections or 0,
            "rate_limited_count": row.rate_limited_count or 0,
        }

    async def get_global_stats(
        self,
        start_time: Optional[datetime] = None,
        end_time: Optional[datetime] = None,
    ) -> dict:
        """Get global statistics."""
        return await self.get_stats(start_time=start_time, end_time=end_time)

    async def get_user_stats(
        self,
        api_key_id: str,
        start_time: Optional[datetime] = None,
        end_time: Optional[datetime] = None,
    ) -> dict:
        """Get statistics for a specific user (API key)."""
        stats = await self.get_stats(
            start_time=start_time,
            end_time=end_time,
            api_key_id=api_key_id,
        )
        stats["api_key_id"] = api_key_id
        return stats

    async def get_api_stats(
        self,
        api_identifier: str,
        start_time: Optional[datetime] = None,
        end_time: Optional[datetime] = None,
    ) -> dict:
        """Get statistics for a specific API."""
        stats = await self.get_stats(
            start_time=start_time,
            end_time=end_time,
            api_identifier=api_identifier,
        )
        stats["api_identifier"] = api_identifier
        return stats

    async def get_users_summary(
        self,
        start_time: Optional[datetime] = None,
        end_time: Optional[datetime] = None,
    ) -> List[dict]:
        """Get statistics grouped by user (API key)."""
        start_time, end_time = self._get_default_time_range(start_time, end_time)
        conditions = self._build_base_query_conditions(start_time, end_time)

        query = (
            select(
                RequestLog.api_key_id,
                func.count(RequestLog.id).label("total_requests"),
                func.sum(RequestLog.sse_message_count).label("total_sse_messages"),
                func.avg(RequestLog.response_time_ms).label("avg_response_time_ms"),
                func.count(case((RequestLog.is_sse == True, 1))).label("sse_connections"),
                func.count(
                    case(
                        (
                            and_(
                                RequestLog.response_status >= 200,
                                RequestLog.response_status < 300,
                            ),
                            1,
                        )
                    )
                ).label("success_count"),
                func.count(
                    case((RequestLog.response_status == 429, 1))
                ).label("rate_limited_count"),
            )
            .where(and_(*conditions))
            .group_by(RequestLog.api_key_id)
            .order_by(func.count(RequestLog.id).desc())
        )

        result = await self.session.execute(query)
        rows = result.all()

        return [
            {
                "api_key_id": row.api_key_id,
                "total_requests": row.total_requests or 0,
                "total_sse_messages": row.total_sse_messages or 0,
                "total_count": (row.total_requests or 0) + (row.total_sse_messages or 0),
                "success_rate": round(
                    (row.success_count or 0) / row.total_requests * 100, 2
                ) if row.total_requests > 0 else 0,
                "avg_response_time_ms": round(row.avg_response_time_ms or 0, 2),
                "sse_connections": row.sse_connections or 0,
                "rate_limited_count": row.rate_limited_count or 0,
            }
            for row in rows
        ]

    async def get_apis_summary(
        self,
        start_time: Optional[datetime] = None,
        end_time: Optional[datetime] = None,
    ) -> List[dict]:
        """Get statistics grouped by API identifier."""
        start_time, end_time = self._get_default_time_range(start_time, end_time)
        conditions = self._build_base_query_conditions(start_time, end_time)

        query = (
            select(
                RequestLog.api_identifier,
                func.count(RequestLog.id).label("total_requests"),
                func.sum(RequestLog.sse_message_count).label("total_sse_messages"),
                func.avg(RequestLog.response_time_ms).label("avg_response_time_ms"),
                func.count(case((RequestLog.is_sse == True, 1))).label("sse_connections"),
                func.count(
                    case(
                        (
                            and_(
                                RequestLog.response_status >= 200,
                                RequestLog.response_status < 300,
                            ),
                            1,
                        )
                    )
                ).label("success_count"),
                func.count(
                    case((RequestLog.response_status == 429, 1))
                ).label("rate_limited_count"),
            )
            .where(and_(*conditions))
            .group_by(RequestLog.api_identifier)
            .order_by(func.count(RequestLog.id).desc())
        )

        result = await self.session.execute(query)
        rows = result.all()

        return [
            {
                "api_identifier": row.api_identifier,
                "total_requests": row.total_requests or 0,
                "total_sse_messages": row.total_sse_messages or 0,
                "total_count": (row.total_requests or 0) + (row.total_sse_messages or 0),
                "success_rate": round(
                    (row.success_count or 0) / row.total_requests * 100, 2
                ) if row.total_requests > 0 else 0,
                "avg_response_time_ms": round(row.avg_response_time_ms or 0, 2),
                "sse_connections": row.sse_connections or 0,
                "rate_limited_count": row.rate_limited_count or 0,
            }
            for row in rows
        ]
