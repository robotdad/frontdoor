"""Tests for the main portal UI at static/index.html."""

import frontdoor.main as main_module
import pytest
from starlette.testclient import TestClient

from frontdoor.auth import create_session_token
import frontdoor.config as config_module
from frontdoor.main import app

INDEX_HTML = main_module._static_dir / "index.html"


class TestIndexHtmlFile:
    """Verify index.html exists with required content."""

    def test_file_exists(self):
        """index.html must exist in the static directory."""
        assert INDEX_HTML.is_file(), (
            f"index.html not found at {INDEX_HTML}. "
            "Run: create frontdoor/frontdoor/static/index.html"
        )

    def test_has_doctype(self):
        """File must start with <!DOCTYPE html>."""
        content = INDEX_HTML.read_text()
        assert content.strip().startswith("<!DOCTYPE html>"), (
            "index.html must start with <!DOCTYPE html>"
        )

    def test_has_preact_htm_import(self):
        """File must import Preact+HTM from esm.sh."""
        content = INDEX_HTML.read_text()
        assert "esm.sh/htm/preact/standalone" in content, (
            "index.html must import Preact+HTM from https://esm.sh/htm/preact/standalone"
        )

    def test_fetches_api_services(self):
        """File must fetch /api/services."""
        content = INDEX_HTML.read_text()
        assert "/api/services" in content, (
            "index.html must fetch /api/services to get service data"
        )

    def test_has_light_dark_mode_tokens(self):
        """File must have Apple HIG light/dark mode CSS tokens."""
        content = INDEX_HTML.read_text()
        assert "prefers-color-scheme: dark" in content, (
            "index.html must have dark mode CSS tokens via @media prefers-color-scheme"
        )
        assert "--glass-bg" in content, (
            "index.html must have glassmorphic CSS tokens (--glass-bg)"
        )
        assert "--tint" in content, (
            "index.html must have Apple HIG tint color token (--tint)"
        )

    def test_has_responsive_grid(self):
        """File must have responsive service grid with auto-fill 280px, 2-col at 768px, 1-col at 480px."""
        content = INDEX_HTML.read_text()
        assert "auto-fill, minmax(280px" in content, (
            "index.html must have responsive grid: auto-fill, minmax(280px, 1fr)"
        )
        assert "max-width: 768px" in content, (
            "index.html must have 2-column breakpoint at 768px"
        )
        assert "max-width: 480px" in content, (
            "index.html must have 1-column breakpoint at 480px"
        )

    def test_has_glassmorphic_header(self):
        """File must have glassmorphic header styles."""
        content = INDEX_HTML.read_text()
        assert "backdrop-filter" in content, (
            "index.html must have glassmorphic header with backdrop-filter"
        )
        assert "header" in content.lower(), "index.html must have a header element"

    def test_has_status_dots(self):
        """File must have status dot CSS for up/down states."""
        content = INDEX_HTML.read_text()
        assert "status-dot" in content, (
            "index.html must have status-dot CSS class for service health indicators"
        )
        assert "--green" in content, (
            "index.html must use --green CSS token for up status dot"
        )
        assert "--red" in content, (
            "index.html must use --red CSS token for down status dot"
        )

    def test_has_also_running_section(self):
        """File must have 'Also Running' section for unregistered processes."""
        content = INDEX_HTML.read_text()
        assert "Also Running" in content, (
            "index.html must have 'Also Running' section for unregistered processes"
        )
        assert "port-badge" in content, (
            "index.html must have port-badge CSS class for unregistered port display"
        )

    def test_has_reduced_motion(self):
        """File must have reduced-motion media query."""
        content = INDEX_HTML.read_text()
        assert "prefers-reduced-motion" in content, (
            "index.html must have @media (prefers-reduced-motion) query"
        )

    def test_signout_posts_to_logout(self):
        """Sign-out must use a form POSTing to /api/auth/logout."""
        content = INDEX_HTML.read_text()
        assert "/api/auth/logout" in content, (
            "index.html sign-out button must POST to /api/auth/logout"
        )

    def test_has_google_fonts(self):
        """File must load Inter and JetBrains Mono via Google Fonts."""
        content = INDEX_HTML.read_text()
        assert "fonts.googleapis.com" in content, (
            "index.html must load fonts from Google Fonts"
        )
        assert "Inter" in content, "index.html must use Inter font"
        assert "JetBrains+Mono" in content or "JetBrains Mono" in content, (
            "index.html must use JetBrains Mono font"
        )

    def test_has_phosphor_icons(self):
        """File must load Phosphor Icons via CDN."""
        content = INDEX_HTML.read_text()
        assert "phosphor-icons" in content or "@phosphor-icons" in content, (
            "index.html must load Phosphor Icons via CDN"
        )

    def test_has_usestate_useeffect(self):
        """File must use useState and useEffect for the Preact app."""
        content = INDEX_HTML.read_text()
        assert "useState" in content, (
            "index.html Preact app must use useState for reactive state"
        )
        assert "useEffect" in content, (
            "index.html Preact app must use useEffect to fetch /api/services"
        )

    def test_has_hostname_display(self):
        """File must display hostname in the header."""
        content = INDEX_HTML.read_text()
        assert "hostname" in content.lower(), (
            "index.html header must display the hostname"
        )

    def test_has_fetch_error_handling(self):
        """fetchServices must use try/catch and track error state for visible failures."""
        content = INDEX_HTML.read_text()
        assert "try {" in content or "try{" in content, (
            "index.html fetchServices must use try/catch to handle network errors"
        )
        assert "catch" in content, (
            "index.html fetchServices must catch errors to prevent silent failures"
        )
        assert "setError" in content, (
            "index.html must track error state (setError) so fetch failures are visible"
        )

    def test_has_focus_visible_for_buttons(self):
        """Header buttons must have :focus-visible CSS for visible keyboard focus."""
        content = INDEX_HTML.read_text()
        assert ":focus-visible" in content, (
            "index.html must have :focus-visible CSS so keyboard focus is visible "
            "on refresh and sign-out buttons (outline: none alone removes it)"
        )


class TestIndexHtmlServed:
    """Verify FastAPI serves index.html at / (requires login)."""

    @pytest.fixture
    def authed_client(self):
        """TestClient with a valid session cookie."""
        token = create_session_token("testuser", config_module.settings.secret_key)
        with TestClient(app, base_url="https://testserver") as client:
            client.cookies.set("frontdoor_session", token)
            yield client

    def test_root_serves_html(self, authed_client):
        """GET / must return the HTML file."""
        resp = authed_client.get("/")
        assert resp.status_code == 200
        assert "text/html" in resp.headers.get("content-type", "")
        assert "<!DOCTYPE html>" in resp.text

    def test_root_contains_preact_import(self, authed_client):
        """Served HTML must contain Preact+HTM import."""
        resp = authed_client.get("/")
        assert "esm.sh/htm/preact/standalone" in resp.text
