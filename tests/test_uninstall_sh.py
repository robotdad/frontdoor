"""
Tests for frontdoor/deploy/uninstall.sh

These tests verify the uninstall script has all required sections and patterns
by inspecting the script content statically, plus syntax validation.
"""

import os
import stat
import subprocess

import pytest

SCRIPT_PATH = os.path.join(os.path.dirname(__file__), "..", "deploy", "uninstall.sh")


@pytest.fixture(scope="module")
def script_content():
    """Read the uninstall.sh script content."""
    with open(SCRIPT_PATH) as f:
        return f.read()


class TestFileExistsAndExecutable:
    def test_file_exists(self):
        assert os.path.exists(SCRIPT_PATH), f"uninstall.sh not found at {SCRIPT_PATH}"

    def test_file_is_executable(self):
        st = os.stat(SCRIPT_PATH)
        assert st.st_mode & stat.S_IXUSR, "uninstall.sh is not executable by owner"


class TestScriptPreamble:
    def test_has_bash_shebang(self, script_content):
        assert script_content.startswith("#!/bin/bash"), "Missing #!/bin/bash shebang"

    def test_has_set_euo_pipefail(self, script_content):
        assert "set -euo pipefail" in script_content, "Missing set -euo pipefail"


class TestVariableDefaults:
    def test_has_install_dir(self, script_content):
        assert 'INSTALL_DIR="/opt/frontdoor"' in script_content, (
            "Missing INSTALL_DIR=/opt/frontdoor"
        )

    def test_has_service_name(self, script_content):
        assert 'SERVICE_NAME="frontdoor"' in script_content, (
            "Missing SERVICE_NAME=frontdoor"
        )

    def test_has_purge_false_default(self, script_content):
        assert "PURGE=false" in script_content, "Missing PURGE=false default"


class TestArgumentParsing:
    def test_has_purge_flag_support(self, script_content):
        assert "--purge" in script_content, "Missing --purge flag support"

    def test_argument_parser_sets_purge_true(self, script_content):
        assert "PURGE=true" in script_content, (
            "Argument parser must set PURGE=true when --purge is given"
        )


class TestStopServiceSection:
    def test_checks_is_active_before_stopping(self, script_content):
        assert "systemctl is-active --quiet" in script_content, (
            "Must check 'systemctl is-active --quiet' before stopping service"
        )

    def test_stops_service(self, script_content):
        assert "systemctl stop" in script_content, "Missing 'systemctl stop'"

    def test_checks_is_enabled_before_disabling(self, script_content):
        assert "systemctl is-enabled --quiet" in script_content, (
            "Must check 'systemctl is-enabled --quiet' before disabling service"
        )

    def test_disables_service(self, script_content):
        assert "systemctl disable" in script_content, "Missing 'systemctl disable'"


class TestRemoveUnitFileSection:
    def test_checks_unit_file_exists(self, script_content):
        assert "/etc/systemd/system/$SERVICE_NAME.service" in script_content, (
            "Must reference /etc/systemd/system/$SERVICE_NAME.service"
        )

    def test_removes_unit_file(self, script_content):
        assert 'rm "/etc/systemd/system/$SERVICE_NAME.service"' in script_content, (
            "Must remove the unit file at /etc/systemd/system/$SERVICE_NAME.service"
        )

    def test_runs_daemon_reload_after_removal(self, script_content):
        assert "systemctl daemon-reload" in script_content, (
            "Must run 'systemctl daemon-reload' after removing unit file"
        )


class TestPurgeSection:
    def test_purge_removes_install_dir(self, script_content):
        assert "rm -rf" in script_content and "$INSTALL_DIR" in script_content, (
            "Purge must remove INSTALL_DIR via rm -rf"
        )

    def test_purge_removes_self_signed_certs_crt(self, script_content):
        assert "/etc/ssl/self-signed/" in script_content, (
            "Purge must reference /etc/ssl/self-signed/ for cert removal"
        )

    def test_purge_removes_self_signed_certs_key(self, script_content):
        # Both .crt and .key must be addressed
        assert "*.key" in script_content or ".key" in script_content, (
            "Purge must remove self-signed *.key files"
        )
        assert "*.crt" in script_content or ".crt" in script_content, (
            "Purge must remove self-signed *.crt files"
        )

    def test_purge_prints_what_is_not_removed(self, script_content):
        # Script must note what is NOT removed (Caddy, Tailscale certs, conf.d snippets)
        assert "Caddy" in script_content or "caddy" in script_content, (
            "Purge section must note Caddy is not removed"
        )

    def test_purge_section_is_conditional(self, script_content):
        # Purge section should only run if PURGE=true
        assert "$PURGE" in script_content or "[ \"$PURGE\"" in script_content, (
            "Purge section must be conditional on PURGE flag"
        )


class TestNoPurgeNote:
    def test_without_purge_prints_note(self, script_content):
        assert "--purge" in script_content, (
            "Script must mention --purge flag in its output/notes"
        )


class TestNegativeRequirements:
    def test_does_not_contain_apt_get_remove(self, script_content):
        assert "apt-get remove" not in script_content, (
            "Script must NOT contain 'apt-get remove'"
        )

    def test_rm_does_not_reference_ssl_tailscale(self, script_content):
        """No rm command should touch /etc/ssl/tailscale (those are Tailscale certs, not ours)."""
        lines = script_content.splitlines()
        for line in lines:
            stripped = line.strip()
            # Skip comment lines
            if stripped.startswith("#"):
                continue
            if "rm" in stripped and "/etc/ssl/tailscale" in stripped:
                pytest.fail(
                    f"rm command must not reference /etc/ssl/tailscale: {line!r}"
                )


class TestScriptSyntax:
    """Automated shell syntax validation."""

    def test_script_passes_bash_syntax_check(self):
        """bash -n validates syntax without executing privileged commands."""
        result = subprocess.run(
            ["bash", "-n", SCRIPT_PATH],
            capture_output=True,
            text=True,
        )
        assert result.returncode == 0, f"bash -n found syntax errors:\n{result.stderr}"
