import asyncio
import time
import pytest
from unittest.mock import patch, MagicMock
from fastapi import HTTPException

SECRET = "test-secret-key-for-unit-tests"


class TestCreateSessionToken:
    def test_returns_string(self):
        from frontdoor.auth import create_session_token

        token = create_session_token("testuser", SECRET)
        assert isinstance(token, str)
        assert len(token) > 0

    def test_contains_username(self):
        from frontdoor.auth import create_session_token

        token = create_session_token("alice", SECRET)
        assert "alice" in token

    def test_different_users_different_tokens(self):
        from frontdoor.auth import create_session_token

        t1 = create_session_token("alice", SECRET)
        t2 = create_session_token("bob", SECRET)
        assert t1 != t2


class TestValidateSessionToken:
    def test_valid_returns_username(self):
        from frontdoor.auth import create_session_token, validate_session_token

        token = create_session_token("alice", SECRET)
        result = validate_session_token(token, SECRET, max_age=3600)
        assert result == "alice"

    def test_wrong_secret_returns_none(self):
        from frontdoor.auth import create_session_token, validate_session_token

        token = create_session_token("alice", SECRET)
        result = validate_session_token(token, "wrong-secret", max_age=3600)
        assert result is None

    def test_tampered_returns_none(self):
        from frontdoor.auth import create_session_token, validate_session_token

        token = create_session_token("alice", SECRET)
        tampered = token[:-5] + "XXXXX"
        result = validate_session_token(tampered, SECRET, max_age=3600)
        assert result is None

    def test_expired_returns_none(self):
        from frontdoor.auth import create_session_token, validate_session_token

        token = create_session_token("alice", SECRET)
        time.sleep(1.1)  # itsdangerous uses second-resolution timestamps
        result = validate_session_token(token, SECRET, max_age=0)
        assert result is None


class TestAuthenticatePam:
    def test_mock_success(self):
        from frontdoor.auth import authenticate_pam

        with patch("frontdoor.auth.pam.pam") as mock_pam_class:
            mock_pam_class.return_value.authenticate.return_value = True
            assert authenticate_pam("user", "pass") is True

    def test_mock_failure(self):
        from frontdoor.auth import authenticate_pam

        with patch("frontdoor.auth.pam.pam") as mock_pam_class:
            mock_pam_class.return_value.authenticate.return_value = False
            assert authenticate_pam("user", "wrong") is False


class TestRequireAuth:
    def test_missing_cookie_raises_401(self):
        from frontdoor.auth import require_auth

        request = MagicMock()
        request.cookies = {}
        with pytest.raises(HTTPException) as exc_info:
            asyncio.get_event_loop().run_until_complete(require_auth(request))
        assert exc_info.value.status_code == 401
        assert exc_info.value.detail["code"] == "UNAUTHORIZED"  # type: ignore[index]

    def test_invalid_token_raises_401(self):
        from frontdoor.auth import require_auth

        request = MagicMock()
        request.cookies = {"frontdoor_session": "garbage-token"}
        with pytest.raises(HTTPException) as exc_info:
            asyncio.get_event_loop().run_until_complete(require_auth(request))
        assert exc_info.value.status_code == 401
        assert exc_info.value.detail["code"] == "UNAUTHORIZED"  # type: ignore[index]

    def test_valid_token_returns_username(self):
        from frontdoor.auth import create_session_token, require_auth
        from frontdoor.config import Settings

        token = create_session_token("alice", SECRET)
        request = MagicMock()
        request.cookies = {"frontdoor_session": token}

        mock_settings = Settings()
        mock_settings.secret_key = SECRET
        mock_settings.session_timeout = 3600

        with patch("frontdoor.auth.settings", mock_settings):
            result = asyncio.get_event_loop().run_until_complete(require_auth(request))
        assert result == "alice"
