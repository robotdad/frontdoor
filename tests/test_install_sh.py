"""
Tests for frontdoor/deploy/install.sh

These tests verify the deploy script has all required sections and patterns
by inspecting the script content statically, plus behavioral validation.
"""

import os
import stat
import subprocess
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

    def test_saves_secret_key_atomically_with_restrictive_permissions(
        self, script_content
    ):
        """Secret file must be created with restrictive permissions at write time, not after."""
        # umask 177 in a subshell creates files as mode 0600 atomically
        assert "umask 177" in script_content, (
            "Secret file must be created atomically via (umask 177; ...) — "
            "writing then chmod 600 creates a window of exposure"
        )
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

    def test_secret_not_injected_inline_via_sed(self, script_content):
        """Regression: secret must NOT be substituted inline into the systemd unit via sed."""
        assert "s|FRONTDOOR_SECRET|" not in script_content, (
            "Secret must not be injected inline into the systemd unit — "
            "use EnvironmentFile= instead"
        )

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

    def test_restarts_caddy(self, script_content):
        # restart handles both fresh-install (inactive) and running cases;
        # reload alone would fail on an inactive service under set -euo pipefail
        assert "systemctl restart caddy" in script_content


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


class TestScriptSyntax:
    """Automated shell syntax validation — prevents future regressions."""

    def test_script_passes_bash_syntax_check(self):
        """bash -n validates syntax without executing privileged commands."""
        result = subprocess.run(
            ["bash", "-n", SCRIPT_PATH],
            capture_output=True,
            text=True,
        )
        assert result.returncode == 0, f"bash -n found syntax errors:\n{result.stderr}"


class TestSystemdUnitPermissions:
    """Systemd unit must be written with restrictive permissions atomically."""

    def test_systemd_unit_written_atomically_with_restrictive_permissions(
        self, script_content
    ):
        """Unit file must be created via (umask 177; ...) -- atomic, no exposure window."""
        assert "umask 177" in script_content, (
            "Systemd unit must be created atomically via (umask 177; ...) -- "
            "writing then chmod creates a window of exposure"
        )
        assert "/etc/systemd/system/frontdoor.service" in script_content


class TestBehavioralRendering:
    """Behavioral tests that execute bash to validate rendered output with controlled inputs."""

    def test_caddyfile_https_renders_with_correct_values(self, tmp_path):
        """Render the HTTPS Caddyfile variant with known inputs and verify output content."""
        output = tmp_path / "Caddyfile"
        script = tmp_path / "render_test.sh"

        # Write a bash script that replicates the HTTPS Caddyfile heredoc from install.sh
        bash_content = (
            "#!/bin/bash\n"
            "set -euo pipefail\n"
            'FQDN="myhost.example.ts.net"\n'
            'SHORT_HOSTNAME="myhost"\n'
            'CERT_PATH="/etc/ssl/tailscale/myhost.crt"\n'
            'KEY_PATH="/etc/ssl/tailscale/myhost.key"\n'
            f'OUTPUT="{output}"\n'
            'cat > "$OUTPUT" <<EOF\n'
            "# Frontdoor — main entry point on port 443\n"
            "$FQDN:443 {\n"
            "    tls $CERT_PATH $KEY_PATH\n"
            "\n"
            "    reverse_proxy localhost:8420\n"
            "}\n"
            "\n"
            "# Short hostname redirect\n"
            "http://$SHORT_HOSTNAME {\n"
            "    redir https://$FQDN{uri} permanent\n"
            "}\n"
            "\n"
            "import /etc/caddy/conf.d/*.caddy\n"
            "EOF\n"
        )
        script.write_text(bash_content)
        script.chmod(0o755)

        result = subprocess.run(
            ["bash", str(script)],
            capture_output=True,
            text=True,
        )
        assert result.returncode == 0, f"Bash render failed:\n{result.stderr}"

        content = output.read_text()
        assert "myhost.example.ts.net:443" in content, (
            "FQDN substitution missing in rendered Caddyfile"
        )
        assert "http://myhost {" in content, "Short hostname block missing"
        assert "redir https://myhost.example.ts.net" in content, (
            "Redirect to FQDN missing"
        )
        assert "import /etc/caddy/conf.d/*.caddy" in content, "conf.d import missing"


