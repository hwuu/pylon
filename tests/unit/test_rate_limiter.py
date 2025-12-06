"""
Tests for rate limiter service.
"""

import pytest
from pylon.services.rate_limiter import RateLimiter, RateLimitResult
from pylon.config import RateLimitConfig, RateLimitRule


@pytest.fixture
def rate_limiter():
    """Create a rate limiter with test config."""
    config = RateLimitConfig(
        global_limit=RateLimitRule(
            max_concurrent=10,
            max_requests_per_minute=100,
            max_sse_connections=5,
        ),
        default_user=RateLimitRule(
            max_concurrent=2,
            max_requests_per_minute=10,
            max_sse_connections=1,
        ),
        apis={
            "POST /v1/heavy": RateLimitRule(max_requests_per_minute=5),
            "POST /v1/stream": RateLimitRule(max_sse_connections=2),
        },
    )
    return RateLimiter(config)


class TestRateLimiter:
    """Tests for RateLimiter class."""

    @pytest.mark.asyncio
    async def test_allow_request_under_limit(self, rate_limiter):
        """Test that requests under limit are allowed."""
        status = await rate_limiter.check_rate_limit("user1", "GET /v1/test")
        assert status.allowed is True
        assert status.result == RateLimitResult.ALLOWED

    @pytest.mark.asyncio
    async def test_user_concurrent_limit(self, rate_limiter):
        """Test user concurrent request limit."""
        # Acquire 2 slots (max for user)
        await rate_limiter.acquire("user1", "GET /v1/test")
        await rate_limiter.acquire("user1", "GET /v1/test")

        # Third request should be blocked
        status = await rate_limiter.check_rate_limit("user1", "GET /v1/test")
        assert status.allowed is False
        assert status.result == RateLimitResult.USER_LIMIT_EXCEEDED

        # Release one slot
        await rate_limiter.release("user1")

        # Now should be allowed
        status = await rate_limiter.check_rate_limit("user1", "GET /v1/test")
        assert status.allowed is True

    @pytest.mark.asyncio
    async def test_global_concurrent_limit(self, rate_limiter):
        """Test global concurrent request limit."""
        # Acquire 10 slots (max global) from different users
        for i in range(10):
            await rate_limiter.acquire(f"user{i}", "GET /v1/test")

        # Next request should be blocked (global limit)
        status = await rate_limiter.check_rate_limit("user99", "GET /v1/test")
        assert status.allowed is False
        assert status.result == RateLimitResult.GLOBAL_LIMIT_EXCEEDED

    @pytest.mark.asyncio
    async def test_user_request_frequency_limit(self, rate_limiter):
        """Test user request frequency limit."""
        # Make 10 requests (max for user per minute)
        for _ in range(10):
            status = await rate_limiter.check_rate_limit("user1", "GET /v1/test")
            assert status.allowed is True
            await rate_limiter.acquire("user1", "GET /v1/test")
            await rate_limiter.release("user1")

        # 11th request should be blocked
        status = await rate_limiter.check_rate_limit("user1", "GET /v1/test")
        assert status.allowed is False
        assert status.result == RateLimitResult.USER_LIMIT_EXCEEDED

    @pytest.mark.asyncio
    async def test_api_limit(self, rate_limiter):
        """Test API-specific rate limit."""
        # Make 5 requests to heavy API (max for this API)
        for _ in range(5):
            status = await rate_limiter.check_rate_limit("user1", "POST /v1/heavy")
            assert status.allowed is True
            await rate_limiter.acquire("user1", "POST /v1/heavy")
            await rate_limiter.release("user1")

        # 6th request should be blocked
        status = await rate_limiter.check_rate_limit("user2", "POST /v1/heavy")
        assert status.allowed is False
        assert status.result == RateLimitResult.API_LIMIT_EXCEEDED

    @pytest.mark.asyncio
    async def test_sse_connection_limit(self, rate_limiter):
        """Test SSE connection limit."""
        # User can have 1 SSE connection
        status = await rate_limiter.check_rate_limit("user1", "GET /v1/stream", is_sse=True)
        assert status.allowed is True
        await rate_limiter.acquire("user1", "GET /v1/stream", is_sse=True)

        # Second SSE connection should be blocked
        status = await rate_limiter.check_rate_limit("user1", "GET /v1/stream", is_sse=True)
        assert status.allowed is False
        assert status.result == RateLimitResult.USER_LIMIT_EXCEEDED

        # Release SSE connection
        await rate_limiter.release("user1", is_sse=True)

        # Now should be allowed
        status = await rate_limiter.check_rate_limit("user1", "GET /v1/stream", is_sse=True)
        assert status.allowed is True

    @pytest.mark.asyncio
    async def test_global_sse_connection_limit(self, rate_limiter):
        """Test global SSE connection limit."""
        # Acquire 5 SSE connections (max global) from different users
        for i in range(5):
            await rate_limiter.acquire(f"user{i}", "GET /v1/stream", is_sse=True)

        # Next SSE connection should be blocked
        status = await rate_limiter.check_rate_limit("user99", "GET /v1/stream", is_sse=True)
        assert status.allowed is False
        assert status.result == RateLimitResult.GLOBAL_LIMIT_EXCEEDED

    @pytest.mark.asyncio
    async def test_api_sse_connection_limit(self, rate_limiter):
        """Test API-specific SSE connection limit."""
        # POST /v1/stream has max_sse_connections=2
        # Acquire 2 SSE connections from different users
        await rate_limiter.acquire("user1", "POST /v1/stream", is_sse=True)
        await rate_limiter.acquire("user2", "POST /v1/stream", is_sse=True)

        # Third SSE connection should be blocked (API limit)
        status = await rate_limiter.check_rate_limit("user3", "POST /v1/stream", is_sse=True)
        assert status.allowed is False
        assert status.result == RateLimitResult.API_LIMIT_EXCEEDED
        assert "API SSE connection limit" in status.message

        # Release one connection
        await rate_limiter.release("user1", "POST /v1/stream", is_sse=True)

        # Now should be allowed
        status = await rate_limiter.check_rate_limit("user3", "POST /v1/stream", is_sse=True)
        assert status.allowed is True

    @pytest.mark.asyncio
    async def test_increment_request_count(self, rate_limiter):
        """Test incrementing request count for SSE messages."""
        # Acquire an SSE connection
        await rate_limiter.acquire("user1", "GET /v1/stream", is_sse=True)

        # Increment count for SSE messages (9 more to reach limit of 10)
        await rate_limiter.increment_request_count("user1", "GET /v1/stream", count=9)

        # Should still be at limit
        status = await rate_limiter.check_request_frequency("user1", "GET /v1/stream")
        assert status.allowed is False

    @pytest.mark.asyncio
    async def test_different_users_independent(self, rate_limiter):
        """Test that different users have independent limits."""
        # User1 reaches their limit
        await rate_limiter.acquire("user1", "GET /v1/test")
        await rate_limiter.acquire("user1", "GET /v1/test")

        status = await rate_limiter.check_rate_limit("user1", "GET /v1/test")
        assert status.allowed is False

        # User2 should still be allowed
        status = await rate_limiter.check_rate_limit("user2", "GET /v1/test")
        assert status.allowed is True

    @pytest.mark.asyncio
    async def test_get_stats(self, rate_limiter):
        """Test getting rate limiter statistics."""
        await rate_limiter.acquire("user1", "GET /v1/test")
        await rate_limiter.acquire("user2", "GET /v1/stream", is_sse=True)

        stats = rate_limiter.get_stats()
        assert stats["global_concurrent"] == 1
        assert stats["global_sse_connections"] == 1
        assert stats["global_requests_this_minute"] == 2
