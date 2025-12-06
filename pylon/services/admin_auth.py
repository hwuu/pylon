"""
Admin authentication service.
"""

from datetime import datetime, timedelta, timezone
from typing import Optional

import jwt

from pylon.config import AdminConfig
from pylon.utils.crypto import verify_password


class AdminAuthService:
    """Service for admin authentication."""

    def __init__(self, config: AdminConfig):
        self.config = config

    def authenticate(self, password: str) -> Optional[str]:
        """
        Authenticate admin with password.

        Args:
            password: The password to verify

        Returns:
            JWT token if authentication successful, None otherwise.
        """
        if not self.config.password_hash:
            return None

        if not verify_password(password, self.config.password_hash):
            return None

        return self._create_token()

    def _create_token(self) -> str:
        """Create a JWT token."""
        now = datetime.now(timezone.utc)
        expire = now + timedelta(hours=self.config.jwt_expire_hours)

        payload = {
            "sub": "admin",
            "iat": now,
            "exp": expire,
        }

        return jwt.encode(payload, self.config.jwt_secret, algorithm="HS256")

    def verify_token(self, token: str) -> bool:
        """
        Verify a JWT token.

        Args:
            token: The JWT token to verify

        Returns:
            True if token is valid, False otherwise.
        """
        if not self.config.jwt_secret:
            return False

        try:
            jwt.decode(token, self.config.jwt_secret, algorithms=["HS256"])
            return True
        except jwt.PyJWTError:
            return False

    def extract_token_from_header(self, authorization: Optional[str]) -> Optional[str]:
        """
        Extract JWT token from Authorization header.

        Args:
            authorization: The Authorization header value

        Returns:
            The token if present, None otherwise.
        """
        if not authorization:
            return None

        parts = authorization.split()
        if len(parts) != 2:
            return None

        scheme, token = parts
        if scheme.lower() != "bearer":
            return None

        return token.strip() if token.strip() else None
