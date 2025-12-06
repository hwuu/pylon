"""
Cryptographic utilities for Pylon.
"""

import hashlib
import secrets
import string

import bcrypt


# API Key prefix
API_KEY_PREFIX = "sk-"
API_KEY_RANDOM_LENGTH = 32


def generate_api_key() -> str:
    """
    Generate a new API key.

    Format: sk-<32 random alphanumeric characters>
    Example: sk-a1b2c3d4e5f6g7h8i9j0k1l2m3n4o5p6

    Returns:
        The generated API key.
    """
    alphabet = string.ascii_lowercase + string.digits
    random_part = "".join(secrets.choice(alphabet) for _ in range(API_KEY_RANDOM_LENGTH))
    return f"{API_KEY_PREFIX}{random_part}"


def hash_api_key(api_key: str) -> str:
    """
    Hash an API key using SHA-256.

    Args:
        api_key: The API key to hash.

    Returns:
        The SHA-256 hash of the API key (hex string).
    """
    return hashlib.sha256(api_key.encode("utf-8")).hexdigest()


def get_api_key_prefix(api_key: str) -> str:
    """
    Get the prefix of an API key for display/identification.

    Args:
        api_key: The full API key.

    Returns:
        The prefix (e.g., "sk-a1b2").
    """
    # Return first 7 characters (sk- + 4 chars)
    return api_key[:7] if len(api_key) >= 7 else api_key


def hash_password(password: str) -> str:
    """
    Hash a password using bcrypt.

    Args:
        password: The password to hash.

    Returns:
        The bcrypt hash of the password.
    """
    salt = bcrypt.gensalt(rounds=12)
    return bcrypt.hashpw(password.encode("utf-8"), salt).decode("utf-8")


def verify_password(password: str, password_hash: str) -> bool:
    """
    Verify a password against its bcrypt hash.

    Args:
        password: The password to verify.
        password_hash: The bcrypt hash to check against.

    Returns:
        True if the password matches, False otherwise.
    """
    try:
        return bcrypt.checkpw(
            password.encode("utf-8"),
            password_hash.encode("utf-8")
        )
    except (ValueError, TypeError):
        return False
