"""
Policy service for managing dynamic configuration.
"""

import json
import logging
from typing import Any, Callable, Coroutine

import yaml
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from pylon.models.policy import Policy

logger = logging.getLogger(__name__)


# Default policy values
DEFAULT_POLICY = {
    "downstream.base_url": "https://api.example.com",
    "downstream.timeout": 30,
    "rate_limit.global": {
        "max_concurrent": 50,
        "max_requests_per_minute": 500,
        "max_sse_connections": 20,
    },
    "rate_limit.default_user": {
        "max_concurrent": 4,
        "max_requests_per_minute": 60,
        "max_sse_connections": 2,
    },
    "rate_limit.apis": {},
    "rate_limit.api_patterns": [],
    "queue.max_size": 100,
    "queue.timeout": 30,
    "sse.idle_timeout": 60,
    "data_retention.days": 30,
    "data_retention.cleanup_interval_hours": 24,
}


class PolicyService:
    """Service for managing policy configuration."""

    def __init__(self, session_factory: Callable[[], AsyncSession]):
        self._session_factory = session_factory
        self._update_callbacks: list[Callable[[str], Coroutine[Any, Any, None]]] = []

    def on_update(self, callback: Callable[[str], Coroutine[Any, Any, None]]):
        """Register a callback to be called when a policy is updated."""
        self._update_callbacks.append(callback)

    async def _notify_update(self, key: str):
        """Notify all registered callbacks of a policy update."""
        for callback in self._update_callbacks:
            try:
                await callback(key)
            except Exception as e:
                logger.error(f"Error in policy update callback: {e}")

    async def get_all(self) -> dict[str, Any]:
        """Get all policy values as a dict."""
        async with self._session_factory() as session:
            result = await session.execute(select(Policy))
            policies = result.scalars().all()

            policy_dict = {}
            for p in policies:
                policy_dict[p.key] = json.loads(p.value)

            return policy_dict

    async def get(self, key: str) -> Any | None:
        """Get a single policy value."""
        async with self._session_factory() as session:
            result = await session.execute(
                select(Policy).where(Policy.key == key)
            )
            policy = result.scalar_one_or_none()
            if policy:
                return json.loads(policy.value)
            return None

    async def set(self, key: str, value: Any) -> None:
        """Set a single policy value."""
        async with self._session_factory() as session:
            result = await session.execute(
                select(Policy).where(Policy.key == key)
            )
            policy = result.scalar_one_or_none()

            json_value = json.dumps(value)
            if policy:
                policy.value = json_value
            else:
                policy = Policy(key=key, value=json_value)
                session.add(policy)

            await session.commit()

        await self._notify_update(key)

    async def set_many(self, items: dict[str, Any]) -> None:
        """Set multiple policy values."""
        async with self._session_factory() as session:
            for key, value in items.items():
                result = await session.execute(
                    select(Policy).where(Policy.key == key)
                )
                policy = result.scalar_one_or_none()

                json_value = json.dumps(value)
                if policy:
                    policy.value = json_value
                else:
                    policy = Policy(key=key, value=json_value)
                    session.add(policy)

            await session.commit()

        # Notify for all updated keys
        for key in items.keys():
            await self._notify_update(key)

    async def init_defaults(self) -> bool:
        """
        Initialize default policy values if table is empty.
        Returns True if defaults were initialized, False if already has data.
        """
        async with self._session_factory() as session:
            result = await session.execute(select(Policy).limit(1))
            if result.scalar_one_or_none() is not None:
                return False

            # Table is empty, initialize defaults
            for key, value in DEFAULT_POLICY.items():
                policy = Policy(key=key, value=json.dumps(value))
                session.add(policy)

            await session.commit()
            logger.info("Initialized default policy values")
            return True

    async def export_yaml(self) -> str:
        """Export all policies as YAML string."""
        policies = await self.get_all()
        structured = self._flatten_to_nested(policies)
        return yaml.dump(structured, default_flow_style=False, allow_unicode=True)

    async def parse_import(self, yaml_content: str) -> dict[str, dict]:
        """
        Parse YAML content and return diff with current values.

        Returns:
            {
                "added": {key: new_value, ...},
                "modified": {key: {"old": old_value, "new": new_value}, ...},
                "unchanged": {key: value, ...}
            }
        """
        try:
            imported = yaml.safe_load(yaml_content)
        except yaml.YAMLError as e:
            raise ValueError(f"Invalid YAML: {e}")

        if not isinstance(imported, dict):
            raise ValueError("YAML must be a dictionary")

        # Flatten nested structure to key-value pairs
        imported_flat = self._nested_to_flatten(imported)

        # Get current values
        current = await self.get_all()

        diff = {
            "added": {},
            "modified": {},
            "unchanged": {},
        }

        for key, new_value in imported_flat.items():
            if key not in current:
                diff["added"][key] = new_value
            elif current[key] != new_value:
                diff["modified"][key] = {"old": current[key], "new": new_value}
            else:
                diff["unchanged"][key] = new_value

        return diff

    async def apply_import(self, changes: dict[str, Any]) -> None:
        """Apply imported changes to the database."""
        items_to_set = {}

        if "added" in changes:
            items_to_set.update(changes["added"])
        if "modified" in changes:
            for key, diff in changes["modified"].items():
                items_to_set[key] = diff["new"]

        if items_to_set:
            await self.set_many(items_to_set)

    def _nested_to_flatten(self, nested: dict, prefix: str = "") -> dict[str, Any]:
        """Convert nested dict to flattened key-value pairs."""
        result = {}

        for key, value in nested.items():
            full_key = f"{prefix}.{key}" if prefix else key

            # These keys should be stored as nested objects, not flattened further
            terminal_keys = {
                "rate_limit.global",
                "rate_limit.default_user",
                "rate_limit.apis",
                "rate_limit.api_patterns",
            }

            if full_key in terminal_keys:
                result[full_key] = value
            elif isinstance(value, dict) and not self._is_terminal_dict(full_key):
                result.update(self._nested_to_flatten(value, full_key))
            else:
                result[full_key] = value

        return result

    def _is_terminal_dict(self, key: str) -> bool:
        """Check if a key should not be further flattened."""
        terminal_prefixes = [
            "rate_limit.global",
            "rate_limit.default_user",
            "rate_limit.apis",
            "rate_limit.api_patterns",
        ]
        return any(key.startswith(p) for p in terminal_prefixes)

    def _flatten_to_nested(self, flat: dict[str, Any]) -> dict:
        """Convert flattened key-value pairs to nested dict."""
        result = {}

        for key, value in flat.items():
            parts = key.split(".")
            current = result

            for i, part in enumerate(parts[:-1]):
                if part not in current:
                    current[part] = {}
                current = current[part]

            current[parts[-1]] = value

        return result


# Singleton instance (set during app initialization)
_policy_service: PolicyService | None = None


def get_policy_service() -> PolicyService:
    """Get the policy service instance."""
    if _policy_service is None:
        raise RuntimeError("Policy service not initialized")
    return _policy_service


def set_policy_service(service: PolicyService):
    """Set the policy service instance."""
    global _policy_service
    _policy_service = service
