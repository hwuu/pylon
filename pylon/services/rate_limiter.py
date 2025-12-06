"""
Rate limiter service for controlling request rates.
"""

import asyncio
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Optional

from pylon.config import RateLimitConfig, RateLimitRule


class RateLimitResult(Enum):
    """Result of a rate limit check."""

    ALLOWED = "allowed"
    USER_LIMIT_EXCEEDED = "user_limit_exceeded"
    API_LIMIT_EXCEEDED = "api_limit_exceeded"
    GLOBAL_LIMIT_EXCEEDED = "global_limit_exceeded"


@dataclass
class RateLimitStatus:
    """Status of a rate limit check."""

    result: RateLimitResult
    message: str = ""

    @property
    def allowed(self) -> bool:
        return self.result == RateLimitResult.ALLOWED


@dataclass
class Counter:
    """A counter with sliding window for rate limiting."""

    count: int = 0
    window_start: datetime = field(default_factory=lambda: datetime.now(timezone.utc))


class RateLimiter:
    """
    In-memory rate limiter with support for:
    - Concurrent request limiting
    - Request frequency limiting (per minute)
    - SSE connection limiting
    """

    def __init__(self, config: RateLimitConfig):
        self.config = config
        self._lock = asyncio.Lock()

        # Concurrent request counters
        self._global_concurrent = 0
        self._user_concurrent: dict[str, int] = defaultdict(int)

        # SSE connection counters
        self._global_sse_connections = 0
        self._user_sse_connections: dict[str, int] = defaultdict(int)

        # Request frequency counters (sliding window per minute)
        self._global_requests = Counter()
        self._user_requests: dict[str, Counter] = defaultdict(Counter)
        self._api_requests: dict[str, Counter] = defaultdict(Counter)

    def _get_user_limit(self, user_id: str) -> RateLimitRule:
        """Get rate limit rule for a user (from config or default)."""
        # TODO: Support per-user config from database
        return self.config.default_user

    def _get_api_limit(self, api_identifier: str) -> Optional[RateLimitRule]:
        """Get rate limit rule for an API."""
        return self.config.apis.get(api_identifier)

    def _reset_counter_if_needed(self, counter: Counter) -> None:
        """Reset counter if the window has passed (1 minute)."""
        now = datetime.now(timezone.utc)
        elapsed = (now - counter.window_start).total_seconds()
        if elapsed >= 60:
            counter.count = 0
            counter.window_start = now

    async def check_rate_limit(
        self,
        user_id: str,
        api_identifier: str,
        is_sse: bool = False,
    ) -> RateLimitStatus:
        """
        Check if a request is allowed under rate limits.

        Args:
            user_id: The API key ID
            api_identifier: The API identifier (e.g., "POST /v1/chat/completions")
            is_sse: Whether this is an SSE connection

        Returns:
            RateLimitStatus indicating if request is allowed.
        """
        async with self._lock:
            user_limit = self._get_user_limit(user_id)
            api_limit = self._get_api_limit(api_identifier)
            global_limit = self.config.global_limit

            # Check user limits first
            if is_sse:
                if (
                    user_limit.max_sse_connections is not None
                    and self._user_sse_connections[user_id] >= user_limit.max_sse_connections
                ):
                    return RateLimitStatus(
                        result=RateLimitResult.USER_LIMIT_EXCEEDED,
                        message="Your SSE connection limit exceeded",
                    )
            else:
                if (
                    user_limit.max_concurrent is not None
                    and self._user_concurrent[user_id] >= user_limit.max_concurrent
                ):
                    return RateLimitStatus(
                        result=RateLimitResult.USER_LIMIT_EXCEEDED,
                        message="Your concurrent request limit exceeded",
                    )

            # Check user request frequency
            if user_limit.max_requests_per_minute is not None:
                user_counter = self._user_requests[user_id]
                self._reset_counter_if_needed(user_counter)
                if user_counter.count >= user_limit.max_requests_per_minute:
                    return RateLimitStatus(
                        result=RateLimitResult.USER_LIMIT_EXCEEDED,
                        message="Your request rate limit exceeded",
                    )

            # Check API limits
            if api_limit is not None and api_limit.max_requests_per_minute is not None:
                api_counter = self._api_requests[api_identifier]
                self._reset_counter_if_needed(api_counter)
                if api_counter.count >= api_limit.max_requests_per_minute:
                    return RateLimitStatus(
                        result=RateLimitResult.API_LIMIT_EXCEEDED,
                        message="API rate limit exceeded",
                    )

            # Check global limits
            if is_sse:
                if (
                    global_limit.max_sse_connections is not None
                    and self._global_sse_connections >= global_limit.max_sse_connections
                ):
                    return RateLimitStatus(
                        result=RateLimitResult.GLOBAL_LIMIT_EXCEEDED,
                        message="System SSE connection limit exceeded",
                    )
            else:
                if (
                    global_limit.max_concurrent is not None
                    and self._global_concurrent >= global_limit.max_concurrent
                ):
                    return RateLimitStatus(
                        result=RateLimitResult.GLOBAL_LIMIT_EXCEEDED,
                        message="System busy, please try again later",
                    )

            # Check global request frequency
            if global_limit.max_requests_per_minute is not None:
                self._reset_counter_if_needed(self._global_requests)
                if self._global_requests.count >= global_limit.max_requests_per_minute:
                    return RateLimitStatus(
                        result=RateLimitResult.GLOBAL_LIMIT_EXCEEDED,
                        message="System request rate limit exceeded",
                    )

            return RateLimitStatus(result=RateLimitResult.ALLOWED)

    async def acquire(
        self,
        user_id: str,
        api_identifier: str,
        is_sse: bool = False,
    ) -> None:
        """
        Acquire rate limit slots (increment counters).

        Should be called after check_rate_limit returns ALLOWED.
        """
        async with self._lock:
            # Increment concurrent/SSE counters
            if is_sse:
                self._global_sse_connections += 1
                self._user_sse_connections[user_id] += 1
            else:
                self._global_concurrent += 1
                self._user_concurrent[user_id] += 1

            # Increment request frequency counters
            self._reset_counter_if_needed(self._global_requests)
            self._global_requests.count += 1

            user_counter = self._user_requests[user_id]
            self._reset_counter_if_needed(user_counter)
            user_counter.count += 1

            api_limit = self._get_api_limit(api_identifier)
            if api_limit is not None:
                api_counter = self._api_requests[api_identifier]
                self._reset_counter_if_needed(api_counter)
                api_counter.count += 1

    async def release(
        self,
        user_id: str,
        is_sse: bool = False,
    ) -> None:
        """
        Release rate limit slots (decrement concurrent counters).

        Should be called when request completes.
        """
        async with self._lock:
            if is_sse:
                self._global_sse_connections = max(0, self._global_sse_connections - 1)
                self._user_sse_connections[user_id] = max(
                    0, self._user_sse_connections[user_id] - 1
                )
            else:
                self._global_concurrent = max(0, self._global_concurrent - 1)
                self._user_concurrent[user_id] = max(
                    0, self._user_concurrent[user_id] - 1
                )

    async def increment_request_count(
        self,
        user_id: str,
        api_identifier: str,
        count: int = 1,
    ) -> None:
        """
        Increment request count (for SSE messages).

        Args:
            user_id: The API key ID
            api_identifier: The API identifier
            count: Number to increment by
        """
        async with self._lock:
            # Increment global counter
            self._reset_counter_if_needed(self._global_requests)
            self._global_requests.count += count

            # Increment user counter
            user_counter = self._user_requests[user_id]
            self._reset_counter_if_needed(user_counter)
            user_counter.count += count

            # Increment API counter if configured
            api_limit = self._get_api_limit(api_identifier)
            if api_limit is not None:
                api_counter = self._api_requests[api_identifier]
                self._reset_counter_if_needed(api_counter)
                api_counter.count += count

    async def check_request_frequency(
        self,
        user_id: str,
        api_identifier: str,
    ) -> RateLimitStatus:
        """
        Check only request frequency limits (for SSE message counting).

        Returns:
            RateLimitStatus indicating if more requests are allowed.
        """
        async with self._lock:
            user_limit = self._get_user_limit(user_id)
            api_limit = self._get_api_limit(api_identifier)
            global_limit = self.config.global_limit

            # Check user request frequency
            if user_limit.max_requests_per_minute is not None:
                user_counter = self._user_requests[user_id]
                self._reset_counter_if_needed(user_counter)
                if user_counter.count >= user_limit.max_requests_per_minute:
                    return RateLimitStatus(
                        result=RateLimitResult.USER_LIMIT_EXCEEDED,
                        message="Your request rate limit exceeded",
                    )

            # Check API limits
            if api_limit is not None and api_limit.max_requests_per_minute is not None:
                api_counter = self._api_requests[api_identifier]
                self._reset_counter_if_needed(api_counter)
                if api_counter.count >= api_limit.max_requests_per_minute:
                    return RateLimitStatus(
                        result=RateLimitResult.API_LIMIT_EXCEEDED,
                        message="API rate limit exceeded",
                    )

            # Check global request frequency
            if global_limit.max_requests_per_minute is not None:
                self._reset_counter_if_needed(self._global_requests)
                if self._global_requests.count >= global_limit.max_requests_per_minute:
                    return RateLimitStatus(
                        result=RateLimitResult.GLOBAL_LIMIT_EXCEEDED,
                        message="System request rate limit exceeded",
                    )

            return RateLimitStatus(result=RateLimitResult.ALLOWED)

    def get_stats(self) -> dict:
        """Get current rate limiter statistics."""
        return {
            "global_concurrent": self._global_concurrent,
            "global_sse_connections": self._global_sse_connections,
            "global_requests_this_minute": self._global_requests.count,
        }
