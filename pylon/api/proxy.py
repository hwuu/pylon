"""
Proxy API routes.
"""

import asyncio
import json
import logging
import time
from datetime import datetime, timezone
from typing import Optional

from fastapi import APIRouter, Request, Response, HTTPException
from fastapi.responses import StreamingResponse
from sqlalchemy.ext.asyncio import AsyncSession

from pylon.models.api_key import ApiKey
from pylon.models.request_log import RequestLog
from pylon.services.auth import AuthService, extract_api_key_from_header
from pylon.services.proxy import ProxyService, get_api_identifier
from pylon.services.rate_limiter import RateLimiter, RateLimitResult
from pylon.services.queue import QueueResult


logger = logging.getLogger(__name__)


router = APIRouter()


# These will be set by the application on startup
_proxy_service: Optional[ProxyService] = None
_rate_limiter: Optional[RateLimiter] = None
_session_factory = None
_sse_idle_timeout: int = 60


def set_dependencies(
    proxy_service: ProxyService,
    rate_limiter: RateLimiter,
    session_factory,
    sse_idle_timeout: int = 60,
):
    """Set the dependencies for the proxy routes."""
    global _proxy_service, _rate_limiter, _session_factory, _sse_idle_timeout
    _proxy_service = proxy_service
    _rate_limiter = rate_limiter
    _session_factory = session_factory
    _sse_idle_timeout = sse_idle_timeout


async def get_db_session():
    """Get a database session."""
    async with _session_factory() as session:
        yield session


async def _save_request_log(
    api_key_id: str,
    api_identifier: str,
    request_path: str,
    request_method: str,
    response_status: int,
    response_time_ms: int,
    client_ip: str,
    is_sse: bool = False,
    sse_message_count: int = 0,
) -> None:
    """Save request log to database."""
    try:
        async with _session_factory() as session:
            log = RequestLog(
                api_key_id=api_key_id,
                api_identifier=api_identifier,
                request_path=request_path,
                request_method=request_method,
                response_status=response_status,
                request_time=datetime.now(timezone.utc),
                response_time_ms=response_time_ms,
                client_ip=client_ip,
                is_sse=is_sse,
                sse_message_count=sse_message_count,
            )
            session.add(log)
            await session.commit()
    except Exception as e:
        logger.error(f"Failed to save request log: {e}")


@router.get("/health")
async def health_check():
    """
    Health check endpoint.

    Returns the health status of Pylon and downstream API.
    """
    downstream_ok = False
    if _proxy_service:
        downstream_ok = await _proxy_service.health_check()

    stats = {}
    if _rate_limiter:
        stats = _rate_limiter.get_stats()

    return {
        "status": "ok",
        "downstream": "ok" if downstream_ok else "error",
        "queue_size": stats.get("queue_size", 0),
        "active_connections": stats.get("global_concurrent", 0),
    }


async def authenticate_request(request: Request, session: AsyncSession) -> ApiKey:
    """Authenticate request and return API key object."""
    authorization = request.headers.get("Authorization")
    api_key_str = extract_api_key_from_header(authorization)

    if not api_key_str:
        raise HTTPException(
            status_code=401,
            detail={"error": "unauthorized", "message": "Missing or invalid API key"},
        )

    auth_service = AuthService(session)
    api_key = await auth_service.validate_api_key(api_key_str)

    if not api_key:
        raise HTTPException(
            status_code=401,
            detail={"error": "unauthorized", "message": "Invalid or expired API key"},
        )

    return api_key


async def check_rate_limits(
    api_key: ApiKey,
    api_identifier: str,
    is_sse: bool = False,
) -> bool:
    """
    Check rate limits and raise exception if exceeded.

    Returns:
        True if should wait in queue, False if can proceed immediately.
    """
    if not _rate_limiter:
        return False

    status = await _rate_limiter.check_rate_limit(
        user_id=api_key.id,
        api_identifier=api_identifier,
        is_sse=is_sse,
    )

    if status.allowed:
        return False

    if status.should_queue:
        return True

    # Rate limit exceeded - raise error
    error_messages = {
        RateLimitResult.USER_LIMIT_EXCEEDED: "Your request limit exceeded",
        RateLimitResult.API_LIMIT_EXCEEDED: "API rate limit exceeded",
        RateLimitResult.GLOBAL_LIMIT_EXCEEDED: "System busy, please try again later",
    }
    raise HTTPException(
        status_code=429,
        detail={
            "error": "rate_limit_exceeded",
            "message": error_messages.get(status.result, status.message),
        },
    )


