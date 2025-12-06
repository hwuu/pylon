"""
Tests for rate limiter with queue integration.
"""

import pytest
import asyncio

from pylon.services.rate_limiter import RateLimiter, RateLimitResult, RateLimitStatus
from pylon.services.queue import QueueResult
from pylon.config import RateLimitConfig, RateLimitRule, QueueConfig
from pylon.models.api_key import Priority


@pytest.fixture
def rate_limit_config():
    """Create rate limit config with low limits for testing."""
    return RateLimitConfig(
        global_limit=RateLimitRule(
            max_concurrent=2,  # Only 2 concurrent requests
            max_requests_per_minute=100,
            max_sse_connections=5,
        ),
        default_user=RateLimitRule(
            max_concurrent=10,
            max_requests_per_minute=50,
            max_sse_connections=2,
        ),
        apis={},
    )


@pytest.fixture
def queue_config():
    """Create queue config."""
    return QueueConfig(
        max_size=5,
        timeout=1,  # 1 second timeout for fast tests
    )


@pytest.fixture
def rate_limiter_with_queue(rate_limit_config, queue_config):
    """Create rate limiter with queue enabled."""
    return RateLimiter(rate_limit_config, queue_config)


@pytest.fixture
def rate_limiter_no_queue(rate_limit_config):
    """Create rate limiter without queue."""
    return RateLimiter(rate_limit_config)


class TestRateLimiterQueueIntegration:
    """Tests for rate limiter with queue."""

    @pytest.mark.asyncio
    async def test_queue_required_when_concurrency_full(self, rate_limiter_with_queue):
        """Test that QUEUE_REQUIRED is returned when global concurrency is full."""
        limiter = rate_limiter_with_queue

        # Fill up global concurrency (max 2)
        await limiter.acquire("user1", "POST /api/test")
        await limiter.acquire("user2", "POST /api/test")

        # Next request should require queue
        status = await limiter.check_rate_limit("user3", "POST /api/test")
        assert status.result == RateLimitResult.QUEUE_REQUIRED
        assert status.should_queue is True

    @pytest.mark.asyncio
    async def test_global_limit_exceeded_when_no_queue(self, rate_limiter_no_queue):
        """Test that GLOBAL_LIMIT_EXCEEDED is returned when no queue configured."""
        limiter = rate_limiter_no_queue

        # Fill up global concurrency
        await limiter.acquire("user1", "POST /api/test")
        await limiter.acquire("user2", "POST /api/test")

        # Next request should be rejected (no queue)
        status = await limiter.check_rate_limit("user3", "POST /api/test")
        assert status.result == RateLimitResult.GLOBAL_LIMIT_EXCEEDED
        assert status.allowed is False
        assert status.should_queue is False

    @pytest.mark.asyncio
    async def test_wait_in_queue_acquires_slot(self, rate_limiter_with_queue):
        """Test that waiting in queue eventually acquires a slot."""
        limiter = rate_limiter_with_queue

        # Fill up concurrency
        await limiter.acquire("user1", "POST /api/test")
        await limiter.acquire("user2", "POST /api/test")

        # Start waiting in queue
        async def wait_and_get_result():
            return await limiter.wait_in_queue("user3", Priority.NORMAL)

        wait_task = asyncio.create_task(wait_and_get_result())

        # Give queue time to start
        await asyncio.sleep(0.05)

        # Release a slot
        await limiter.release("user1")

        # Wait should complete with ACQUIRED
        result = await asyncio.wait_for(wait_task, timeout=2)
        assert result == QueueResult.ACQUIRED

    @pytest.mark.asyncio
    async def test_wait_in_queue_timeout(self, rate_limiter_with_queue):
        """Test that queue wait times out if no slot available."""
        limiter = rate_limiter_with_queue

        # Fill up concurrency
        await limiter.acquire("user1", "POST /api/test")
        await limiter.acquire("user2", "POST /api/test")

        # Wait in queue - should timeout
        result = await limiter.wait_in_queue("user3", Priority.NORMAL)
        assert result == QueueResult.TIMEOUT

    @pytest.mark.asyncio
    async def test_high_priority_preempts_low(self, rate_limit_config):
        """Test that high priority request can preempt low priority."""
        queue_config = QueueConfig(max_size=1, timeout=0.5)
        limiter = RateLimiter(rate_limit_config, queue_config)

        # Fill concurrency
        await limiter.acquire("user1", "POST /api/test")
        await limiter.acquire("user2", "POST /api/test")

        # Low priority enters queue
        low_task = asyncio.create_task(
            limiter.wait_in_queue("low_user", Priority.LOW)
        )
        await asyncio.sleep(0.05)

        # High priority enters - should preempt low
        high_task = asyncio.create_task(
            limiter.wait_in_queue("high_user", Priority.HIGH)
        )
        await asyncio.sleep(0.05)

        # Low priority should be preempted
        low_result = await low_task
        assert low_result == QueueResult.PREEMPTED

        # High priority should timeout (no slots released)
        high_result = await high_task
        assert high_result == QueueResult.TIMEOUT

    @pytest.mark.asyncio
    async def test_queue_stats_in_get_stats(self, rate_limiter_with_queue):
        """Test that queue stats are included in get_stats."""
        limiter = rate_limiter_with_queue

        # Initially empty queue
        stats = limiter.get_stats()
        assert stats["queue_size"] == 0
        assert "queue_by_priority" in stats

        # Fill concurrency and add to queue
        await limiter.acquire("user1", "POST /api/test")
        await limiter.acquire("user2", "POST /api/test")

        # Start queueing requests
        tasks = [
            asyncio.create_task(limiter.wait_in_queue("q1", Priority.HIGH)),
            asyncio.create_task(limiter.wait_in_queue("q2", Priority.NORMAL)),
        ]
        await asyncio.sleep(0.05)

        # Check stats
        stats = limiter.get_stats()
        assert stats["queue_size"] == 2
        assert stats["queue_by_priority"]["high"] == 1
        assert stats["queue_by_priority"]["normal"] == 1

        # Cancel tasks
        for task in tasks:
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass

    @pytest.mark.asyncio
    async def test_frequency_limit_checked_before_queue(self, rate_limit_config, queue_config):
        """Test that frequency limits are checked before queueing."""
        # Low frequency limit
        rate_limit_config.default_user.max_requests_per_minute = 2
        limiter = RateLimiter(rate_limit_config, queue_config)

        # Use up frequency limit
        await limiter.acquire("user1", "POST /api/test")
        await limiter.acquire("user1", "POST /api/test")

        # Next request should be rejected (not queued)
        status = await limiter.check_rate_limit("user1", "POST /api/test")
        assert status.result == RateLimitResult.USER_LIMIT_EXCEEDED
        assert status.allowed is False
        assert status.should_queue is False

    @pytest.mark.asyncio
    async def test_skip_global_concurrent_when_from_queue(self, rate_limiter_with_queue):
        """Test that acquire with skip_global_concurrent works correctly."""
        limiter = rate_limiter_with_queue

        # Acquire normally
        await limiter.acquire("user1", "POST /api/test")
        stats = limiter.get_stats()
        assert stats["global_concurrent"] == 1

        # Acquire with skip (simulating queue-acquired slot)
        await limiter.acquire("user2", "POST /api/test", skip_global_concurrent=True)
        stats = limiter.get_stats()
        # Global should still be 1, not 2
        assert stats["global_concurrent"] == 1

    @pytest.mark.asyncio
    async def test_release_notifies_queue(self, rate_limiter_with_queue):
        """Test that releasing a slot notifies the queue."""
        limiter = rate_limiter_with_queue

        # Fill concurrency
        await limiter.acquire("user1", "POST /api/test")
        await limiter.acquire("user2", "POST /api/test")

        # Queue a request
        wait_task = asyncio.create_task(
            limiter.wait_in_queue("user3", Priority.NORMAL)
        )
        await asyncio.sleep(0.05)

        # Release should trigger queue processing
        await limiter.release("user1")

        # Wait should complete quickly
        result = await asyncio.wait_for(wait_task, timeout=1)
        assert result == QueueResult.ACQUIRED


