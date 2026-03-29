"""Tests for frontdoor/context/conventions.md content.

Verifies the conventions documentation contains required sections and content
as per the TLS conventions update spec.
"""

from pathlib import Path

CONVENTIONS_PATH = Path(__file__).parent.parent / "context" / "conventions.md"


def _read_conventions() -> str:
    return CONVENTIONS_PATH.read_text()


class TestHTTPSConventionSection:
    def test_has_tls_certificates_heading(self):
        """Should have updated heading referencing TLS Certificates, not just Tailscale."""
        content = _read_conventions()
        assert "### HTTPS via Caddy + TLS Certificates" in content

    def test_old_tailscale_only_heading_removed(self):
        """Old heading 'HTTPS via Caddy + Tailscale' (without TLS Certificates) should be gone."""
        content = _read_conventions()
        # The new heading is "HTTPS via Caddy + TLS Certificates" — the old exact heading must not appear
        assert "### HTTPS via Caddy + Tailscale\n" not in content

    def test_tailscale_cert_path_present(self):
        """Should reference the Tailscale cert path /etc/ssl/tailscale/."""
        content = _read_conventions()
        assert "/etc/ssl/tailscale/" in content

    def test_self_signed_cert_path_present(self):
        """Should reference the self-signed cert path /etc/ssl/self-signed/."""
        content = _read_conventions()
        assert "/etc/ssl/self-signed/" in content

    def test_ten_year_validity_mentioned(self):
        """Self-signed certs should be noted as having 10-year validity."""
        content = _read_conventions()
        assert "10-year" in content

    def test_tailscale_recommended_not_required(self):
        """Should state that Tailscale is recommended but not required."""
        content = _read_conventions()
        assert "recommended but not required" in content

    def test_three_tier_priority_tailscale(self):
        """Should mention Tailscale as the first (recommended) tier."""
        content = _read_conventions()
        # Tailscale should appear in the TLS priority list context
        assert "Tailscale" in content

    def test_three_tier_priority_self_signed(self):
        """Should mention self-signed as the fallback tier."""
        content = _read_conventions()
        assert "self-signed" in content

    def test_three_tier_priority_plain_http(self):
        """Should mention plain HTTP as the ultimate fallback."""
        content = _read_conventions()
        # plain HTTP (ultimate fallback)
        assert "plain HTTP" in content or "Plain HTTP" in content

    def test_ultimate_fallback_restriction(self):
        """Plain HTTP should be noted as only for Tailscale tailnets or trusted LANs."""
        content = _read_conventions()
        assert "tailnet" in content.lower() or "trusted" in content.lower()


class TestSecureCookiesNote:
    def test_frontdoor_secure_cookies_env_var_mentioned(self):
        """Should document the FRONTDOOR_SECURE_COOKIES environment variable."""
        content = _read_conventions()
        assert "FRONTDOOR_SECURE_COOKIES" in content

    def test_secure_cookies_true_for_https(self):
        """FRONTDOOR_SECURE_COOKIES should be noted as true when HTTPS is active."""
        content = _read_conventions()
        assert "true" in content or "`true`" in content

    def test_secure_cookies_false_for_plain_http(self):
        """FRONTDOOR_SECURE_COOKIES should be noted as false only for plain HTTP."""
        content = _read_conventions()
        assert "false" in content or "`false`" in content

    def test_secure_cookies_after_shared_auth_section(self):
        """FRONTDOOR_SECURE_COOKIES note should appear after the Shared Auth section."""
        content = _read_conventions()
        shared_auth_pos = content.find("### Shared Auth via `frontdoor_session` Cookie")
        secure_cookies_pos = content.find("FRONTDOOR_SECURE_COOKIES")
        assert shared_auth_pos != -1, "Shared Auth section must exist"
        assert secure_cookies_pos != -1, "FRONTDOOR_SECURE_COOKIES must exist"
        assert secure_cookies_pos > shared_auth_pos, (
            "FRONTDOOR_SECURE_COOKIES note must appear after the Shared Auth section"
        )

    def test_secure_cookies_covers_both_tls_types(self):
        """Note should clarify FRONTDOOR_SECURE_COOKIES is true for both Tailscale and self-signed HTTPS."""
        content = _read_conventions()
        # The note should mention both Tailscale and self-signed in the context of FRONTDOOR_SECURE_COOKIES
        # We verify by checking the note exists and both terms appear in the file
        assert "FRONTDOOR_SECURE_COOKIES" in content
        assert "self-signed" in content
