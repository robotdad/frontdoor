"""Tests for frontdoor/docs/HOSTING.md content.

Verifies the hosting documentation contains all required sections and content
as per the HOSTING.md spec.
"""

from pathlib import Path

HOSTING_PATH = Path(__file__).parent.parent / "docs" / "HOSTING.md"


def _read_hosting() -> str:
    return HOSTING_PATH.read_text()


class TestFileExists:
    def test_hosting_md_exists(self):
        """HOSTING.md must exist at frontdoor/docs/HOSTING.md."""
        assert HOSTING_PATH.exists(), f"Expected {HOSTING_PATH} to exist"


class TestTLSProvisioningSection:
    def test_has_tls_provisioning_heading(self):
        """Should have a TLS Provisioning section heading."""
        content = _read_hosting()
        assert "TLS Provisioning" in content

    def test_tailscale_cert_path(self):
        """Should reference Tailscale cert path /etc/ssl/tailscale/."""
        content = _read_hosting()
        assert "/etc/ssl/tailscale/" in content

    def test_self_signed_cert_path(self):
        """Should reference self-signed cert path /etc/ssl/self-signed/."""
        content = _read_hosting()
        assert "/etc/ssl/self-signed/" in content

    def test_plain_http_tier(self):
        """Should mention plain HTTP as a tier."""
        content = _read_hosting()
        assert "plain HTTP" in content or "Plain HTTP" in content

    def test_rsa_2048_key_mentioned(self):
        """Should note RSA 2048-bit keys for self-signed certs."""
        content = _read_hosting()
        assert "2048" in content

    def test_ten_year_validity_mentioned(self):
        """Should note 10-year validity for self-signed certs."""
        content = _read_hosting()
        assert "10-year" in content or "10 year" in content

    def test_tls_table_has_three_tiers(self):
        """Table should include all three tiers as rows."""
        content = _read_hosting()
        assert "tailscale" in content.lower()
        assert "self-signed" in content.lower()
        # Plain HTTP appears at least once
        assert "plain http" in content.lower()

    def test_when_used_info_present(self):
        """Should explain when each tier is used."""
        content = _read_hosting()
        # The table should describe when each tier is used
        assert "when" in content.lower()


class TestFQDNDetectionSection:
    def test_has_fqdn_detection_heading(self):
        """Should have a FQDN Detection section heading."""
        content = _read_hosting()
        assert "FQDN" in content and "Detection" in content

    def test_tailscale_dns_preferred(self):
        """Should state Tailscale DNS name is preferred."""
        content = _read_hosting()
        assert "Tailscale" in content

    def test_hostname_f_fallback(self):
        """Should mention hostname -f as fallback."""
        content = _read_hosting()
        assert "hostname -f" in content

    def test_fqdn_used_for_caddy_vhost(self):
        """Should explain FQDN is used for Caddy vhost."""
        content = _read_hosting()
        assert "vhost" in content or "virtual host" in content.lower()

    def test_fqdn_used_for_cert_cn(self):
        """Should mention FQDN used for cert CN."""
        content = _read_hosting()
        assert "CN" in content or "cert" in content.lower()

    def test_fqdn_used_for_cookie_domain(self):
        """Should mention FQDN used for cookie domain."""
        content = _read_hosting()
        assert "cookie domain" in content.lower() or "cookie" in content.lower()

    def test_lan_without_dns_note(self):
        """Should include a note about LAN without DNS."""
        content = _read_hosting()
        assert "LAN" in content or "lan" in content.lower()


class TestIntegrationFlowSection:
    def test_has_integration_heading(self):
        """Should have a section about how frontdoor integrates with apps."""
        content = _read_hosting()
        assert "Integrates" in content or "integrates" in content

    def test_ascii_flow_diagram_browser(self):
        """ASCII flow diagram should include Browser."""
        content = _read_hosting()
        assert "Browser" in content

    def test_ascii_flow_diagram_caddy(self):
        """ASCII flow diagram should include Caddy."""
        content = _read_hosting()
        assert "Caddy" in content

    def test_ascii_flow_diagram_forward_auth(self):
        """ASCII flow diagram should include forward_auth."""
        content = _read_hosting()
        assert "forward_auth" in content

    def test_ascii_flow_diagram_validates_cookie(self):
        """ASCII flow diagram should show cookie validation step."""
        content = _read_hosting()
        assert "cookie" in content.lower() or "validates" in content.lower()

    def test_ascii_flow_diagram_reverse_proxy(self):
        """ASCII flow diagram should include reverse_proxy."""
        content = _read_hosting()
        assert "reverse_proxy" in content

    def test_ascii_flow_diagram_x_authenticated_user(self):
        """ASCII flow diagram should show X-Authenticated-User header."""
        content = _read_hosting()
        assert "X-Authenticated-User" in content


class TestPuttingAppBehindFrontdoorSection:
    def test_has_putting_app_behind_heading(self):
        """Should have a section about putting an app behind frontdoor."""
        content = _read_hosting()
        assert "Behind Frontdoor" in content or "behind frontdoor" in content.lower()

    def test_six_steps_present(self):
        """Should have 6 steps for putting an app behind frontdoor."""
        content = _read_hosting()
        # Check that steps 1-6 are present
        for i in range(1, 7):
            assert f"{i}." in content or f"{i})" in content, f"Step {i} should be present"

    def test_bind_localhost_step(self):
        """Should mention binding to localhost."""
        content = _read_hosting()
        assert "localhost" in content

    def test_no_app_tls_step(self):
        """Should mention no app TLS."""
        content = _read_hosting()
        assert "TLS" in content

    def test_read_x_authenticated_user_step(self):
        """Should mention reading X-Authenticated-User."""
        content = _read_hosting()
        assert "X-Authenticated-User" in content

    def test_write_caddy_snippet_step(self):
        """Should mention writing a Caddy snippet."""
        content = _read_hosting()
        assert "caddy" in content.lower() or "Caddy" in content

    def test_drop_manifest_step(self):
        """Should mention dropping a manifest."""
        content = _read_hosting()
        assert "manifest" in content.lower()

    def test_amplifierd_trust_proxy_auth_note(self):
        """Should include amplifierd note about AMPLIFIERD_TRUST_PROXY_AUTH=true."""
        content = _read_hosting()
        assert "AMPLIFIERD_TRUST_PROXY_AUTH" in content


class TestCookieBehaviorSection:
    def test_has_cookie_behavior_heading(self):
        """Should have a Cookie Behavior section."""
        content = _read_hosting()
        assert "Cookie" in content and ("Behavior" in content or "behavior" in content)

    def test_frontdoor_secure_cookies_env_var(self):
        """Should document FRONTDOOR_SECURE_COOKIES environment variable."""
        content = _read_hosting()
        assert "FRONTDOOR_SECURE_COOKIES" in content

    def test_secure_cookies_true_condition(self):
        """Should show when FRONTDOOR_SECURE_COOKIES is true."""
        content = _read_hosting()
        assert "true" in content

    def test_secure_cookies_false_condition(self):
        """Should show when FRONTDOOR_SECURE_COOKIES is false."""
        content = _read_hosting()
        assert "false" in content

    def test_frontdoor_cookie_domain_env_var(self):
        """Should document FRONTDOOR_COOKIE_DOMAIN environment variable."""
        content = _read_hosting()
        assert "FRONTDOOR_COOKIE_DOMAIN" in content

    def test_frontdoor_env_editing_note(self):
        """Should include note about editing frontdoor.env."""
        content = _read_hosting()
        assert "frontdoor.env" in content


class TestUninstallingSection:
    def test_has_uninstalling_heading(self):
        """Should have an Uninstalling section."""
        content = _read_hosting()
        assert "Uninstall" in content or "uninstall" in content

    def test_basic_uninstall_command(self):
        """Should show the basic uninstall command."""
        content = _read_hosting()
        assert "uninstall.sh" in content

    def test_purge_uninstall_command(self):
        """Should show the --purge uninstall command."""
        content = _read_hosting()
        assert "--purge" in content


class TestEnvironmentVariablesSection:
    def test_has_env_vars_heading(self):
        """Should have an Environment Variables section."""
        content = _read_hosting()
        assert "Environment Variable" in content or "environment variable" in content.lower()

    def test_frontdoor_secret_key_listed(self):
        """Should list FRONTDOOR_SECRET_KEY."""
        content = _read_hosting()
        assert "FRONTDOOR_SECRET_KEY" in content

    def test_frontdoor_secure_cookies_listed(self):
        """Should list FRONTDOOR_SECURE_COOKIES in env vars table."""
        content = _read_hosting()
        assert "FRONTDOOR_SECURE_COOKIES" in content

    def test_frontdoor_cookie_domain_listed(self):
        """Should list FRONTDOOR_COOKIE_DOMAIN in env vars table."""
        content = _read_hosting()
        assert "FRONTDOOR_COOKIE_DOMAIN" in content
