"""
Tests for rate limiter service.
"""

import pytest
from pylon.services.rate_limiter import RateLimiter, RateLimitResult
from pylon.config import RateLimitConfig, RateLimitRule, ApiPattern


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


class TestUserConfigLoader:
    """Tests for user-specific rate limit config from database."""

    @pytest.fixture
    def rate_limiter_with_loader(self):
        """Create a rate limiter with user config loader."""
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
        )
        return RateLimiter(config)

    @pytest.mark.asyncio
    async def test_user_config_from_loader(self, rate_limiter_with_loader):
        """Test that user config is loaded from callback."""
        import json

        # Set up a mock loader that returns custom config for user1
        async def mock_loader(user_id: str):
            if user_id == "user1":
                return json.dumps({
                    "max_concurrent": 5,
                    "max_requests_per_minute": 50,
                })
            return None

        rate_limiter_with_loader.set_user_config_loader(mock_loader)

        # User1 should be able to make 5 concurrent requests (custom config)
        for i in range(5):
            await rate_limiter_with_loader.acquire("user1", "GET /test")

        # 6th request should fail
        status = await rate_limiter_with_loader.check_rate_limit("user1", "GET /test")
        assert status.allowed is False
        assert status.result == RateLimitResult.USER_LIMIT_EXCEEDED

    @pytest.mark.asyncio
    async def test_default_config_when_no_loader(self, rate_limiter_with_loader):
        """Test default config is used when no loader is set."""
        # No loader set, should use default (max_concurrent=2)
        await rate_limiter_with_loader.acquire("user1", "GET /test")
        await rate_limiter_with_loader.acquire("user1", "GET /test")

        # 3rd request should fail (default limit)
        status = await rate_limiter_with_loader.check_rate_limit("user1", "GET /test")
        assert status.allowed is False

    @pytest.mark.asyncio
    async def test_default_config_when_loader_returns_none(self, rate_limiter_with_loader):
        """Test default config is used when loader returns None."""
        async def mock_loader(user_id: str):
            return None

        rate_limiter_with_loader.set_user_config_loader(mock_loader)

        # Should use default (max_concurrent=2)
        await rate_limiter_with_loader.acquire("user1", "GET /test")
        await rate_limiter_with_loader.acquire("user1", "GET /test")

        status = await rate_limiter_with_loader.check_rate_limit("user1", "GET /test")
        assert status.allowed is False

    @pytest.mark.asyncio
    async def test_user_config_merged_with_default(self, rate_limiter_with_loader):
        """Test that partial user config is merged with default."""
        import json

        # User config only specifies max_concurrent, should use default for others
        async def mock_loader(user_id: str):
            if user_id == "user1":
                return json.dumps({"max_concurrent": 5})
            return None

        rate_limiter_with_loader.set_user_config_loader(mock_loader)

        # User1 should have max_concurrent=5 from custom config
        # but max_requests_per_minute=10 from default
        for i in range(10):
            status = await rate_limiter_with_loader.check_rate_limit("user1", "GET /test")
            if status.allowed:
                await rate_limiter_with_loader.acquire("user1", "GET /test")

        # Should be limited by frequency (10 per minute from default)
        status = await rate_limiter_with_loader.check_rate_limit("user1", "GET /test")
        assert status.allowed is False
        assert status.result == RateLimitResult.USER_LIMIT_EXCEEDED

    @pytest.mark.asyncio
    async def test_user_config_cached(self, rate_limiter_with_loader):
        """Test that user config is cached after first load."""
        import json
        load_count = 0

        async def mock_loader(user_id: str):
            nonlocal load_count
            load_count += 1
            return json.dumps({"max_concurrent": 5})

        rate_limiter_with_loader.set_user_config_loader(mock_loader)

        # Multiple requests for same user
        await rate_limiter_with_loader.check_rate_limit("user1", "GET /test")
        await rate_limiter_with_loader.check_rate_limit("user1", "GET /test")
        await rate_limiter_with_loader.check_rate_limit("user1", "GET /test")

        # Should only load once due to caching
        assert load_count == 1

    @pytest.mark.asyncio
    async def test_invalidate_user_config_cache(self, rate_limiter_with_loader):
        """Test invalidating user config cache."""
        import json
        load_count = 0
        current_limit = 5

        async def mock_loader(user_id: str):
            nonlocal load_count
            load_count += 1
            return json.dumps({"max_concurrent": current_limit})

        rate_limiter_with_loader.set_user_config_loader(mock_loader)

        # First request loads config
        await rate_limiter_with_loader.check_rate_limit("user1", "GET /test")
        assert load_count == 1

        # Invalidate cache
        rate_limiter_with_loader.invalidate_user_config_cache("user1")

        # Update the limit
        current_limit = 10

        # Next request should reload config
        await rate_limiter_with_loader.check_rate_limit("user1", "GET /test")
        assert load_count == 2

    @pytest.mark.asyncio
    async def test_invalid_json_falls_back_to_default(self, rate_limiter_with_loader):
        """Test that invalid JSON config falls back to default."""
        async def mock_loader(user_id: str):
            return "invalid json {"

        rate_limiter_with_loader.set_user_config_loader(mock_loader)

        # Should use default (max_concurrent=2)
        await rate_limiter_with_loader.acquire("user1", "GET /test")
        await rate_limiter_with_loader.acquire("user1", "GET /test")

        status = await rate_limiter_with_loader.check_rate_limit("user1", "GET /test")
        assert status.allowed is False


