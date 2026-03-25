import asyncio
import time

import pytest
from fastapi import HTTPException
from starlette.testclient import TestClient
from unittest.mock import MagicMock, patch, patch as _patch

from frontdoor.config import Settings

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


# ---------------------------------------------------------------------------
# Route tests – require the app to have the auth router registered
# ---------------------------------------------------------------------------


@pytest.fixture
def auth_client():
    """TestClient that does NOT follow redirects (so we can inspect 3xx responses)."""
    from frontdoor.main import app

    return TestClient(app, base_url="https://testserver", follow_redirects=False)


@pytest.fixture
def valid_token():
    """A freshly-minted, valid session token for 'testuser'."""
    from frontdoor.auth import create_session_token

    return create_session_token("testuser", SECRET)


@pytest.fixture
def patched_settings():
    """Settings with the known SECRET and a long timeout."""
    s = Settings()
    s.secret_key = SECRET
    s.session_timeout = 3600
    s.cookie_domain = ""
    return s


class TestValidateRoute:
    def test_no_cookie_returns_401(self, auth_client):
        response = auth_client.get("/api/auth/validate")
        assert response.status_code == 401

    def test_invalid_cookie_returns_401(self, auth_client):
        response = auth_client.get(
            "/api/auth/validate", cookies={"frontdoor_session": "garbage-token"}
        )
        assert response.status_code == 401

    def test_valid_cookie_returns_200_with_header(
        self, auth_client, valid_token, patched_settings
    ):
        with _patch("frontdoor.auth.settings", patched_settings):
            response = auth_client.get(
                "/api/auth/validate",
                cookies={"frontdoor_session": valid_token},
            )
        assert response.status_code == 200
        assert response.headers.get("x-authenticated-user") == "testuser"


class TestLogoutRoute:
    def test_logout_redirects_303_to_login(self, auth_client):
        response = auth_client.post("/api/auth/logout")
        assert response.status_code == 303
        assert response.headers.get("location") in (
            "/login",
            "https://testserver/login",
        )

    def test_logout_clears_cookie(self, auth_client):
        response = auth_client.post("/api/auth/logout")
        set_cookie = response.headers.get("set-cookie", "")
        assert "frontdoor_session" in set_cookie
        assert "max-age=0" in set_cookie.lower()


class TestLoginRoute:
    def test_successful_login_sets_cookie_and_redirects(self, auth_client):
        with patch("frontdoor.routes.auth.authenticate_pam", return_value=True):
            response = auth_client.post(
                "/api/auth/login",
                data={"username": "testuser", "password": "goodpass"},
            )
        assert response.status_code == 303
        location = response.headers.get("location", "")
        assert location == "/"
        assert "frontdoor_session" in response.headers.get("set-cookie", "")

    def test_failed_login_redirects_with_error(self, auth_client):
        with patch("frontdoor.routes.auth.authenticate_pam", return_value=False):
            response = auth_client.post(
                "/api/auth/login",
                data={"username": "testuser", "password": "badpass"},
            )
        assert response.status_code == 303
        location = response.headers.get("location", "")
        assert location.startswith("/login?error=1")

    def test_next_param_redirects(self, auth_client):
        with patch("frontdoor.routes.auth.authenticate_pam", return_value=True):
            response = auth_client.post(
                "/api/auth/login?next=/some/deep/page",
                data={"username": "testuser", "password": "goodpass"},
            )
        assert response.status_code == 303
        location = response.headers.get("location", "")
        assert location == "/some/deep/page"

    def test_failed_login_preserves_next(self, auth_client):
        with patch("frontdoor.routes.auth.authenticate_pam", return_value=False):
            response = auth_client.post(
                "/api/auth/login?next=/some/deep/page",
                data={"username": "testuser", "password": "badpass"},
            )
        assert response.status_code == 303
        location = response.headers.get("location", "")
        assert "error=1" in location
        assert "next=" in location

    def test_cookie_name_is_frontdoor_session(self, auth_client):
        with patch("frontdoor.routes.auth.authenticate_pam", return_value=True):
            response = auth_client.post(
                "/api/auth/login",
                data={"username": "testuser", "password": "goodpass"},
            )
        assert "frontdoor_session" in response.headers.get("set-cookie", "")

    def test_cookie_is_httponly(self, auth_client):
        with patch("frontdoor.routes.auth.authenticate_pam", return_value=True):
            response = auth_client.post(
                "/api/auth/login",
                data={"username": "testuser", "password": "goodpass"},
            )
        set_cookie = response.headers.get("set-cookie", "").lower()
        assert "httponly" in set_cookie

    def test_cookie_samesite_lax(self, auth_client):
        with patch("frontdoor.routes.auth.authenticate_pam", return_value=True):
            response = auth_client.post(
                "/api/auth/login",
                data={"username": "testuser", "password": "goodpass"},
            )
        set_cookie = response.headers.get("set-cookie", "").lower()
        assert "samesite=lax" in set_cookie

    # ------------------------------------------------------------------
    # Security regression tests: open redirect and URL encoding
    # ------------------------------------------------------------------

    def test_open_redirect_absolute_url_rejected(self, auth_client):
        """Successful login with an absolute external next must not redirect off-site."""
        with patch("frontdoor.routes.auth.authenticate_pam", return_value=True):
            response = auth_client.post(
                "/api/auth/login?next=https://evil.example",
                data={"username": "testuser", "password": "goodpass"},
            )
        assert response.status_code == 303
        location = response.headers.get("location", "")
        assert location == "/"

    def test_open_redirect_protocol_relative_rejected(self, auth_client):
        """Successful login with a protocol-relative next must not redirect off-site."""
        with patch("frontdoor.routes.auth.authenticate_pam", return_value=True):
            response = auth_client.post(
                "/api/auth/login?next=//evil.example",
                data={"username": "testuser", "password": "goodpass"},
            )
        assert response.status_code == 303
        location = response.headers.get("location", "")
        assert location == "/"

    def test_failed_login_next_is_url_encoded(self, auth_client):
        """Failed login redirect must URL-encode next so embedded chars don't corrupt the query string."""
        with patch("frontdoor.routes.auth.authenticate_pam", return_value=False):
            response = auth_client.post(
                "/api/auth/login?next=/path%3Fx%3D1%26admin%3Dtrue",
                data={"username": "testuser", "password": "badpass"},
            )
        assert response.status_code == 303
        location = response.headers.get("location", "")
        # If next is not encoded, "admin=true" appears as a standalone query param
        assert "admin=true" not in location
        assert "error=1" in location
        assert "next=" in location

    def test_failed_login_has_no_session_cookie(self, auth_client):
        """Failed login must not issue a session cookie."""
        with patch("frontdoor.routes.auth.authenticate_pam", return_value=False):
            response = auth_client.post(
                "/api/auth/login",
                data={"username": "testuser", "password": "badpass"},
            )
        assert response.status_code == 303
        set_cookie = response.headers.get("set-cookie", "")
        assert "frontdoor_session" not in set_cookie