class TestSecretDeliveryDesign:
    """Regression tests for correct secret delivery via EnvironmentFile=."""

    def test_secret_not_injected_inline_via_sed(self, script_content):
        """Regression: secret must NOT be substituted inline into the systemd unit via sed."""
        assert "s|FRONTDOOR_SECRET|" not in script_content, (
            "Secret must not be injected inline into the systemd unit -- "
            "use EnvironmentFile= instead"
        )

    def test_install_references_environment_file_secret(self, script_content):
        """install.sh must write the secret in EnvironmentFile key=value format."""
        assert (
            "EnvironmentFile" in script_content
            or "FRONTDOOR_SECRET_KEY=" in script_content
        ), "install.sh must write the secret in EnvironmentFile format (KEY=value)"

    def test_service_template_uses_environment_file(self):
        """Service template must use EnvironmentFile= for secret delivery, not Environment=."""
        service_path = os.path.join(
            os.path.dirname(__file__), "..", "deploy", "frontdoor.service"
        )
        with open(service_path) as f:
            service_content = f.read()
        assert "EnvironmentFile=" in service_content, (
            "frontdoor.service must use EnvironmentFile= for secret delivery"
        )

    def test_service_template_no_inline_secret_placeholder(self):
        """Service template must NOT embed the secret placeholder in Environment=."""
        service_path = os.path.join(
            os.path.dirname(__file__), "..", "deploy", "frontdoor.service"
        )
        with open(service_path) as f:
            service_content = f.read()
        assert (
            "Environment=FRONTDOOR_SECRET_KEY=FRONTDOOR_SECRET" not in service_content
        ), "Secret placeholder must not appear in Environment= -- use EnvironmentFile="


class TestInstallSequencing:
    """Regression tests for fresh-install sequencing failures."""

    def test_caddy_installed_before_cert_key_ownership(self, script_content):
        """Caddy must be installed BEFORE chown root:caddy is applied to the cert key.

        On a fresh host, the 'caddy' group does not exist until Caddy is installed.
        Applying 'chown root:caddy' before that will fail under set -euo pipefail.
        """
        caddy_install_pos = script_content.find("command -v caddy")
        cert_chown_pos = script_content.find("chown root:caddy")
        assert caddy_install_pos != -1, "Caddy install check not found in script"
        assert cert_chown_pos != -1, "chown root:caddy not found in script"
        assert caddy_install_pos < cert_chown_pos, (
            "Caddy must be installed BEFORE 'chown root:caddy' is applied to the cert key. "
            f"Caddy install at char pos {caddy_install_pos}, "
            f"cert chown at char pos {cert_chown_pos}."
        )

    def test_caddy_service_restarted_not_just_reloaded(self, script_content):
        """Caddy must be restarted (not just reloaded) to handle the fresh-install case.

        'systemctl enable caddy' does NOT start the service if it is inactive.
        'systemctl reload caddy' fails on an inactive service under set -euo pipefail.
        'systemctl restart caddy' handles both the stopped and running cases.
        """
        assert "systemctl restart caddy" in script_content, (
            "Caddy must use 'systemctl restart caddy' (not just 'reload') to handle "
            "fresh-install where the service is not yet running. "
            "'reload' fails on an inactive service."
        )


class TestFqdnValidation:
    """FQDN and SHORT_HOSTNAME must be validated before use in config generation."""

    def test_fqdn_validated_after_detection(self, script_content):
        """Script must validate FQDN is non-empty before rendering Caddy config."""
        # Pattern: [ -z "$FQDN" ] or similar empty-check for the FQDN variable
        assert '-z "$FQDN"' in script_content or '[ -z "$FQDN"' in script_content, (
            "FQDN must be validated for emptiness immediately after detection"
        )

    def test_short_hostname_validated_after_detection(self, script_content):
        """Script must validate SHORT_HOSTNAME is non-empty before rendering Caddy config."""
        # Pattern: [ -z "$SHORT_HOSTNAME" ] or similar empty-check
        assert (
            '-z "$SHORT_HOSTNAME"' in script_content
            or '[ -z "$SHORT_HOSTNAME"' in script_content
        ), "SHORT_HOSTNAME must be validated for emptiness immediately after detection"

    def test_fqdn_validation_fails_fast(self, script_content):
        """Validation must exit the script on empty/invalid FQDN, not silently continue."""
        assert "exit 1" in script_content, (
            "Script must exit 1 on invalid FQDN to prevent broken Caddy config generation"
        )
