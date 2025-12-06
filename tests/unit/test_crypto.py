"""
Tests for cryptographic utilities.
"""

import pytest

from pylon.utils.crypto import (
    generate_api_key,
    hash_api_key,
    get_api_key_prefix,
    hash_password,
    verify_password,
    API_KEY_PREFIX,
    API_KEY_RANDOM_LENGTH,
)


class TestApiKey:
    """Tests for API key functions."""

    def test_generate_api_key_format(self):
        """Test that generated API keys have the correct format."""
        api_key = generate_api_key()

        assert api_key.startswith(API_KEY_PREFIX)
        assert len(api_key) == len(API_KEY_PREFIX) + API_KEY_RANDOM_LENGTH

    def test_generate_api_key_uniqueness(self):
        """Test that generated API keys are unique."""
        keys = [generate_api_key() for _ in range(100)]
        assert len(set(keys)) == 100  # All should be unique

    def test_generate_api_key_characters(self):
        """Test that generated API keys only contain valid characters."""
        api_key = generate_api_key()
        random_part = api_key[len(API_KEY_PREFIX):]

        # Should only contain lowercase letters and digits
        assert all(c.islower() or c.isdigit() for c in random_part)

    def test_hash_api_key(self):
        """Test API key hashing."""
        api_key = "sk-a1b2c3d4e5f6g7h8i9j0k1l2m3n4o5p6"
        hashed = hash_api_key(api_key)

        # SHA-256 produces 64 character hex string
        assert len(hashed) == 64
        assert all(c in "0123456789abcdef" for c in hashed)

    def test_hash_api_key_consistency(self):
        """Test that hashing the same key produces the same result."""
        api_key = "sk-test12345"
        hash1 = hash_api_key(api_key)
        hash2 = hash_api_key(api_key)

        assert hash1 == hash2

    def test_hash_api_key_different_keys(self):
        """Test that different keys produce different hashes."""
        key1 = "sk-test12345"
        key2 = "sk-test12346"

        hash1 = hash_api_key(key1)
        hash2 = hash_api_key(key2)

        assert hash1 != hash2

    def test_get_api_key_prefix(self):
        """Test getting API key prefix."""
        api_key = "sk-a1b2c3d4e5f6g7h8i9j0k1l2m3n4o5p6"
        prefix = get_api_key_prefix(api_key)

        assert prefix == "sk-a1b2"
        assert len(prefix) == 7

    def test_get_api_key_prefix_short_key(self):
        """Test getting prefix for a short key."""
        short_key = "sk-ab"
        prefix = get_api_key_prefix(short_key)

        assert prefix == "sk-ab"


class TestPassword:
    """Tests for password functions."""

    def test_hash_password(self):
        """Test password hashing."""
        password = "my-secure-password"
        hashed = hash_password(password)

        # bcrypt hashes start with $2b$
        assert hashed.startswith("$2b$")
        assert len(hashed) == 60  # bcrypt produces 60 character hashes

    def test_hash_password_different_each_time(self):
        """Test that hashing the same password produces different results (due to salt)."""
        password = "my-secure-password"
        hash1 = hash_password(password)
        hash2 = hash_password(password)

        assert hash1 != hash2  # Different salts

    def test_verify_password_correct(self):
        """Test verifying correct password."""
        password = "my-secure-password"
        hashed = hash_password(password)

        assert verify_password(password, hashed) is True

    def test_verify_password_incorrect(self):
        """Test verifying incorrect password."""
        password = "my-secure-password"
        wrong_password = "wrong-password"
        hashed = hash_password(password)

        assert verify_password(wrong_password, hashed) is False

    def test_verify_password_invalid_hash(self):
        """Test verifying against invalid hash."""
        password = "my-secure-password"

        assert verify_password(password, "invalid-hash") is False
        assert verify_password(password, "") is False

    def test_verify_password_unicode(self):
        """Test password with unicode characters."""
        password = "密码test123"
        hashed = hash_password(password)

        assert verify_password(password, hashed) is True
        assert verify_password("wrong", hashed) is False
