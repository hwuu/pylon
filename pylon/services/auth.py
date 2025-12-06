"""
Authentication service for API Key validation.
"""

from datetime import datetime, timezone
from typing import Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from pylon.models.api_key import ApiKey
from pylon.utils.crypto import hash_api_key


class AuthService:
    """Service for API Key authentication."""

    def __init__(self, session: AsyncSession):
        self.session = session

    async def validate_api_key(self, api_key: str) -> Optional[ApiKey]:
        """
        Validate an API key and return the ApiKey object if valid.

        Args:
            api_key: The API key to validate.

        Returns:
            The ApiKey object if valid, None otherwise.
        """
        if not api_key:
            return None

        # Hash the key and look it up
        key_hash = hash_api_key(api_key)

        stmt = select(ApiKey).where(ApiKey.key_hash == key_hash)
        result = await self.session.execute(stmt)
        api_key_obj = result.scalar_one_or_none()

        if api_key_obj is None:
            return None

        # Check if valid (not expired and not revoked)
        if not api_key_obj.is_valid:
            return None

        return api_key_obj

    async def get_api_key_by_id(self, key_id: str) -> Optional[ApiKey]:
        """
        Get an API key by its ID.

        Args:
            key_id: The API key ID.

        Returns:
            The ApiKey object if found, None otherwise.
        """
        stmt = select(ApiKey).where(ApiKey.id == key_id)
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none()


def extract_api_key_from_header(authorization: Optional[str]) -> Optional[str]:
    """
    Extract API key from Authorization header.

    Expected format: "Bearer <api_key>"

    Args:
        authorization: The Authorization header value.

    Returns:
        The extracted API key, or None if invalid format.
    """
    if not authorization:
        return None

    parts = authorization.split(" ", 1)
    if len(parts) != 2:
        return None

    scheme, token = parts
    if scheme.lower() != "bearer":
        return None

    return token.strip() if token.strip() else None
