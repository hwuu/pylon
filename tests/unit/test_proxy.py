"""
Tests for proxy service.
"""

import pytest
from pylon.services.proxy import ProxyService, get_api_identifier
from pylon.config import DownstreamConfig


class TestGetApiIdentifier:
    """Tests for get_api_identifier function."""

    def test_simple_path(self):
        """Test simple path."""
        assert get_api_identifier("GET", "/v1/models") == "GET /v1/models"
        assert get_api_identifier("POST", "/v1/chat/completions") == "POST /v1/chat/completions"

    def test_method_case(self):
        """Test method is uppercased."""
        assert get_api_identifier("get", "/v1/models") == "GET /v1/models"
        assert get_api_identifier("post", "/v1/chat") == "POST /v1/chat"

    def test_path_with_query_string(self):
        """Test path with query string is stripped."""
        assert get_api_identifier("GET", "/v1/models?limit=10") == "GET /v1/models"

    def test_path_with_trailing_slash(self):
        """Test trailing slash is removed."""
        assert get_api_identifier("GET", "/v1/models/") == "GET /v1/models"

    def test_root_path(self):
        """Test root path."""
        assert get_api_identifier("GET", "/") == "GET /"
        assert get_api_identifier("GET", "") == "GET /"


class TestProxyServiceFilterHeaders:
    """Tests for ProxyService header filtering."""

    def test_filter_authorization(self):
        """Test that Authorization header is filtered."""
        config = DownstreamConfig(base_url="http://example.com")
        service = ProxyService(config)

        headers = {
            "Authorization": "Bearer sk-test",
            "Content-Type": "application/json",
        }
        filtered = service._filter_headers(headers)

        assert "Authorization" not in filtered
        assert "authorization" not in filtered
        assert filtered.get("Content-Type") == "application/json"

    def test_filter_hop_by_hop_headers(self):
        """Test that hop-by-hop headers are filtered."""
        config = DownstreamConfig(base_url="http://example.com")
        service = ProxyService(config)

        headers = {
            "Host": "original-host.com",
            "Connection": "keep-alive",
            "Transfer-Encoding": "chunked",
            "Content-Type": "application/json",
            "X-Custom-Header": "custom-value",
        }
        filtered = service._filter_headers(headers)

        assert "Host" not in filtered
        assert "Connection" not in filtered
        assert "Transfer-Encoding" not in filtered
        assert filtered.get("Content-Type") == "application/json"
        assert filtered.get("X-Custom-Header") == "custom-value"

    def test_filter_case_insensitive(self):
        """Test that header filtering is case insensitive."""
        config = DownstreamConfig(base_url="http://example.com")
        service = ProxyService(config)

        headers = {
            "authorization": "Bearer sk-test",
            "AUTHORIZATION": "Bearer sk-test2",
            "HOST": "example.com",
        }
        filtered = service._filter_headers(headers)

        assert len(filtered) == 0
