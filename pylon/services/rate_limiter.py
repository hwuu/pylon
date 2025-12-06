"""
Rate limiter service for controlling request rates.
"""

import asyncio
import json
import logging
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Optional, Callable, Awaitable

from pylon.config import RateLimitConfig, RateLimitRule, QueueConfig, ApiPattern
from pylon.services.queue import RequestQueue, QueueResult
from pylon.models.api_key import Priority


logger = logging.getLogger(__name__)


class RateLimitResult(Enum):
    """Result of a rate limit check."""

    ALLOWED = "allowed"
    QUEUE_REQUIRED = "queue_required"  # Concurrency full, should queue
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

    @property
    def should_queue(self) -> bool:
        return self.result == RateLimitResult.QUEUE_REQUIRED


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
    - Priority queue for waiting requests
    - Per-user rate limit config from database
    """

    def __init__(
        self,
        config: RateLimitConfig,
        queue_config: Optional[QueueConfig] = None,
        user_config_loader: Optional[Callable[[str], Awaitable[Optional[str]]]] = None,
    ):
        self.config = config
        self._lock = asyncio.Lock()

        # Callback to load user config from database (returns JSON string or None)
        self._user_config_loader = user_config_loader

        # Cache for user rate limit configs (user_id -> RateLimitRule)
        self._user_config_cache: dict[str, RateLimitRule] = {}

        # Concurrent request counters
        self._global_concurrent = 0
        self._user_concurrent: dict[str, int] = defaultdict(int)
        self._api_concurrent: dict[str, int] = defaultdict(int)

        # SSE connection counters
        self._global_sse_connections = 0
        self._user_sse_connections: dict[str, int] = defaultdict(int)
        self._api_sse_connections: dict[str, int] = defaultdict(int)

        # Request frequency counters (sliding window per minute)
        self._global_requests = Counter()
        self._user_requests: dict[str, Counter] = defaultdict(Counter)
        self._api_requests: dict[str, Counter] = defaultdict(Counter)

        # Priority queue for waiting when concurrency is full
        self._queue: Optional[RequestQueue] = None
        if queue_config:
            self._queue = RequestQueue(queue_config, self._try_acquire_slot)

    def set_user_config_loader(
        self, loader: Callable[[str], Awaitable[Optional[str]]]
    ) -> None:
        """Set the callback to load user config from database."""
        self._user_config_loader = loader

    async def _load_user_config(self, user_id: str) -> Optional[RateLimitRule]:
        """Load user rate limit config from database."""
        if self._user_config_loader is None:
            return None

        try:
            config_json = await self._user_config_loader(user_id)
            if config_json is None:
                return None

            config_dict = json.loads(config_json)
            return RateLimitRule(
                max_concurrent=config_dict.get("max_concurrent"),
                max_requests_per_minute=config_dict.get("max_requests_per_minute"),
                max_sse_connections=config_dict.get("max_sse_connections"),
            )
        except (json.JSONDecodeError, TypeError) as e:
            logger.warning(f"Failed to parse user rate limit config for {user_id}: {e}")
            return None

    async def _get_user_limit(self, user_id: str) -> RateLimitRule:
        """Get rate limit rule for a user (from cache, database, or default)."""
        # Check cache first
        if user_id in self._user_config_cache:
            return self._user_config_cache[user_id]

        # Try to load from database
        user_config = await self._load_user_config(user_id)
        if user_config is not None:
            # Merge with default config (user config overrides default)
            merged = RateLimitRule(
                max_concurrent=user_config.max_concurrent
                if user_config.max_concurrent is not None
                else self.config.default_user.max_concurrent,
                max_requests_per_minute=user_config.max_requests_per_minute
                if user_config.max_requests_per_minute is not None
                else self.config.default_user.max_requests_per_minute,
                max_sse_connections=user_config.max_sse_connections
                if user_config.max_sse_connections is not None
                else self.config.default_user.max_sse_connections,
            )
            self._user_config_cache[user_id] = merged
            return merged

        # Use default
        return self.config.default_user

    def invalidate_user_config_cache(self, user_id: str) -> None:
        """Invalidate cached user config (call when user config is updated)."""
        self._user_config_cache.pop(user_id, None)

    def _match_api_pattern(self, pattern: str, api_identifier: str) -> bool:
        """
        Match an API identifier against a pattern.

        Supports:
        - Exact match: "GET /users" matches "GET /users"
        - Parameter match: "GET /users/{id}" matches "GET /users/123"
        - Wildcard match: "POST /v1/*" matches "POST /v1/chat/completions"

        Args:
            pattern: The pattern to match against (e.g., "GET /users/{id}")
            api_identifier: The API identifier (e.g., "GET /users/123")

        Returns:
            True if the pattern matches the api_identifier.
        """
        import re

        # Split into method and path
        pattern_parts = pattern.split(" ", 1)
        api_parts = api_identifier.split(" ", 1)

        if len(pattern_parts) != 2 or len(api_parts) != 2:
            return False

        pattern_method, pattern_path = pattern_parts
        api_method, api_path = api_parts

        # Method must match exactly
        if pattern_method.upper() != api_method.upper():
            return False

        # Convert pattern path to regex
        # {param} -> [^/]+ (matches any segment)
        # * -> .* (matches anything including slashes)
        regex_pattern = re.escape(pattern_path)
        regex_pattern = re.sub(r"\\{[^}]+\\}", r"[^/]+", regex_pattern)
        regex_pattern = regex_pattern.replace(r"\*", r".*")
        regex_pattern = f"^{regex_pattern}$"

        return bool(re.match(regex_pattern, api_path))

    def _get_api_limit(self, api_identifier: str) -> Optional[RateLimitRule]:
        """
        Get rate limit rule for an API.

        Priority:
        1. Exact match in apis dict
        2. Pattern match in api_patterns list (first match wins)
        """
        # Check exact match first
        if api_identifier in self.config.apis:
            return self.config.apis[api_identifier]

        # Check pattern matches
        for api_pattern in self.config.api_patterns:
            if self._match_api_pattern(api_pattern.pattern, api_identifier):
                return api_pattern.rule

        return None

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

        Check order (per design doc 4.2):
        1. User rate limits (frequency, then concurrency/SSE)
        2. API rate limits (frequency)
        3. Global rate limits (frequency, then concurrency/SSE)
        4. If concurrency full but queue available -> QUEUE_REQUIRED

        Args:
            user_id: The API key ID
            api_identifier: The API identifier (e.g., "POST /v1/chat/completions")
            is_sse: Whether this is an SSE connection

        Returns:
            RateLimitStatus indicating if request is allowed or should queue.
        """
        # Load user config outside of lock to avoid blocking
        user_limit = await self._get_user_limit(user_id)

        async with self._lock:
            api_limit = self._get_api_limit(api_identifier)
            global_limit = self.config.global_limit

            # === Step 1: Check User Limits ===

            # Check user request frequency first
            if user_limit.max_requests_per_minute is not None:
                user_counter = self._user_requests[user_id]
                self._reset_counter_if_needed(user_counter)
                if user_counter.count >= user_limit.max_requests_per_minute:
                    return RateLimitStatus(
                        result=RateLimitResult.USER_LIMIT_EXCEEDED,
                        message="Your request rate limit exceeded",
                    )

            # Check user concurrency/SSE limit
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

            # === Step 2: Check API Limits ===

            if api_limit is not None:
                # Check API frequency
                if api_limit.max_requests_per_minute is not None:
                    api_counter = self._api_requests[api_identifier]
                    self._reset_counter_if_needed(api_counter)
                    if api_counter.count >= api_limit.max_requests_per_minute:
                        return RateLimitStatus(
                            result=RateLimitResult.API_LIMIT_EXCEEDED,
                            message="API rate limit exceeded",
                        )

                # Check API concurrency or SSE connections
                if is_sse:
                    if (
                        api_limit.max_sse_connections is not None
                        and self._api_sse_connections[api_identifier] >= api_limit.max_sse_connections
                    ):
                        return RateLimitStatus(
                            result=RateLimitResult.API_LIMIT_EXCEEDED,
                            message="API SSE connection limit exceeded",
                        )
                else:
                    if (
                        api_limit.max_concurrent is not None
                        and self._api_concurrent[api_identifier] >= api_limit.max_concurrent
                    ):
                        return RateLimitStatus(
                            result=RateLimitResult.API_LIMIT_EXCEEDED,
                            message="API concurrent limit exceeded",
                        )

            # === Step 3: Check Global Limits ===

            # Check global request frequency
            if global_limit.max_requests_per_minute is not None:
                self._reset_counter_if_needed(self._global_requests)
                if self._global_requests.count >= global_limit.max_requests_per_minute:
                    return RateLimitStatus(
                        result=RateLimitResult.GLOBAL_LIMIT_EXCEEDED,
                        message="System request rate limit exceeded",
                    )

            # Check global concurrency/SSE - if full, may need to queue
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
                    # Global concurrency full - should queue if queue is available
                    if self._queue is not None:
                        return RateLimitStatus(
                            result=RateLimitResult.QUEUE_REQUIRED,
                            message="Concurrency limit reached, entering queue",
                        )
                    else:
                        return RateLimitStatus(
                            result=RateLimitResult.GLOBAL_LIMIT_EXCEEDED,
                            message="System busy, please try again later",
                        )

            return RateLimitStatus(result=RateLimitResult.ALLOWED)

    async def acquire(
        self,
        user_id: str,
        api_identifier: str,
        is_sse: bool = False,
        skip_global_concurrent: bool = False,
    ) -> None:
        """
        Acquire rate limit slots (increment counters).

        Args:
            user_id: The API key ID
            api_identifier: The API identifier
            is_sse: Whether this is an SSE connection
            skip_global_concurrent: If True, skip incrementing global concurrent
                                   (used when slot was acquired via queue)
        """
        async with self._lock:
            # Increment concurrent/SSE counters
            if is_sse:
                self._global_sse_connections += 1
                self._user_sse_connections[user_id] += 1
                # Increment API SSE counter
                api_limit = self._get_api_limit(api_identifier)
                if api_limit is not None and api_limit.max_sse_connections is not None:
                    self._api_sse_connections[api_identifier] += 1
            else:
                if not skip_global_concurrent:
                    self._global_concurrent += 1
                self._user_concurrent[user_id] += 1

            # Increment API concurrent counter
            api_limit = self._get_api_limit(api_identifier)
            if api_limit is not None and api_limit.max_concurrent is not None and not is_sse:
                self._api_concurrent[api_identifier] += 1

            # Increment request frequency counters
            self._reset_counter_if_needed(self._global_requests)
            self._global_requests.count += 1

            user_counter = self._user_requests[user_id]
            self._reset_counter_if_needed(user_counter)
            user_counter.count += 1

            if api_limit is not None:
                api_counter = self._api_requests[api_identifier]
                self._reset_counter_if_needed(api_counter)
                api_counter.count += 1

    async def release(
        self,
        user_id: str,
        api_identifier: str = "",
        is_sse: bool = False,
    ) -> None:
        """
        Release rate limit slots (decrement concurrent counters).

        Args:
            user_id: The API key ID
            api_identifier: The API identifier (for API concurrent tracking)
            is_sse: Whether this is an SSE connection
        """
        async with self._lock:
            if is_sse:
                self._global_sse_connections = max(0, self._global_sse_connections - 1)
                self._user_sse_connections[user_id] = max(
                    0, self._user_sse_connections[user_id] - 1
                )
                # Decrement API SSE counter
                if api_identifier:
                    api_limit = self._get_api_limit(api_identifier)
                    if api_limit is not None and api_limit.max_sse_connections is not None:
                        self._api_sse_connections[api_identifier] = max(
                            0, self._api_sse_connections[api_identifier] - 1
                        )
            else:
                self._global_concurrent = max(0, self._global_concurrent - 1)
                self._user_concurrent[user_id] = max(
                    0, self._user_concurrent[user_id] - 1
                )

            # Decrement API concurrent counter
            if api_identifier and not is_sse:
                api_limit = self._get_api_limit(api_identifier)
                if api_limit is not None and api_limit.max_concurrent is not None:
                    self._api_concurrent[api_identifier] = max(
                        0, self._api_concurrent[api_identifier] - 1
                    )

        # Notify queue that a slot may be available
        if self._queue is not None and not is_sse:
            await self._queue.notify_slot_available()

    async def _try_acquire_slot(self) -> bool:
        """
        Try to acquire a concurrent slot (callback for queue).

        Returns:
            True if slot was acquired, False otherwise.
        """
        async with self._lock:
            global_limit = self.config.global_limit
            if (
                global_limit.max_concurrent is None
                or self._global_concurrent < global_limit.max_concurrent
            ):
                self._global_concurrent += 1
                return True
            return False

    async def wait_in_queue(
        self,
        user_id: str,
        priority: Priority,
    ) -> QueueResult:
        """
        Wait in the priority queue for a slot to become available.

        Args:
            user_id: The API key ID
            priority: Request priority

        Returns:
            QueueResult indicating outcome (ACQUIRED, TIMEOUT, or PREEMPTED).
        """
        if self._queue is None:
            return QueueResult.TIMEOUT

        return await self._queue.enqueue(user_id, priority)

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
        # Load user config outside of lock to avoid blocking
        user_limit = await self._get_user_limit(user_id)

        async with self._lock:
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

    async def wait_for_frequency_slot(
        self,
        user_id: str,
        api_identifier: str,
        timeout: float = 60.0,
    ) -> Optional[float]:
        """
        Wait for frequency limit to allow more requests.

        Polls until frequency limit resets or timeout is reached.

        Args:
            user_id: The API key ID
            api_identifier: The API identifier
            timeout: Maximum time to wait in seconds

        Returns:
            Seconds waited if slot acquired, None if timeout.
        """
        import time

        start_time = time.time()
        poll_interval = 0.1  # 100ms polling interval

        while True:
            status = await self.check_request_frequency(user_id, api_identifier)
            if status.allowed:
                return time.time() - start_time

            elapsed = time.time() - start_time
            if elapsed >= timeout:
                return None

            # Wait before next poll
            await asyncio.sleep(min(poll_interval, timeout - elapsed))

    async def increment_and_check_frequency(
        self,
        user_id: str,
        api_identifier: str,
    ) -> RateLimitStatus:
        """
        Check frequency limit and increment counters atomically.

        This is for SSE messages: check first, only increment if allowed.

        Args:
            user_id: The API key ID
            api_identifier: The API identifier

        Returns:
            RateLimitStatus indicating if the increment was allowed.
        """
        # Load user config outside of lock to avoid blocking
        user_limit = await self._get_user_limit(user_id)

        async with self._lock:
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

            # All checks passed, increment counters
            self._global_requests.count += 1

            user_counter = self._user_requests[user_id]
            user_counter.count += 1

            if api_limit is not None:
                api_counter = self._api_requests[api_identifier]
                api_counter.count += 1

            return RateLimitStatus(result=RateLimitResult.ALLOWED)

    def get_stats(self) -> dict:
        """Get current rate limiter statistics."""
        stats = {
            "global_concurrent": self._global_concurrent,
            "global_sse_connections": self._global_sse_connections,
            "global_requests_this_minute": self._global_requests.count,
            "queue_size": 0,
        }
        if self._queue is not None:
            queue_stats = self._queue.get_stats()
            stats["queue_size"] = queue_stats["queue_size"]
            stats["queue_by_priority"] = queue_stats["by_priority"]

        # Add per-user statistics
        user_stats = []
        for user_id, concurrent in self._user_concurrent.items():
            sse = self._user_sse_connections.get(user_id, 0)
            user_counter = self._user_requests.get(user_id)
            requests = user_counter.count if user_counter else 0
            if concurrent > 0 or sse > 0 or requests > 0:
                user_stats.append({
                    "user_id": user_id,
                    "concurrent": concurrent,
                    "sse_connections": sse,
                    "requests_this_minute": requests,
                })
        stats["user_stats"] = user_stats

        return stats
