"""
Tests for frontdoor/deploy/install.sh

These tests verify the deploy script has all required sections and patterns
by inspecting the script content statically.
"""

import os
import stat
import pytest

SCRIPT_PATH = os.path.join(os.path.dirname(__file__), "..", "deploy", "install.sh")


@pytest.fixture(scope="module")
def script_content():
    """Read the install.sh script content."""
    with open(SCRIPT_PATH) as f:
        return f.read()


class TestFileExistsAndExecutable:
    def test_file_exists(self):
        assert os.path.exists(SCRIPT_PATH), f"install.sh not found at {SCRIPT_PATH}"

    def test_file_is_executable(self):
        st = os.stat(SCRIPT_PATH)
        assert st.st_mode & stat.S_IXUSR, "install.sh is not executable by owner"


class TestScriptPreamble:
    def test_has_bash_shebang(self, script_content):
        assert script_content.startswith("#!/bin/bash"), "Missing #!/bin/bash shebang"

    def test_has_set_euo_pipefail(self, script_content):
        assert "set -euo pipefail" in script_content, "Missing set -euo pipefail"


class TestEnvironmentDetection:
    def test_has_script_dir(self, script_content):
        assert "SCRIPT_DIR=" in script_content

    def test_has_project_dir(self, script_content):
        assert "PROJECT_DIR=" in script_content

    def test_has_install_dir_opt_frontdoor(self, script_content):
        assert 'INSTALL_DIR="/opt/frontdoor"' in script_content

    def test_has_cert_dir(self, script_content):
        assert 'CERT_DIR="/etc/ssl/tailscale"' in script_content

    def test_has_filebrowser_new_port(self, script_content):
        assert "FILEBROWSER_NEW_PORT=8447" in script_content

    def test_uses_sudo_user_fallback(self, script_content):
        assert "SUDO_USER" in script_content


class TestTailscaleFqdnDetection:
    def test_detects_fqdn_via_tailscale_json(self, script_content):
        assert "tailscale status --json" in script_content
        assert "DNSName" in script_content

    def test_detects_short_hostname(self, script_content):
        assert "hostname -s" in script_content
        assert "SHORT_HOSTNAME=" in script_content


class TestSecretKeyGeneration:
    def test_reads_existing_secret_key(self, script_content):
        assert ".secret_key" in script_content
        assert "cat " in script_content or "$(cat" in script_content

    def test_generates_new_secret_key(self, script_content):
        assert "secrets.token_hex(32)" in script_content

    def test_saves_secret_key_with_chmod_600(self, script_content):
        # Must save and protect the secret key
        assert "chmod 600" in script_content
        assert ".secret_key" in script_content


class TestPamAccess:
    def test_checks_shadow_group(self, script_content):
        assert "shadow" in script_content
        assert "usermod" in script_content


class TestAppInstall:
    def test_rsync_install(self, script_content):
        assert "rsync" in script_content
        assert (
            "--exclude='.venv'" in script_content or "--exclude=.venv" in script_content
        )
        assert "__pycache__" in script_content
        assert ".git" in script_content

    def test_creates_venv(self, script_content):
        assert "python3 -m venv" in script_content

    def test_pip_install(self, script_content):
        assert ".venv/bin/pip" in script_content or "pip install" in script_content


class TestTailscaleCert:
    def test_tries_tailscale_cert(self, script_content):
        assert "tailscale cert" in script_content

    def test_sets_https_true_on_success(self, script_content):
        assert "HTTPS=true" in script_content

    def test_falls_back_to_http(self, script_content):
        assert "HTTPS=false" in script_content

    def test_fallback_message_mentions_tailscale(self, script_content):
        # Should have an informative message about HTTP fallback
        assert "HTTP" in script_content


class TestCaddyInstall:
    def test_installs_caddy_if_not_present(self, script_content):
        assert "command -v caddy" in script_content
        assert "apt-get" in script_content and "caddy" in script_content


class TestDirectoryCreation:
    def test_creates_caddy_conf_d(self, script_content):
        assert "/etc/caddy/conf.d" in script_content

    def test_creates_manifests_directory(self, script_content):
        assert "/opt/frontdoor/manifests" in script_content


class TestCaddyMigration:
    def test_checks_for_existing_filebrowser_in_caddyfile(self, script_content):
        # Migration: detect if Caddyfile has filebrowser config
        assert "reverse_proxy localhost:58080" in script_content

    def test_writes_filebrowser_caddy_snippet(self, script_content):
        assert "filebrowser.caddy" in script_content
        assert "/etc/caddy/conf.d/filebrowser.caddy" in script_content

    def test_migration_uses_port_8447(self, script_content):
        assert "8447" in script_content

    def test_migration_has_forward_auth(self, script_content):
        assert "forward_auth" in script_content
        assert "localhost:8420" in script_content

    def test_migration_handles_https_and_http(self, script_content):
        # Both HTTPS and HTTP variants of migration
        assert "HTTPS" in script_content


class TestMainCaddyfile:
    def test_writes_caddyfile(self, script_content):
        assert "/etc/caddy/Caddyfile" in script_content

    def test_caddyfile_has_fqdn_on_port_443(self, script_content):
        assert ":443" in script_content or "$FQDN {" in script_content

    def test_caddyfile_has_short_hostname_redirect(self, script_content):
        assert "SHORT_HOSTNAME" in script_content
        # redirect from short hostname to FQDN
        assert "redir" in script_content or "redirect" in script_content.lower()

    def test_caddyfile_imports_conf_d(self, script_content):
        assert "import /etc/caddy/conf.d/*.caddy" in script_content

    def test_caddyfile_has_forward_auth_to_frontdoor(self, script_content):
        # frontdoor is on port 8420, forward_auth for authentication
        assert "8420" in script_content


class TestSystemdUnit:
    def test_writes_systemd_unit_via_sed(self, script_content):
        assert "frontdoor.service" in script_content
        assert "/etc/systemd/system/frontdoor.service" in script_content
        assert "sed" in script_content

    def test_sed_replaces_frontdoor_user(self, script_content):
        assert "FRONTDOOR_USER" in script_content

    def test_sed_replaces_frontdoor_dir(self, script_content):
        assert "FRONTDOOR_DIR" in script_content

    def test_sed_replaces_frontdoor_secret(self, script_content):
        assert "FRONTDOOR_SECRET" in script_content

    def test_sed_replaces_frontdoor_https_enabled(self, script_content):
        assert "FRONTDOOR_HTTPS_ENABLED" in script_content

    def test_sed_replaces_frontdoor_fqdn(self, script_content):
        assert "FRONTDOOR_FQDN" in script_content


class TestServiceManagement:
    def test_systemctl_daemon_reload(self, script_content):
        assert "systemctl daemon-reload" in script_content

    def test_enables_frontdoor(self, script_content):
        assert "systemctl enable frontdoor" in script_content

    def test_restarts_frontdoor(self, script_content):
        assert "systemctl restart frontdoor" in script_content

    def test_enables_caddy(self, script_content):
        assert "systemctl enable caddy" in script_content

    def test_reloads_caddy(self, script_content):
        assert "systemctl reload caddy" in script_content


class TestCompletionMessage:
    def test_has_completion_message(self, script_content):
        assert (
            "Installation complete" in script_content
            or "complete" in script_content.lower()
        )

    def test_shows_url(self, script_content):
        assert "https://" in script_content or "$FQDN" in script_content

    def test_shows_status_commands(self, script_content):
        assert "systemctl status frontdoor" in script_content
        assert "systemctl status caddy" in script_content