class TestCheckOrderPerDesign:
    """Tests to verify check order matches design doc 4.2."""

    @pytest.mark.asyncio
    async def test_user_limit_checked_first(self, rate_limit_config, queue_config):
        """Test user limit is checked before API and global limits."""
        rate_limit_config.default_user.max_requests_per_minute = 1
        rate_limit_config.apis["POST /api/test"] = RateLimitRule(max_requests_per_minute=10)
        limiter = RateLimiter(rate_limit_config, queue_config)

        # Use up user limit
        await limiter.acquire("user1", "POST /api/test")

        # Should hit user limit, not API or global
        status = await limiter.check_rate_limit("user1", "POST /api/test")
        assert status.result == RateLimitResult.USER_LIMIT_EXCEEDED

    @pytest.mark.asyncio
    async def test_api_limit_checked_after_user(self, rate_limit_config, queue_config):
        """Test API limit is checked after user limit."""
        rate_limit_config.apis["POST /api/test"] = RateLimitRule(max_requests_per_minute=1)
        limiter = RateLimiter(rate_limit_config, queue_config)

        # Use up API limit (different users to avoid user limit)
        await limiter.acquire("user1", "POST /api/test")

        # Different user should hit API limit
        status = await limiter.check_rate_limit("user2", "POST /api/test")
        assert status.result == RateLimitResult.API_LIMIT_EXCEEDED

    @pytest.mark.asyncio
    async def test_global_checked_last(self, rate_limit_config, queue_config):
        """Test global concurrency is checked last (triggers queue)."""
        limiter = RateLimiter(rate_limit_config, queue_config)

        # Fill global concurrency with different users
        await limiter.acquire("user1", "POST /api/test")
        await limiter.acquire("user2", "POST /api/test")

        # Third user should trigger queue (not user/API limit)
        status = await limiter.check_rate_limit("user3", "POST /api/other")
        assert status.result == RateLimitResult.QUEUE_REQUIRED