async def wait_in_queue(api_key: ApiKey) -> None:
    """
    Wait in the priority queue for a slot.

    Raises HTTPException if timeout or preempted.
    """
    if not _rate_limiter:
        raise HTTPException(
            status_code=503,
            detail={"error": "service_unavailable", "message": "Queue not configured"},
        )

    result = await _rate_limiter.wait_in_queue(api_key.id, api_key.priority)

    if result == QueueResult.ACQUIRED:
        return

    if result == QueueResult.TIMEOUT:
        raise HTTPException(
            status_code=504,
            detail={"error": "gateway_timeout", "message": "Queue wait timeout"},
        )

    if result == QueueResult.PREEMPTED:
        raise HTTPException(
            status_code=503,
            detail={"error": "preempted", "message": "Request preempted by higher priority"},
        )


def _is_sse_request(request: Request, body: bytes) -> bool:
    """Check if this is an SSE (streaming) request."""
    # Check Accept header
    accept = request.headers.get("accept", "")
    if "text/event-stream" in accept:
        return True

    # Check request body for stream: true (common in OpenAI-style APIs)
    if body:
        try:
            data = json.loads(body)
            if isinstance(data, dict) and data.get("stream") is True:
                return True
        except (json.JSONDecodeError, UnicodeDecodeError):
            pass

    return False


def _create_pylon_error_event(code: str, message: str) -> str:
    """Create a pylon_error SSE event."""
    error_data = json.dumps({"code": code, "message": message})
    return f"event: pylon_error\ndata: {error_data}\n\n"


@router.api_route("/{path:path}", methods=["GET", "POST", "PUT", "DELETE", "PATCH", "HEAD", "OPTIONS"])
async def proxy_request(
    request: Request,
    path: str,
):
    """
    Proxy all requests to the downstream API.

    This is the main proxy endpoint that handles all HTTP methods.
    Supports both regular HTTP requests and SSE (Server-Sent Events) streams.
    Implements priority queue for waiting when concurrency is full.
    """
    start_time = time.time()
    api_key_id = None
    api_identifier = None
    body = b""

    try:
        if not _proxy_service or not _session_factory:
            raise HTTPException(
                status_code=503,
                detail={"error": "service_unavailable", "message": "Proxy not configured"},
            )

        # Get request body early to detect SSE
        body = await request.body()
        is_sse = _is_sse_request(request, body)

        # Get database session
        async with _session_factory() as session:
            # Authenticate
            api_key = await authenticate_request(request, session)
            api_key_id = api_key.id

            # Get API identifier
            full_path = f"/{path}"
            if request.url.query:
                full_path = f"{full_path}?{request.url.query}"
            api_identifier = get_api_identifier(request.method, full_path)

            # Check rate limits - may need to queue
            should_queue = await check_rate_limits(api_key, api_identifier, is_sse=is_sse)

            if should_queue:
                # Wait in priority queue for a slot
                await wait_in_queue(api_key)
                # Queue already acquired global concurrent slot, just update user counters
                await _rate_limiter.acquire(
                    api_key.id, api_identifier, is_sse=is_sse, skip_global_concurrent=True
                )
            else:
                # Acquire rate limit slot directly
                await _rate_limiter.acquire(api_key.id, api_identifier, is_sse=is_sse)

            # Get headers as dict
            headers = dict(request.headers)

            if is_sse:
                # Handle SSE request
                return await _handle_sse_request(
                    api_key=api_key,
                    api_identifier=api_identifier,
                    method=request.method,
                    path=f"/{path}",
                    headers=headers,
                    body=body,
                    query_params=dict(request.query_params) if request.query_params else None,
                    client_ip=request.client.host if request.client else "unknown",
                    start_time=start_time,
                )
            else:
                # Handle regular request
                try:
                    # Forward request
                    response = await _proxy_service.forward_request(
                        method=request.method,
                        path=f"/{path}",
                        headers=headers,
                        content=body if body else None,
                        query_params=dict(request.query_params) if request.query_params else None,
                    )
                    elapsed_ms = int((time.time() - start_time) * 1000)

                    # Log successful request
                    logger.info(
                        f"[{api_key_id[:8]}] {api_identifier} -> {response.status_code} "
                        f"({elapsed_ms}ms, req={len(body)}B, res={len(response.content)}B)"
                    )

                    # Save request log to database
                    await _save_request_log(
                        api_key_id=api_key.id,
                        api_identifier=api_identifier,
                        request_path=f"/{path}",
                        request_method=request.method,
                        response_status=response.status_code,
                        response_time_ms=elapsed_ms,
                        client_ip=request.client.host if request.client else "unknown",
                    )

                    # Build response headers (filter hop-by-hop)
                    response_headers = {}
                    skip_headers = {"connection", "keep-alive", "transfer-encoding", "content-encoding"}
                    for key, value in response.headers.items():
                        if key.lower() not in skip_headers:
                            response_headers[key] = value

                    return Response(
                        content=response.content,
                        status_code=response.status_code,
                        headers=response_headers,
                    )

                finally:
                    # Release rate limit slot
                    await _rate_limiter.release(api_key.id, api_identifier)

    except HTTPException as e:
        # Log error responses
        elapsed_ms = int((time.time() - start_time) * 1000)
        key_prefix = f"[{api_key_id[:8]}]" if api_key_id else "[no-key]"
        api_info = api_identifier or f"{request.method} /{path}"
        logger.warning(
            f"{key_prefix} {api_info} -> {e.status_code} "
            f"({elapsed_ms}ms, req={len(body)}B, err={e.detail})"
        )
        raise


