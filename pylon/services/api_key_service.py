"""
API Key management service.
"""

from datetime import datetime, timedelta, timezone
from typing import Optional, List

from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from pylon.models.api_key import ApiKey, Priority
from pylon.utils.crypto import generate_api_key, hash_api_key, get_api_key_prefix


class ApiKeyService:
    """Service for managing API keys."""

    def __init__(self, session: AsyncSession):
        self.session = session

    async def create_api_key(
        self,
        description: str = "",
        priority: Priority = Priority.NORMAL,
        expires_in_days: Optional[int] = None,
        rate_limit_config: Optional[dict] = None,
    ) -> tuple[str, ApiKey]:
        """
        Create a new API key.

        Args:
            description: Short description of the key
            priority: Key priority (high/normal/low)
            expires_in_days: Days until expiration (None = never expires)
            rate_limit_config: Custom rate limit config for this key

        Returns:
            Tuple of (raw_key, api_key_object).
            The raw key is only returned once and cannot be retrieved later.
        """
        raw_key = generate_api_key()

        expires_at = None
        if expires_in_days is not None:
            expires_at = datetime.now(timezone.utc) + timedelta(days=expires_in_days)

        api_key = ApiKey(
            key_hash=hash_api_key(raw_key),
            key_prefix=get_api_key_prefix(raw_key),
            description=description,
            priority=priority,
            expires_at=expires_at,
        )

        if rate_limit_config:
            import json
            api_key.rate_limit_config = json.dumps(rate_limit_config)

        self.session.add(api_key)
        await self.session.commit()
        await self.session.refresh(api_key)

        return raw_key, api_key

    async def list_api_keys(
        self,
        include_revoked: bool = False,
        include_expired: bool = False,
    ) -> List[ApiKey]:
        """
        List all API keys.

        Args:
            include_revoked: Include revoked keys
            include_expired: Include expired keys

        Returns:
            List of API key objects.
        """
        query = select(ApiKey)

        if not include_revoked:
            query = query.where(ApiKey.revoked_at.is_(None))

        if not include_expired:
            query = query.where(
                (ApiKey.expires_at.is_(None)) |
                (ApiKey.expires_at > datetime.now(timezone.utc))
            )

        query = query.order_by(ApiKey.created_at.desc())
        result = await self.session.execute(query)
        return list(result.scalars().all())

    async def get_api_key(self, key_id: str) -> Optional[ApiKey]:
        """
        Get an API key by ID.

        Args:
            key_id: The API key ID

        Returns:
            The API key object or None.
        """
        result = await self.session.execute(
            select(ApiKey).where(ApiKey.id == key_id)
        )
        return result.scalar_one_or_none()

    async def update_api_key(
        self,
        key_id: str,
        description: Optional[str] = None,
        priority: Optional[Priority] = None,
        expires_at: Optional[datetime] = None,
        rate_limit_config: Optional[dict] = None,
    ) -> Optional[ApiKey]:
        """
        Update an API key.

        Args:
            key_id: The API key ID
            description: New description (None = don't change)
            priority: New priority (None = don't change)
            expires_at: New expiration time (None = don't change)
            rate_limit_config: New rate limit config (None = don't change)

        Returns:
            The updated API key object or None if not found.
        """
        api_key = await self.get_api_key(key_id)
        if not api_key:
            return None

        if description is not None:
            api_key.description = description

        if priority is not None:
            api_key.priority = priority

        if expires_at is not None:
            api_key.expires_at = expires_at

        if rate_limit_config is not None:
            import json
            api_key.rate_limit_config = json.dumps(rate_limit_config)

        await self.session.commit()
        await self.session.refresh(api_key)
        return api_key

    async def revoke_api_key(self, key_id: str) -> Optional[ApiKey]:
        """
        Revoke an API key.

        Args:
            key_id: The API key ID

        Returns:
            The revoked API key object or None if not found.
        """
        api_key = await self.get_api_key(key_id)
        if not api_key:
            return None

        api_key.revoked_at = datetime.now(timezone.utc)
        await self.session.commit()
        await self.session.refresh(api_key)
        return api_key

    async def refresh_api_key(self, key_id: str) -> Optional[tuple[str, ApiKey]]:
        """
        Refresh an API key (generate new key, keep same ID and settings).

        Args:
            key_id: The API key ID

        Returns:
            Tuple of (new_raw_key, api_key_object) or None if not found.
        """
        api_key = await self.get_api_key(key_id)
        if not api_key:
            return None

        # Generate new key
        new_raw_key = generate_api_key()
        api_key.key_hash = hash_api_key(new_raw_key)
        api_key.key_prefix = get_api_key_prefix(new_raw_key)

        await self.session.commit()
        await self.session.refresh(api_key)

        return new_raw_key, api_key

    async def delete_api_key(self, key_id: str) -> bool:
        """
        Permanently delete an API key.

        Args:
            key_id: The API key ID

        Returns:
            True if deleted, False if not found.
        """
        api_key = await self.get_api_key(key_id)
        if not api_key:
            return False

        await self.session.delete(api_key)
        await self.session.commit()
        return True

    async def get_api_key_count(self) -> dict:
        """
        Get API key statistics.

        Returns:
            Dict with counts: total, active, expired, revoked.
        """
        now = datetime.now(timezone.utc)

        # Total count
        total_result = await self.session.execute(
            select(func.count(ApiKey.id))
        )
        total = total_result.scalar() or 0

        # Active count (not expired and not revoked)
        active_result = await self.session.execute(
            select(func.count(ApiKey.id)).where(
                ApiKey.revoked_at.is_(None),
                (ApiKey.expires_at.is_(None)) | (ApiKey.expires_at > now)
            )
        )
        active = active_result.scalar() or 0

        # Expired count
        expired_result = await self.session.execute(
            select(func.count(ApiKey.id)).where(
                ApiKey.expires_at.is_not(None),
                ApiKey.expires_at <= now
            )
        )
        expired = expired_result.scalar() or 0

        # Revoked count
        revoked_result = await self.session.execute(
            select(func.count(ApiKey.id)).where(
                ApiKey.revoked_at.is_not(None)
            )
        )
        revoked = revoked_result.scalar() or 0

        return {
            "total": total,
            "active": active,
            "expired": expired,
            "revoked": revoked,
        }
