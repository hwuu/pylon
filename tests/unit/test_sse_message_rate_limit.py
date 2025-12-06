"""
Tests for SSE message rate limiting.
"""

import pytest
import asyncio

from pylon.services.rate_limiter import RateLimiter, RateLimitResult, RateLimitStatus
from pylon.config import RateLimitConfig, RateLimitRule


@pytest.fixture
def rate_limit_config():
    """Create rate limit config with low limits for testing."""
    return RateLimitConfig(
        global_limit=RateLimitRule(
            max_concurrent=10,
            max_requests_per_minute=100,
            max_sse_connections=5,
        ),
        default_user=RateLimitRule(
            max_concurrent=5,
            max_requests_per_minute=10,  # Low limit for testing
            max_sse_connections=2,
        ),
        apis={
            "POST /api/chat": RateLimitRule(
                max_concurrent=5,
                max_requests_per_minute=20,
            )
        },
    )


@pytest.fixture
def rate_limiter(rate_limit_config):
    """Create rate limiter without queue."""
    return RateLimiter(rate_limit_config)


class TestSseMessageFrequencyLimit:
    """Tests for SSE message frequency rate limiting."""

    @pytest.mark.asyncio
    async def test_check_frequency_within_limit(self, rate_limiter):
        """Test that frequency check passes when within limit."""
        status = await rate_limiter.check_request_frequency("user1", "POST /api/test")
        assert status.allowed

    @pytest.mark.asyncio
    async def test_check_frequency_user_exceeded(self, rate_limiter):
        """Test that user frequency limit is checked."""
        # Use up user limit (10 requests per minute)
        for _ in range(10):
            await rate_limiter.increment_request_count("user1", "POST /api/test")

        # Next check should fail
        status = await rate_limiter.check_request_frequency("user1", "POST /api/test")
        assert status.result == RateLimitResult.USER_LIMIT_EXCEEDED
        assert not status.allowed

    @pytest.mark.asyncio
    async def test_check_frequency_api_exceeded(self, rate_limiter):
        """Test that API frequency limit is checked."""
        # Use up API limit (20 requests per minute) with different users
        for i in range(20):
            await rate_limiter.increment_request_count(f"user{i}", "POST /api/chat")

        # Next check should fail
        status = await rate_limiter.check_request_frequency("user_new", "POST /api/chat")
        assert status.result == RateLimitResult.API_LIMIT_EXCEEDED
        assert not status.allowed

    @pytest.mark.asyncio
    async def test_check_frequency_global_exceeded(self, rate_limit_config):
        """Test that global frequency limit is checked."""
        # Lower global limit for this test
        rate_limit_config.global_limit.max_requests_per_minute = 5
        rate_limit_config.default_user.max_requests_per_minute = 100  # High user limit
        limiter = RateLimiter(rate_limit_config)

        # Use up global limit with different users
        for i in range(5):
            await limiter.increment_request_count(f"user{i}", "POST /api/other")

        # Next check should fail
        status = await limiter.check_request_frequency("user_new", "POST /api/other")
        assert status.result == RateLimitResult.GLOBAL_LIMIT_EXCEEDED
        assert not status.allowed


class TestWaitForFrequencySlot:
    """Tests for waiting when frequency limit is exceeded."""

    @pytest.mark.asyncio
    async def test_wait_for_frequency_immediately_available(self, rate_limiter):
        """Test that wait returns immediately if within limits."""
        # Should return immediately when within limits
        wait_seconds = await rate_limiter.wait_for_frequency_slot(
            "user1", "POST /api/test", timeout=1.0
        )
        assert wait_seconds == 0

    @pytest.mark.asyncio
    async def test_wait_for_frequency_returns_wait_time(self, rate_limiter):
        """Test that wait returns the time waited."""
        # Use up user limit
        for _ in range(10):
            await rate_limiter.increment_request_count("user1", "POST /api/test")

        # Should timeout and return None (couldn't acquire in time)
        wait_seconds = await rate_limiter.wait_for_frequency_slot(
            "user1", "POST /api/test", timeout=0.1
        )
        assert wait_seconds is None  # Timeout

    @pytest.mark.asyncio
    async def test_wait_for_frequency_window_reset(self, rate_limit_config):
        """Test that wait succeeds after window resets."""
        # Create limiter with very short window for testing
        limiter = RateLimiter(rate_limit_config)

        # Use up user limit
        for _ in range(10):
            await limiter.increment_request_count("user1", "POST /api/test")

        # Manually reset the counter to simulate window reset
        async with limiter._lock:
            from datetime import datetime, timezone, timedelta
            limiter._user_requests["user1"].window_start = datetime.now(
                timezone.utc
            ) - timedelta(seconds=61)  # Force window reset

        # Now should succeed immediately
        wait_seconds = await limiter.wait_for_frequency_slot(
            "user1", "POST /api/test", timeout=1.0
        )
        assert wait_seconds == 0


class TestIncrementAndCheck:
    """Tests for combined increment and check operation."""

    @pytest.mark.asyncio
    async def test_increment_and_check_within_limit(self, rate_limiter):
        """Test increment_and_check when within limits."""
        result = await rate_limiter.increment_and_check_frequency(
            "user1", "POST /api/test"
        )
        assert result.allowed

        # Count should have increased
        async with rate_limiter._lock:
            assert rate_limiter._user_requests["user1"].count == 1

    @pytest.mark.asyncio
    async def test_increment_and_check_at_limit(self, rate_limiter):
        """Test increment_and_check fails when at limit."""
        # Use up user limit (10 requests per minute)
        for _ in range(10):
            await rate_limiter.increment_request_count("user1", "POST /api/test")

        # Next should fail (at limit, not incremented)
        result = await rate_limiter.increment_and_check_frequency(
            "user1", "POST /api/test"
        )
        assert not result.allowed
        assert result.result == RateLimitResult.USER_LIMIT_EXCEEDED

        # Count should NOT have increased (pre-check failed)
        async with rate_limiter._lock:
            assert rate_limiter._user_requests["user1"].count == 10

    @pytest.mark.asyncio
    async def test_increment_and_check_user_priority_over_api(self, rate_limiter):
        """Test that user limit is checked before API limit."""
        # Use up user limit first
        for _ in range(10):
            await rate_limiter.increment_request_count("user1", "POST /api/chat")

        # Should hit user limit, not API limit
        result = await rate_limiter.increment_and_check_frequency(
            "user1", "POST /api/chat"
        )
        assert result.result == RateLimitResult.USER_LIMIT_EXCEEDED
