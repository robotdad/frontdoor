"""
Tests for web-app-setup SKILL.md required content.

These tests verify that SKILL.md contains all required sections and commands
as specified in the task spec. Run BEFORE implementing changes to confirm
they fail, then run AFTER to confirm they pass.
"""
import pathlib

SKILL_PATH = pathlib.Path(__file__).parent / "SKILL.md"


def read_skill() -> str:
    return SKILL_PATH.read_text()


# --------------------------------------------------------------------------- #
# Change 1: TLS certs section (lines 51-65 replacement)
# --------------------------------------------------------------------------- #

def test_tls_section_heading_no_tailscale_qualifier():
    """Section heading should be plain '### TLS certs absent' without the
    '*(Tailscale only...)' qualifier."""
    content = read_skill()
    assert "### TLS certs absent" in content
    # Old heading had the Tailscale-only qualifier — should be gone
    assert "*(Tailscale only" not in content


def test_tls_tailscale_certs_option_present():
    """Tailscale cert option (preferred, paid plan) must be present with the
    full `tailscale cert` commands and /etc/ssl/tailscale/ path."""
    content = read_skill()
    assert "tailscale cert" in content
    assert "/etc/ssl/tailscale/" in content


def test_tls_self_signed_openssl_command_present():
    """Self-signed cert option must include a full `openssl req -x509` command."""
    content = read_skill()
    assert "openssl req -x509" in content


def test_tls_self_signed_path_present():
    """Self-signed certs should use /etc/ssl/self-signed/ path."""
    content = read_skill()
    assert "/etc/ssl/self-signed/" in content


def test_tls_http_fallback_option_present():
    """No-certs HTTP fallback option must be mentioned (WireGuard context)."""
    content = read_skill()
    # The section should mention HTTP fallback when no certs are available
    lower = content.lower()
    assert "http fallback" in lower or "no certs" in lower or "wireguard" in lower


# --------------------------------------------------------------------------- #
# Change 2: Phase 2c Caddy snippet (lines 152-173 replacement)
# --------------------------------------------------------------------------- #

def test_caddy_snippet_cert_path_variable():
    """Caddy snippet must use $CERT_PATH variable for cert file path."""
    content = read_skill()
    assert "$CERT_PATH" in content


def test_caddy_snippet_key_path_variable():
    """Caddy snippet must use $KEY_PATH variable for key file path."""
    content = read_skill()
    assert "$KEY_PATH" in content


def test_caddy_snippet_fqdn_hostname_f_fallback():
    """FQDN detection must include `hostname -f` as a fallback after Tailscale."""
    content = read_skill()
    assert "hostname -f" in content


def test_caddy_snippet_tailscale_fqdn_detection():
    """FQDN detection still includes Tailscale-based detection as primary."""
    content = read_skill()
    assert "tailscale status" in content


# --------------------------------------------------------------------------- #
# Change 3: New section 3f (after line 414)
# --------------------------------------------------------------------------- #

def test_section_3f_exists():
    """New section '3f. Behind Frontdoor — App Hosting Pattern' must exist."""
    content = read_skill()
    assert "3f" in content
    assert "Behind Frontdoor" in content or "behind frontdoor" in content.lower()


def test_section_3f_bind_localhost():
    """Section 3f must mention binding to localhost only."""
    content = read_skill()
    # The section should describe binding to localhost
    assert "localhost" in content
    # Specifically in the 3f context — check it appears after 3e content
    idx_3f = content.find("3f")
    assert idx_3f != -1
    idx_localhost_after_3f = content.find("localhost", idx_3f)
    assert idx_localhost_after_3f != -1


def test_section_3f_no_app_level_tls():
    """Section 3f must state no app-level TLS."""
    content = read_skill()
    idx_3f = content.find("3f")
    assert idx_3f != -1
    section_content = content[idx_3f:]
    assert "tls" in section_content.lower()


def test_section_3f_x_authenticated_user_header():
    """Section 3f must mention X-Authenticated-User header."""
    content = read_skill()
    idx_3f = content.find("3f")
    assert idx_3f != -1
    section_content = content[idx_3f:]
    assert "X-Authenticated-User" in section_content


def test_section_3f_amplifierd_trust_proxy_auth():
    """Section 3f must include AMPLIFIERD_TRUST_PROXY_AUTH=true for amplifierd."""
    content = read_skill()
    assert "AMPLIFIERD_TRUST_PROXY_AUTH=true" in content


def test_section_3f_appears_after_3e():
    """Section 3f must appear after section 3e."""
    content = read_skill()
    idx_3e = content.find("### 3e.")
    idx_3f = content.find("### 3f.")
    assert idx_3e != -1, "Section 3e must exist"
    assert idx_3f != -1, "Section 3f must exist"
    assert idx_3f > idx_3e, "Section 3f must appear after section 3e"
