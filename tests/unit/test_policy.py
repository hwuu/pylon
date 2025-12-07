"""
Tests for policy configuration.
"""

import pytest

from pylon.config import (
    PolicyConfig,
    policy_from_dict,
    RateLimitRule,
)


class TestPolicyFromDict:
    """Tests for policy_from_dict function."""

    def test_empty_dict(self):
        """Test that empty dict returns default policy."""
        policy = policy_from_dict({})

        # Check defaults
        assert policy.downstream.base_url == ""
        assert policy.downstream.timeout == 30
        assert policy.queue.max_size == 100
        assert policy.queue.timeout == 30
        assert policy.sse.idle_timeout == 60
        assert policy.data_retention.days == 30

    def test_full_policy(self):
        """Test parsing full policy from dict."""
        policy_dict = {
            "downstream.base_url": "https://api.example.com",
            "downstream.timeout": 60,
            "rate_limit.global": {
                "max_concurrent": 100,
                "max_requests_per_minute": 1000,
                "max_sse_connections": 50,
            },
            "rate_limit.default_user": {
                "max_concurrent": 10,
                "max_requests_per_minute": 100,
                "max_sse_connections": 5,
            },
            "rate_limit.apis": {
                "POST /v1/chat": {"max_requests_per_minute": 50},
            },
            "queue.max_size": 200,
            "queue.timeout": 60,
            "sse.idle_timeout": 120,
            "data_retention.days": 60,
            "data_retention.cleanup_interval_hours": 12,
        }

        policy = policy_from_dict(policy_dict)

        # Downstream
        assert policy.downstream.base_url == "https://api.example.com"
        assert policy.downstream.timeout == 60

        # Rate limit
        assert policy.rate_limit.global_limit.max_concurrent == 100
        assert policy.rate_limit.global_limit.max_requests_per_minute == 1000
        assert policy.rate_limit.default_user.max_concurrent == 10
        assert "POST /v1/chat" in policy.rate_limit.apis
        assert policy.rate_limit.apis["POST /v1/chat"].max_requests_per_minute == 50

        # Queue
        assert policy.queue.max_size == 200
        assert policy.queue.timeout == 60

        # SSE
        assert policy.sse.idle_timeout == 120

        # Data retention
        assert policy.data_retention.days == 60
        assert policy.data_retention.cleanup_interval_hours == 12

    def test_empty_apis_policy(self):
        """Test parsing policy with empty apis section."""
        policy_dict = {
            "downstream.base_url": "http://example.com",
            "rate_limit.apis": {},
        }

        policy = policy_from_dict(policy_dict)
        assert policy.rate_limit.apis == {}

    def test_api_patterns(self):
        """Test parsing API patterns."""
        policy_dict = {
            "rate_limit.api_patterns": [
                {
                    "pattern": "GET /users/{id}",
                    "rule": {"max_requests_per_minute": 100},
                },
                {
                    "pattern": "POST /v1/*",
                    "rule": {"max_concurrent": 20},
                },
            ],
        }

        policy = policy_from_dict(policy_dict)
        assert len(policy.rate_limit.api_patterns) == 2
        assert policy.rate_limit.api_patterns[0].pattern == "GET /users/{id}"
        assert policy.rate_limit.api_patterns[0].rule.max_requests_per_minute == 100
        assert policy.rate_limit.api_patterns[1].pattern == "POST /v1/*"
        assert policy.rate_limit.api_patterns[1].rule.max_concurrent == 20
