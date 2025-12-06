"""
Tests for pylon/main.py CLI commands.
"""

import pytest
from unittest.mock import patch, MagicMock
from argparse import Namespace

from pylon.main import cmd_hash_password, main


class TestCmdHashPassword:
    """Tests for hash-password command."""

    def test_hash_password_success(self):
        """Test successful password hashing."""
        with patch("getpass.getpass") as mock_getpass:
            mock_getpass.side_effect = ["testpassword", "testpassword"]

            with patch("pylon.utils.hash_password") as mock_hash:
                mock_hash.return_value = "$2b$12$testhash"

                args = Namespace()
                result = cmd_hash_password(args)

                assert result == 0
                mock_hash.assert_called_once_with("testpassword")

    def test_hash_password_empty(self):
        """Test empty password rejection."""
        with patch("getpass.getpass") as mock_getpass:
            mock_getpass.return_value = ""

            args = Namespace()
            result = cmd_hash_password(args)

            assert result == 1

    def test_hash_password_mismatch(self):
        """Test password mismatch rejection."""
        with patch("getpass.getpass") as mock_getpass:
            mock_getpass.side_effect = ["password1", "password2"]

            args = Namespace()
            result = cmd_hash_password(args)

            assert result == 1

    def test_hash_password_cancelled(self):
        """Test keyboard interrupt handling."""
        with patch("getpass.getpass") as mock_getpass:
            mock_getpass.side_effect = KeyboardInterrupt()

            args = Namespace()
            result = cmd_hash_password(args)

            assert result == 1


class TestMainCLI:
    """Tests for main CLI argument parsing."""

    def test_default_command_is_serve(self):
        """Test that no command defaults to serve."""
        with patch("sys.argv", ["pylon"]):
            with patch("pylon.main.cmd_serve") as mock_serve:
                mock_serve.return_value = 0
                result = main()

                assert result == 0
                mock_serve.assert_called_once()

    def test_serve_command(self):
        """Test explicit serve command."""
        with patch("sys.argv", ["pylon", "serve", "-c", "test.yaml"]):
            with patch("pylon.main.cmd_serve") as mock_serve:
                mock_serve.return_value = 0
                result = main()

                assert result == 0
                args = mock_serve.call_args[0][0]
                assert args.config == "test.yaml"

    def test_hash_password_command(self):
        """Test hash-password command."""
        with patch("sys.argv", ["pylon", "hash-password"]):
            with patch("pylon.main.cmd_hash_password") as mock_hash:
                mock_hash.return_value = 0
                result = main()

                assert result == 0
                mock_hash.assert_called_once()