async def _handle_sse_request(
    api_key: ApiKey,
    api_identifier: str,
    method: str,
    path: str,
    headers: dict,
    body: bytes,
    query_params: Optional[dict],
    client_ip: str,
    start_time: float,
) -> StreamingResponse:
    """Handle SSE streaming request."""

    # Track SSE metrics
    total_bytes = 0
    message_count = 0
    response_status = 200

    async def generate():
        """Generate SSE stream with idle timeout and message rate limiting."""
        nonlocal total_bytes, message_count, response_status
        last_data_time = time.time()

        try:
            stream = _proxy_service.forward_request_stream(
                method=method,
                path=path,
                headers=headers,
                content=body if body else None,
                query_params=query_params,
                idle_timeout=_sse_idle_timeout,
            )

            # First yield gets metadata
            first = True
            response_headers = {}

            async for chunk, status, hdrs in stream:
                if first:
                    first = False
                    response_status = status
                    response_headers = hdrs

                    # Log SSE connection start
                    logger.info(
                        f"[{api_key.id[:8]}] SSE {api_identifier} -> {response_status} (started, req={len(body)}B)"
                    )

                    # If downstream returned error, don't stream
                    if status >= 400:
                        # Return error as pylon_error event
                        yield _create_pylon_error_event(
                            "downstream_error",
                            f"Downstream returned status {status}"
                        )
                        return

                    continue

                # Update last data time
                last_data_time = time.time()

                # Count SSE data events (lines starting with "data:")
                if chunk:
                    total_bytes += len(chunk)
                    chunk_str = chunk.decode("utf-8", errors="replace")
                    data_count = chunk_str.count("data:")
                    message_count += data_count

                    # Rate limit each SSE message
                    for _ in range(data_count):
                        # Check and increment frequency counter
                        status = await _rate_limiter.increment_and_check_frequency(
                            api_key.id, api_identifier
                        )
                        if not status.allowed:
                            # Wait for frequency window to reset
                            wait_result = await _rate_limiter.wait_for_frequency_slot(
                                api_key.id, api_identifier, timeout=60.0
                            )
                            if wait_result is None:
                                # Timeout waiting for frequency slot
                                yield _create_pylon_error_event(
                                    "rate_limit_timeout",
                                    "Timeout waiting for rate limit window reset"
                                ).encode("utf-8")
                                return

                yield chunk

                # Check idle timeout
                if time.time() - last_data_time > _sse_idle_timeout:
                    yield _create_pylon_error_event(
                        "idle_timeout",
                        f"No data received for {_sse_idle_timeout} seconds"
                    ).encode("utf-8")
                    return

        except asyncio.TimeoutError:
            yield _create_pylon_error_event(
                "idle_timeout",
                f"No data received for {_sse_idle_timeout} seconds"
            ).encode("utf-8")

        except Exception as e:
            logger.exception("SSE stream error")
            yield _create_pylon_error_event(
                "stream_error",
                str(e)
            ).encode("utf-8")

        finally:
            # Log SSE connection end
            elapsed_ms = int((time.time() - start_time) * 1000)
            logger.info(
                f"[{api_key.id[:8]}] SSE {api_identifier} ended "
                f"({elapsed_ms}ms, {message_count} msgs, {total_bytes}B)"
            )

            # Save request log to database
            await _save_request_log(
                api_key_id=api_key.id,
                api_identifier=api_identifier,
                request_path=path,
                request_method=method,
                response_status=response_status,
                response_time_ms=elapsed_ms,
                client_ip=client_ip,
                is_sse=True,
                sse_message_count=message_count,
            )

            # Release SSE connection slot
            await _rate_limiter.release(api_key.id, api_identifier, is_sse=True)

    return StreamingResponse(
        generate(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )
