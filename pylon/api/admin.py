"""
Admin API routes.
"""

from datetime import datetime, timezone
from typing import Optional, List

from fastapi import APIRouter, Request, HTTPException, Depends
from pydantic import BaseModel, Field

from pylon.config import AdminConfig
from pylon.services.admin_auth import AdminAuthService
from pylon.services.api_key_service import ApiKeyService
from pylon.models.api_key import Priority


router = APIRouter()


# These will be set by the application on startup
_admin_auth_service: Optional[AdminAuthService] = None
_session_factory = None
_rate_limiter = None


def set_dependencies(
    admin_auth_service: AdminAuthService,
    session_factory,
    rate_limiter=None,
):
    """Set the dependencies for the admin routes."""
    global _admin_auth_service, _session_factory, _rate_limiter
    _admin_auth_service = admin_auth_service
    _session_factory = session_factory
    _rate_limiter = rate_limiter


# ============== Request/Response Models ==============

class LoginRequest(BaseModel):
    """Login request body."""
    password: str


class LoginResponse(BaseModel):
    """Login response body."""
    token: str
    expires_in_hours: int


class ApiKeyCreateRequest(BaseModel):
    """Request to create an API key."""
    description: str = ""
    priority: str = "normal"
    expires_in_days: Optional[int] = None
    rate_limit_config: Optional[dict] = None


class ApiKeyCreateResponse(BaseModel):
    """Response after creating an API key."""
    id: str
    key: str  # Only returned on creation
    key_prefix: str
    description: str
    priority: str
    created_at: datetime
    expires_at: Optional[datetime]


class ApiKeyResponse(BaseModel):
    """API key response (without the actual key)."""
    id: str
    key_prefix: str
    description: str
    priority: str
    created_at: datetime
    expires_at: Optional[datetime]
    revoked_at: Optional[datetime]
    is_valid: bool


class ApiKeyUpdateRequest(BaseModel):
    """Request to update an API key."""
    description: Optional[str] = None
    priority: Optional[str] = None
    expires_at: Optional[datetime] = None


class ApiKeyRefreshResponse(BaseModel):
    """Response after refreshing an API key."""
    id: str
    key: str  # New key
    key_prefix: str


class ApiKeyCountResponse(BaseModel):
    """API key count statistics."""
    total: int
    active: int
    expired: int
    revoked: int


class MonitorResponse(BaseModel):
    """Real-time monitoring data."""
    global_concurrent: int
    global_sse_connections: int
    global_requests_this_minute: int
    queue_size: int = 0


# ============== Auth Dependency ==============

async def require_auth(request: Request):
    """Dependency to require admin authentication."""
    if not _admin_auth_service:
        raise HTTPException(status_code=503, detail="Service not configured")

    authorization = request.headers.get("Authorization")
    token = _admin_auth_service.extract_token_from_header(authorization)

    if not token:
        raise HTTPException(
            status_code=401,
            detail={"error": "unauthorized", "message": "Missing or invalid token"}
        )

    if not _admin_auth_service.verify_token(token):
        raise HTTPException(
            status_code=401,
            detail={"error": "unauthorized", "message": "Invalid or expired token"}
        )


# ============== Auth Routes ==============

@router.post("/login", response_model=LoginResponse)
async def login(body: LoginRequest):
    """
    Authenticate admin and get JWT token.
    """
    if not _admin_auth_service:
        raise HTTPException(status_code=503, detail="Service not configured")

    token = _admin_auth_service.authenticate(body.password)
    if not token:
        raise HTTPException(
            status_code=401,
            detail={"error": "unauthorized", "message": "Invalid password"}
        )

    return LoginResponse(
        token=token,
        expires_in_hours=_admin_auth_service.config.jwt_expire_hours,
    )


# ============== API Key Routes ==============

@router.get("/api-keys", response_model=List[ApiKeyResponse], dependencies=[Depends(require_auth)])
async def list_api_keys(
    include_revoked: bool = False,
    include_expired: bool = False,
):
    """
    List all API keys.
    """
    if not _session_factory:
        raise HTTPException(status_code=503, detail="Service not configured")

    async with _session_factory() as session:
        service = ApiKeyService(session)
        keys = await service.list_api_keys(
            include_revoked=include_revoked,
            include_expired=include_expired,
        )

        return [
            ApiKeyResponse(
                id=key.id,
                key_prefix=key.key_prefix,
                description=key.description,
                priority=key.priority.value,
                created_at=key.created_at,
                expires_at=key.expires_at,
                revoked_at=key.revoked_at,
                is_valid=key.is_valid,
            )
            for key in keys
        ]


@router.post("/api-keys", response_model=ApiKeyCreateResponse, dependencies=[Depends(require_auth)])
async def create_api_key(body: ApiKeyCreateRequest):
    """
    Create a new API key.

    The actual key is only returned once in this response.
    """
    if not _session_factory:
        raise HTTPException(status_code=503, detail="Service not configured")

    # Validate priority
    try:
        priority = Priority(body.priority)
    except ValueError:
        raise HTTPException(
            status_code=400,
            detail={"error": "invalid_priority", "message": f"Invalid priority: {body.priority}"}
        )

    async with _session_factory() as session:
        service = ApiKeyService(session)
        raw_key, api_key = await service.create_api_key(
            description=body.description,
            priority=priority,
            expires_in_days=body.expires_in_days,
            rate_limit_config=body.rate_limit_config,
        )

        return ApiKeyCreateResponse(
            id=api_key.id,
            key=raw_key,
            key_prefix=api_key.key_prefix,
            description=api_key.description,
            priority=api_key.priority.value,
            created_at=api_key.created_at,
            expires_at=api_key.expires_at,
        )


