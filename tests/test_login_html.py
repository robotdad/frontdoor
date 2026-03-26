"""Tests for the login page at static/login.html."""

import frontdoor.main as main_module
from starlette.testclient import TestClient

from frontdoor.main import app

LOGIN_HTML = main_module._static_dir / "login.html"


class TestLoginHtmlFile:
    """Verify login.html exists with all required content per spec."""

    def test_file_exists(self):
        """login.html must exist in the static directory."""
        assert LOGIN_HTML.is_file(), (
            f"login.html not found at {LOGIN_HTML}. "
            "Create frontdoor/frontdoor/static/login.html"
        )

    def test_has_doctype(self):
        """File must start with <!DOCTYPE html>."""
        content = LOGIN_HTML.read_text()
        assert content.strip().startswith("<!DOCTYPE html>"), (
            "login.html must start with <!DOCTYPE html>"
        )

    def test_has_inter_font(self):
        """File must load Inter font via Google Fonts."""
        content = LOGIN_HTML.read_text()
        assert "fonts.googleapis.com" in content, (
            "login.html must load fonts from Google Fonts"
        )
        assert "Inter" in content, "login.html must use Inter font"

    def test_has_apple_hig_design_tokens_light_mode(self):
        """File must have Apple HIG light mode CSS tokens."""
        content = LOGIN_HTML.read_text()
        assert "--bg" in content, "login.html must have --bg CSS token"
        assert "--elevated" in content, "login.html must have --elevated CSS token"
        assert "--tint" in content, (
            "login.html must have --tint CSS token (Apple HIG blue)"
        )
        assert "#007AFF" in content, "login.html must have Apple HIG tint color #007AFF"

    def test_has_apple_hig_design_tokens_dark_mode(self):
        """File must have Apple HIG dark mode CSS tokens."""
        content = LOGIN_HTML.read_text()
        assert "prefers-color-scheme: dark" in content, (
            "login.html must have dark mode CSS tokens via @media prefers-color-scheme"
        )

    def test_has_card_entrance_animation(self):
        """File must have card entrance animation with scale+translate keyframes."""
        content = LOGIN_HTML.read_text()
        assert "@keyframes" in content, (
            "login.html must have CSS @keyframes for card entrance animation"
        )
        assert "scale" in content, (
            "login.html card entrance animation must use scale transform"
        )
        assert "translateY" in content or "translate" in content.lower(), (
            "login.html card entrance animation must use translate transform"
        )

    def test_has_spring_animation(self):
        """File must have spring animation for the login card."""
        content = LOGIN_HTML.read_text()
        assert "spring" in content or "cubic-bezier" in content, (
            "login.html must have spring animation (cubic-bezier) for card entrance"
        )

    def test_has_centered_login_card_max_400px(self):
        """File must have a login card centered with max-width: 400px."""
        content = LOGIN_HTML.read_text()
        assert "400px" in content, (
            "login.html must have centered login card with max-width: 400px"
        )

    def test_has_lock_icon_svg(self):
        """File must have a lock icon (SVG)."""
        content = LOGIN_HTML.read_text()
        assert "<svg" in content, "login.html must have a lock SVG icon"
        # The lock icon should reference lock-related path data or viewBox
        assert "viewBox" in content, "login.html SVG must have a viewBox attribute"

    def test_has_dynamic_hostname_display(self):
        """File must display hostname dynamically via JS."""
        content = LOGIN_HTML.read_text()
        assert "hostName" in content, (
            "login.html must have element with id='hostName' for dynamic hostname display"
        )
        assert "window.location.hostname" in content, (
            "login.html must use window.location.hostname to set hostname dynamically"
        )

    def test_has_username_field_with_proper_autocomplete(self):
        """Username field must have autocomplete='username' and autocapitalize='none'."""
        content = LOGIN_HTML.read_text()
        assert (
            'autocomplete="username"' in content or "autocomplete='username'" in content
        ), "login.html username field must have autocomplete='username'"
        assert (
            'autocapitalize="none"' in content or "autocapitalize='none'" in content
        ), "login.html username field must have autocapitalize='none' for mobile"

    def test_has_password_field(self):
        """File must have a password input field."""
        content = LOGIN_HTML.read_text()
        assert 'type="password"' in content or "type='password'" in content, (
            "login.html must have a password input field"
        )

    def test_has_sign_in_button_with_tint(self):
        """Sign In button must use tint color."""
        content = LOGIN_HTML.read_text()
        assert "Sign In" in content, "login.html must have a 'Sign In' button"
        # Tint color is used in background for the button
        assert "var(--tint)" in content, (
            "login.html Sign In button must use var(--tint) color"
        )

    def test_has_error_message_div_hidden_by_default(self):
        """Error message div must exist and be hidden by default."""
        content = LOGIN_HTML.read_text()
        # The error div should exist but not be visible by default
        # Check for error-related element with some form of hidden class
        assert "error" in content.lower(), (
            "login.html must have an error message element"
        )
        # The element should use CSS class toggling (not inline style display:none like old code)
        assert "classList" in content or "visible" in content, (
            "login.html error message must use classList for visibility toggling"
        )

    def test_error_shown_with_query_param_error_1(self):
        """Error message must be shown when URL has ?error=1."""
        content = LOGIN_HTML.read_text()
        assert "error" in content and (
            "=== '1'" in content or '=== "1"' in content or "get('error')" in content
        ), "login.html must check URL for ?error=1 to show the error message"

    def test_form_posts_to_api_auth_login(self):
        """Form must POST to /api/auth/login with next param."""
        content = LOGIN_HTML.read_text()
        assert "/api/auth/login" in content, (
            "login.html form must target /api/auth/login"
        )
        assert 'method="POST"' in content or "method='POST'" in content, (
            "login.html form must use POST method"
        )

    def test_js_sets_form_action_with_next_param(self):
        """JS must set form action to /api/auth/login?next=<encoded value>."""
        content = LOGIN_HTML.read_text()
        assert "next" in content, "login.html JS must read 'next' query param"
        assert "encodeURIComponent" in content, (
            "login.html JS must use encodeURIComponent for the next param"
        )
        assert "get('next')" in content or 'get("next")' in content, (
            "login.html JS must use URLSearchParams.get('next')"
        )

    def test_next_param_defaults_to_slash(self):
        """JS must default next param to '/' if not provided."""
        content = LOGIN_HTML.read_text()
        assert "|| '/'" in content or '|| "/"' in content, (
            "login.html JS must default next param to '/' if not present in URL"
        )

    def test_has_form_element_wrapping_fields(self):
        """Fields and button must be wrapped in a <form> element."""
        content = LOGIN_HTML.read_text()
        assert "<form" in content, (
            "login.html must have a <form> element wrapping the username/password fields"
        )

    def test_has_reduced_motion(self):
        """File must have reduced-motion media query."""
        content = LOGIN_HTML.read_text()
        assert "prefers-reduced-motion" in content, (
            "login.html must have @media (prefers-reduced-motion) query"
        )


class TestLoginHtmlServed:
    """Verify FastAPI serves login.html at /login.html."""

    def test_login_page_served(self):
        """GET /login.html must return 200 with the login page HTML."""
        with TestClient(app, base_url="https://testserver") as client:
            resp = client.get("/login.html", follow_redirects=False)
            assert resp.status_code == 200, (
                f"GET /login.html returned {resp.status_code}, expected 200"
            )
            assert "text/html" in resp.headers.get("content-type", ""), (
                "GET /login.html must return text/html content type"
            )
            assert "<!DOCTYPE html>" in resp.text, (
                "GET /login.html must return HTML with DOCTYPE"
            )

    def test_login_page_contains_form(self):
        """Served login page must contain the login form."""
        with TestClient(app, base_url="https://testserver") as client:
            resp = client.get("/login.html", follow_redirects=False)
            assert "/api/auth/login" in resp.text, (
                "Served login.html must contain form targeting /api/auth/login"
            )