class TestApiPatternMatching:
    """Tests for API pattern matching."""

    @pytest.fixture
    def rate_limiter_with_patterns(self):
        """Create a rate limiter with API patterns."""
        config = RateLimitConfig(
            global_limit=RateLimitRule(
                max_concurrent=100,
                max_requests_per_minute=1000,
                max_sse_connections=50,
            ),
            default_user=RateLimitRule(
                max_concurrent=10,
                max_requests_per_minute=100,
                max_sse_connections=5,
            ),
            apis={
                "GET /exact/match": RateLimitRule(max_requests_per_minute=5),
            },
            api_patterns=[
                ApiPattern(
                    pattern="GET /users/{id}",
                    rule=RateLimitRule(max_requests_per_minute=10),
                ),
                ApiPattern(
                    pattern="POST /v1/*",
                    rule=RateLimitRule(max_requests_per_minute=20),
                ),
                ApiPattern(
                    pattern="DELETE /items/{category}/{id}",
                    rule=RateLimitRule(max_requests_per_minute=3),
                ),
            ],
        )
        return RateLimiter(config)

    def test_pattern_matching_exact(self, rate_limiter_with_patterns):
        """Test exact pattern matching."""
        # Exact match should take priority
        rule = rate_limiter_with_patterns._get_api_limit("GET /exact/match")
        assert rule is not None
        assert rule.max_requests_per_minute == 5

    def test_pattern_matching_param(self, rate_limiter_with_patterns):
        """Test {param} pattern matching."""
        # Should match GET /users/{id}
        rule = rate_limiter_with_patterns._get_api_limit("GET /users/123")
        assert rule is not None
        assert rule.max_requests_per_minute == 10

        rule = rate_limiter_with_patterns._get_api_limit("GET /users/abc")
        assert rule is not None
        assert rule.max_requests_per_minute == 10

    def test_pattern_matching_wildcard(self, rate_limiter_with_patterns):
        """Test * wildcard pattern matching."""
        # Should match POST /v1/*
        rule = rate_limiter_with_patterns._get_api_limit("POST /v1/chat/completions")
        assert rule is not None
        assert rule.max_requests_per_minute == 20

        rule = rate_limiter_with_patterns._get_api_limit("POST /v1/images/generate")
        assert rule is not None
        assert rule.max_requests_per_minute == 20

    def test_pattern_matching_multiple_params(self, rate_limiter_with_patterns):
        """Test pattern with multiple {param} segments."""
        # Should match DELETE /items/{category}/{id}
        rule = rate_limiter_with_patterns._get_api_limit("DELETE /items/books/42")
        assert rule is not None
        assert rule.max_requests_per_minute == 3

    def test_pattern_no_match(self, rate_limiter_with_patterns):
        """Test that non-matching patterns return None."""
        # No pattern matches
        rule = rate_limiter_with_patterns._get_api_limit("GET /unknown/path")
        assert rule is None

        # Wrong method
        rule = rate_limiter_with_patterns._get_api_limit("POST /users/123")
        assert rule is None

    def test_pattern_exact_takes_priority(self, rate_limiter_with_patterns):
        """Test that exact match takes priority over patterns."""
        # Add a pattern that would also match
        rate_limiter_with_patterns.config.api_patterns.append(
            ApiPattern(
                pattern="GET /exact/*",
                rule=RateLimitRule(max_requests_per_minute=999),
            )
        )

        # Exact match should still take priority
        rule = rate_limiter_with_patterns._get_api_limit("GET /exact/match")
        assert rule is not None
        assert rule.max_requests_per_minute == 5  # From exact match, not pattern

    @pytest.mark.asyncio
    async def test_pattern_rate_limit_applied(self, rate_limiter_with_patterns):
        """Test that pattern-based rate limits are actually applied."""
        # Pattern GET /users/{id} has max_requests_per_minute=10
        # Make 10 requests (need to release after each to avoid concurrent limit)
        for i in range(10):
            status = await rate_limiter_with_patterns.check_rate_limit("user1", "GET /users/123")
            if status.allowed:
                await rate_limiter_with_patterns.acquire("user1", "GET /users/123")
                await rate_limiter_with_patterns.release("user1", "GET /users/123")

        # 11th request should be limited by API frequency
        status = await rate_limiter_with_patterns.check_rate_limit("user1", "GET /users/123")
        assert status.allowed is False
        assert status.result == RateLimitResult.API_LIMIT_EXCEEDED

    def test_match_api_pattern_method_case_insensitive(self, rate_limiter_with_patterns):
        """Test that method matching is case insensitive."""
        assert rate_limiter_with_patterns._match_api_pattern("GET /test", "get /test") is True
        assert rate_limiter_with_patterns._match_api_pattern("get /test", "GET /test") is True

    def test_match_api_pattern_invalid_format(self, rate_limiter_with_patterns):
        """Test handling of invalid pattern/identifier format."""
        # Missing method
        assert rate_limiter_with_patterns._match_api_pattern("/test", "GET /test") is False
        assert rate_limiter_with_patterns._match_api_pattern("GET /test", "/test") is False