@router.get("/api-keys/count", response_model=ApiKeyCountResponse, dependencies=[Depends(require_auth)])
async def get_api_key_count():
    """
    Get API key statistics.
    """
    if not _session_factory:
        raise HTTPException(status_code=503, detail="Service not configured")

    async with _session_factory() as session:
        service = ApiKeyService(session)
        counts = await service.get_api_key_count()
        return ApiKeyCountResponse(**counts)


@router.get("/api-keys/{key_id}", response_model=ApiKeyResponse, dependencies=[Depends(require_auth)])
async def get_api_key(key_id: str):
    """
    Get a single API key by ID.
    """
    if not _session_factory:
        raise HTTPException(status_code=503, detail="Service not configured")

    async with _session_factory() as session:
        service = ApiKeyService(session)
        api_key = await service.get_api_key(key_id)

        if not api_key:
            raise HTTPException(
                status_code=404,
                detail={"error": "not_found", "message": "API key not found"}
            )

        return ApiKeyResponse(
            id=api_key.id,
            key_prefix=api_key.key_prefix,
            description=api_key.description,
            priority=api_key.priority.value,
            created_at=api_key.created_at,
            expires_at=api_key.expires_at,
            revoked_at=api_key.revoked_at,
            is_valid=api_key.is_valid,
        )


@router.put("/api-keys/{key_id}", response_model=ApiKeyResponse, dependencies=[Depends(require_auth)])
async def update_api_key(key_id: str, body: ApiKeyUpdateRequest):
    """
    Update an API key.
    """
    if not _session_factory:
        raise HTTPException(status_code=503, detail="Service not configured")

    # Validate priority if provided
    priority = None
    if body.priority is not None:
        try:
            priority = Priority(body.priority)
        except ValueError:
            raise HTTPException(
                status_code=400,
                detail={"error": "invalid_priority", "message": f"Invalid priority: {body.priority}"}
            )

    async with _session_factory() as session:
        service = ApiKeyService(session)
        api_key = await service.update_api_key(
            key_id,
            description=body.description,
            priority=priority,
            expires_at=body.expires_at,
        )

        if not api_key:
            raise HTTPException(
                status_code=404,
                detail={"error": "not_found", "message": "API key not found"}
            )

        return ApiKeyResponse(
            id=api_key.id,
            key_prefix=api_key.key_prefix,
            description=api_key.description,
            priority=api_key.priority.value,
            created_at=api_key.created_at,
            expires_at=api_key.expires_at,
            revoked_at=api_key.revoked_at,
            is_valid=api_key.is_valid,
        )


@router.post("/api-keys/{key_id}/revoke", response_model=ApiKeyResponse, dependencies=[Depends(require_auth)])
async def revoke_api_key(key_id: str):
    """
    Revoke an API key.
    """
    if not _session_factory:
        raise HTTPException(status_code=503, detail="Service not configured")

    async with _session_factory() as session:
        service = ApiKeyService(session)
        api_key = await service.revoke_api_key(key_id)

        if not api_key:
            raise HTTPException(
                status_code=404,
                detail={"error": "not_found", "message": "API key not found"}
            )

        return ApiKeyResponse(
            id=api_key.id,
            key_prefix=api_key.key_prefix,
            description=api_key.description,
            priority=api_key.priority.value,
            created_at=api_key.created_at,
            expires_at=api_key.expires_at,
            revoked_at=api_key.revoked_at,
            is_valid=api_key.is_valid,
        )


@router.post("/api-keys/{key_id}/refresh", response_model=ApiKeyRefreshResponse, dependencies=[Depends(require_auth)])
async def refresh_api_key(key_id: str):
    """
    Refresh an API key (generate new key, keep same ID).

    The new key is only returned once in this response.
    """
    if not _session_factory:
        raise HTTPException(status_code=503, detail="Service not configured")

    async with _session_factory() as session:
        service = ApiKeyService(session)
        result = await service.refresh_api_key(key_id)

        if not result:
            raise HTTPException(
                status_code=404,
                detail={"error": "not_found", "message": "API key not found"}
            )

        raw_key, api_key = result
        return ApiKeyRefreshResponse(
            id=api_key.id,
            key=raw_key,
            key_prefix=api_key.key_prefix,
        )


@router.delete("/api-keys/{key_id}", dependencies=[Depends(require_auth)])
async def delete_api_key(key_id: str):
    """
    Permanently delete an API key.
    """
    if not _session_factory:
        raise HTTPException(status_code=503, detail="Service not configured")

    async with _session_factory() as session:
        service = ApiKeyService(session)
        deleted = await service.delete_api_key(key_id)

        if not deleted:
            raise HTTPException(
                status_code=404,
                detail={"error": "not_found", "message": "API key not found"}
            )

        return {"message": "API key deleted"}


# ============== Monitor Routes ==============

@router.get("/monitor", response_model=MonitorResponse, dependencies=[Depends(require_auth)])
async def get_monitor_data():
    """
    Get real-time monitoring data.
    """
    if not _rate_limiter:
        return MonitorResponse(
            global_concurrent=0,
            global_sse_connections=0,
            global_requests_this_minute=0,
            queue_size=0,
        )

    stats = _rate_limiter.get_stats()
    return MonitorResponse(
        global_concurrent=stats.get("global_concurrent", 0),
        global_sse_connections=stats.get("global_sse_connections", 0),
        global_requests_this_minute=stats.get("global_requests_this_minute", 0),
        queue_size=stats.get("queue_size", 0),
    )


# ============== Health Check ==============

@router.get("/health")
async def health_check():
    """
    Health check endpoint (no auth required).
    """
    return {"status": "ok"}
