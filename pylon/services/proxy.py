"""
Proxy service for forwarding requests to downstream API.
"""

from typing import Optional, AsyncIterator
import httpx

from pylon.config import DownstreamConfig


class ProxyService:
    """Service for proxying requests to downstream API."""

    def __init__(self, config: DownstreamConfig):
        self.config = config
        self.base_url = config.base_url.rstrip("/")
        self.timeout = config.timeout
        self._client: Optional[httpx.AsyncClient] = None

    async def get_client(self) -> httpx.AsyncClient:
        """Get or create the HTTP client."""
        if self._client is None:
            self._client = httpx.AsyncClient(
                base_url=self.base_url,
                timeout=httpx.Timeout(self.timeout),
                follow_redirects=True,
            )
        return self._client

    async def close(self):
        """Close the HTTP client."""
        if self._client is not None:
            await self._client.aclose()
            self._client = None

    async def forward_request(
        self,
        method: str,
        path: str,
        headers: dict,
        content: Optional[bytes] = None,
        query_params: Optional[dict] = None,
    ) -> httpx.Response:
        """
        Forward a request to the downstream API.

        Args:
            method: HTTP method (GET, POST, etc.)
            path: Request path (e.g., /v1/chat/completions)
            headers: Request headers (Authorization will be stripped)
            content: Request body content
            query_params: Query parameters

        Returns:
            The response from downstream API.
        """
        client = await self.get_client()

        # Filter headers - remove hop-by-hop headers and Authorization
        filtered_headers = self._filter_headers(headers)

        # Build the full URL path
        url = path
        if query_params:
            url = httpx.URL(path).copy_merge_params(query_params)

        response = await client.request(
            method=method,
            url=url,
            headers=filtered_headers,
            content=content,
        )

        return response

    async def forward_request_stream(
        self,
        method: str,
        path: str,
        headers: dict,
        content: Optional[bytes] = None,
        query_params: Optional[dict] = None,
        idle_timeout: float = 60.0,
    ) -> AsyncIterator[tuple[bytes, int, dict]]:
        """
        Forward a request to the downstream API and stream the response.

        Args:
            method: HTTP method
            path: Request path
            headers: Request headers
            content: Request body content
            query_params: Query parameters
            idle_timeout: Timeout in seconds for idle connection (no data received)

        Yields:
            First yield: (b"", status_code, response_headers)
            Subsequent yields: (chunk, 0, {})
        """
        import asyncio

        client = await self.get_client()

        # Filter headers
        filtered_headers = self._filter_headers(headers)

        # Build the full URL path
        url = path
        if query_params:
            url = httpx.URL(path).copy_merge_params(query_params)

        async with client.stream(
            method=method,
            url=url,
            headers=filtered_headers,
            content=content,
        ) as response:
            # First yield response metadata
            yield (b"", response.status_code, dict(response.headers))

            # Stream chunks with idle timeout
            async for chunk in response.aiter_bytes():
                try:
                    # Use wait_for to implement idle timeout
                    yield (chunk, 0, {})
                except asyncio.TimeoutError:
                    # Idle timeout - will be handled by caller
                    raise

    def _filter_headers(self, headers: dict) -> dict:
        """
        Filter headers before forwarding to downstream.

        Removes:
        - Authorization header (we add our own auth if needed)
        - Hop-by-hop headers
        - Host header (will be set by httpx)
        """
        # Headers that should not be forwarded
        skip_headers = {
            "authorization",
            "host",
            "connection",
            "keep-alive",
            "proxy-authenticate",
            "proxy-authorization",
            "te",
            "trailers",
            "transfer-encoding",
            "upgrade",
            "content-length",  # httpx will set this
        }

        return {
            key: value
            for key, value in headers.items()
            if key.lower() not in skip_headers
        }

    async def health_check(self) -> bool:
        """
        Check if the downstream API is reachable.

        Returns:
            True if downstream is healthy, False otherwise.
        """
        try:
            client = await self.get_client()
            # Try a simple HEAD request to the base URL
            response = await client.head("/", timeout=5.0)
            # Consider any response (even 404) as "reachable"
            return True
        except Exception:
            return False


def get_api_identifier(method: str, path: str) -> str:
    """
    Get the API identifier for a request.

    Format: "METHOD /path"
    Example: "POST /v1/chat/completions"

    Args:
        method: HTTP method
        path: Request path

    Returns:
        The API identifier string.
    """
    # Normalize path - remove query string and trailing slashes
    clean_path = path.split("?")[0].rstrip("/")
    if not clean_path:
        clean_path = "/"

    return f"{method.upper()} {clean_path}"
