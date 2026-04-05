"""Tests for require_admin_auth — three-tier admin authentication."""

import asyncio
from unittest.mock import MagicMock, patch

import pytest
from fastapi import HTTPException

from frontdoor.config import Settings

SECRET = "test-secret-key-for-admin-auth"


def _make_request(
    host: str = "10.0.0.5",
    bearer: str | None = None,
    cookie: str | None = None,
) -> MagicMock:
    """Build a mock FastAPI Request with configurable auth sources."""
    request = MagicMock()
    request.client = MagicMock()
    request.client.host = host
    request.headers = {}
    if bearer:
        request.headers["authorization"] = f"Bearer {bearer}"
    request.cookies = {}
    if cookie:
        request.cookies["frontdoor_session"] = cookie
    return request


class TestLocalhostBypass:
    def test_localhost_allowed(self, tmp_path):
        """Requests from 127.0.0.1 pass without token or cookie."""
        from frontdoor.auth import require_admin_auth

        tokens_file = tmp_path / "tokens.json"
        tokens_file.write_text("{}")
        mock_settings = Settings()
        mock_settings.allow_localhost_admin = True
        mock_settings.tokens_file = tokens_file

        request = _make_request(host="127.0.0.1")

        with patch("frontdoor.auth.settings", mock_settings):
            result = asyncio.get_event_loop().run_until_complete(
                require_admin_auth(request)
            )
        assert result == "localhost"

    def test_localhost_disabled(self, tmp_path):
        """When allow_localhost_admin=False, localhost alone is not enough."""
        from frontdoor.auth import require_admin_auth

        tokens_file = tmp_path / "tokens.json"
        tokens_file.write_text("{}")
        mock_settings = Settings()
        mock_settings.allow_localhost_admin = False
        mock_settings.tokens_file = tokens_file
        mock_settings.secret_key = SECRET
        mock_settings.session_timeout = 3600

        request = _make_request(host="127.0.0.1")

        with patch("frontdoor.auth.settings", mock_settings):
            with pytest.raises(HTTPException) as exc_info:
                asyncio.get_event_loop().run_until_complete(
                    require_admin_auth(request)
                )
        assert exc_info.value.status_code == 401


class TestTokenAuth:
    def test_valid_bearer_token(self, tmp_path):
        """Valid Bearer token returns the token name."""
        from frontdoor.auth import require_admin_auth
        from frontdoor.tokens import create_token

        tokens_file = tmp_path / "tokens.json"
        _, raw_token = create_token("test-device", tokens_file=tokens_file)

        mock_settings = Settings()
        mock_settings.tokens_file = tokens_file
        mock_settings.allow_localhost_admin = False
        mock_settings.secret_key = SECRET
        mock_settings.session_timeout = 3600

        request = _make_request(host="10.0.0.5", bearer=raw_token)

        with patch("frontdoor.auth.settings", mock_settings):
            result = asyncio.get_event_loop().run_until_complete(
                require_admin_auth(request)
            )
        assert result == "token:test-device"

    def test_invalid_bearer_token(self, tmp_path):
        """Invalid Bearer token with no other auth raises 401."""
        from frontdoor.auth import require_admin_auth

        tokens_file = tmp_path / "tokens.json"
        tokens_file.write_text("{}")
        mock_settings = Settings()
        mock_settings.tokens_file = tokens_file
        mock_settings.allow_localhost_admin = False
        mock_settings.secret_key = SECRET
        mock_settings.session_timeout = 3600

        request = _make_request(host="10.0.0.5", bearer="ft_invalid_garbage")

        with patch("frontdoor.auth.settings", mock_settings):
            with pytest.raises(HTTPException) as exc_info:
                asyncio.get_event_loop().run_until_complete(
                    require_admin_auth(request)
                )
        assert exc_info.value.status_code == 401


class TestCookieAuth:
    def test_valid_session_cookie(self, tmp_path):
        """Valid session cookie passes admin auth."""
        from frontdoor.auth import create_session_token, require_admin_auth

        tokens_file = tmp_path / "tokens.json"
        tokens_file.write_text("{}")
        mock_settings = Settings()
        mock_settings.tokens_file = tokens_file
        mock_settings.allow_localhost_admin = False
        mock_settings.secret_key = SECRET
        mock_settings.session_timeout = 3600

        token = create_session_token("alice", SECRET)
        request = _make_request(host="10.0.0.5", cookie=token)

        with patch("frontdoor.auth.settings", mock_settings):
            result = asyncio.get_event_loop().run_until_complete(
                require_admin_auth(request)
            )
        assert result == "alice"


class TestNoAuth:
    def test_no_credentials_raises_401(self, tmp_path):
        """Request with no auth of any kind raises 401."""
        from frontdoor.auth import require_admin_auth

        tokens_file = tmp_path / "tokens.json"
        tokens_file.write_text("{}")
        mock_settings = Settings()
        mock_settings.tokens_file = tokens_file
        mock_settings.allow_localhost_admin = False
        mock_settings.secret_key = SECRET
        mock_settings.session_timeout = 3600

        request = _make_request(host="10.0.0.5")

        with patch("frontdoor.auth.settings", mock_settings):
            with pytest.raises(HTTPException) as exc_info:
                asyncio.get_event_loop().run_until_complete(
                    require_admin_auth(request)
                )
        assert exc_info.value.status_code == 401
