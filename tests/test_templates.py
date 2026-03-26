"""
Tests for frontdoor/templates/ — deployment template files.

These tests verify that each template file:
  - Exists in the correct location
  - Contains the required APPNAME_* / APP_* placeholders
  - Contains the required directives per the spec
"""

import os
import pytest

TEMPLATES_DIR = os.path.join(os.path.dirname(__file__), "..", "templates")


def template_path(filename: str) -> str:
    return os.path.join(TEMPLATES_DIR, filename)


def read_template(filename: str) -> str:
    with open(template_path(filename)) as f:
        return f.read()


# ---------------------------------------------------------------------------
# File existence
# ---------------------------------------------------------------------------


class TestTemplateFilesExist:
    def test_templates_directory_exists(self):
        assert os.path.isdir(TEMPLATES_DIR), (
            f"templates/ directory not found at {TEMPLATES_DIR}"
        )

    def test_caddy_template_exists(self):
        assert os.path.exists(template_path("app.caddy.template")), (
            "app.caddy.template not found in templates/"
        )

    def test_service_template_exists(self):
        assert os.path.exists(template_path("app.service.template")), (
            "app.service.template not found in templates/"
        )

    def test_install_sh_template_exists(self):
        assert os.path.exists(template_path("install.sh.template")), (
            "install.sh.template not found in templates/"
        )

    def test_frontdoor_json_template_exists(self):
        assert os.path.exists(template_path("frontdoor.json.template")), (
            "frontdoor.json.template not found in templates/"
        )

    def test_signout_link_template_exists(self):
        assert os.path.exists(template_path("signout-link.html.template")), (
            "signout-link.html.template not found in templates/"
        )


# ---------------------------------------------------------------------------
# app.caddy.template
# ---------------------------------------------------------------------------


class TestCaddyTemplate:
    @pytest.fixture(scope="class")
    def content(self):
        return read_template("app.caddy.template")

    def test_has_appname_fqdn_placeholder(self, content):
        assert "APPNAME_FQDN" in content

    def test_has_appname_port_placeholder(self, content):
        assert "APPNAME_PORT" in content

    def test_has_tls_directive(self, content):
        assert "tls" in content

    def test_has_cert_path_placeholder(self, content):
        assert "CERT_PATH" in content

    def test_has_key_path_placeholder(self, content):
        assert "KEY_PATH" in content

    def test_has_forward_auth_directive(self, content):
        assert "forward_auth" in content

    def test_forward_auth_points_to_frontdoor_port(self, content):
        assert "localhost:8420" in content

    def test_forward_auth_has_validate_uri(self, content):
        assert "/api/auth/validate" in content

    def test_forward_auth_copies_authenticated_user_header(self, content):
        assert "X-Authenticated-User" in content

    def test_has_reverse_proxy_directive(self, content):
        assert "reverse_proxy" in content

    def test_reverse_proxy_uses_internal_port_placeholder(self, content):
        assert "APPNAME_INTERNAL_PORT" in content


# ---------------------------------------------------------------------------
# app.service.template
# ---------------------------------------------------------------------------


class TestServiceTemplate:
    @pytest.fixture(scope="class")
    def content(self):
        return read_template("app.service.template")

    def test_has_unit_section(self, content):
        assert "[Unit]" in content

    def test_has_service_section(self, content):
        assert "[Service]" in content

    def test_has_install_section(self, content):
        assert "[Install]" in content

    def test_description_placeholder(self, content):
        assert "APPNAME_DESCRIPTION" in content

    def test_after_network_target(self, content):
        assert "After=network.target" in content

    def test_after_tailscaled(self, content):
        assert "tailscaled.service" in content

    def test_wants_tailscaled(self, content):
        assert "Wants=tailscaled.service" in content

    def test_type_simple(self, content):
        assert "Type=simple" in content

    def test_user_placeholder(self, content):
        assert "User=APPNAME_USER" in content

    def test_working_directory_placeholder(self, content):
        assert "WorkingDirectory=APPNAME_INSTALL_DIR" in content

    def test_execstart_uses_uvicorn(self, content):
        assert "uvicorn" in content

    def test_execstart_has_module_placeholder(self, content):
        assert "APPNAME_MODULE" in content

    def test_execstart_uses_install_dir_venv(self, content):
        assert "APPNAME_INSTALL_DIR/.venv/bin/uvicorn" in content

    def test_execstart_binds_localhost(self, content):
        assert "--host 127.0.0.1" in content

    def test_execstart_internal_port_placeholder(self, content):
        assert "APPNAME_INTERNAL_PORT" in content

    def test_restart_always(self, content):
        assert "Restart=always" in content

    def test_restart_sec_5(self, content):
        assert "RestartSec=5" in content

    def test_wanted_by_multi_user(self, content):
        assert "WantedBy=multi-user.target" in content


# ---------------------------------------------------------------------------
# install.sh.template
# ---------------------------------------------------------------------------


class TestInstallShTemplate:
    @pytest.fixture(scope="class")
    def content(self):
        return read_template("install.sh.template")

    def test_has_bash_shebang(self, content):
        assert content.startswith("#!/bin/bash") or "#!/bin/bash" in content[:30]

    def test_has_display_name_placeholder(self, content):
        assert "APPNAME_DISPLAY_NAME" in content

    def test_has_slug_placeholder(self, content):
        assert "APPNAME_SLUG" in content

    def test_has_internal_port_placeholder(self, content):
        assert "APPNAME_INTERNAL_PORT" in content

    def test_has_port_placeholder(self, content):
        assert "APPNAME_PORT" in content

    def test_has_module_placeholder(self, content):
        assert "APPNAME_MODULE" in content

    def test_has_environment_detection(self, content):
        # Should detect user / environment
        assert "SUDO_USER" in content or "whoami" in content

    def test_has_tailscale_fqdn_detection(self, content):
        assert "tailscale" in content
        assert "FQDN" in content

    def test_has_rsync_app_install(self, content):
        assert "rsync" in content

    def test_has_venv_creation(self, content):
        assert "python3 -m venv" in content or ".venv" in content

    def test_has_pip_install(self, content):
        assert "pip install" in content or ".venv/bin/pip" in content

    def test_has_caddy_snippet_forward_auth(self, content):
        assert "forward_auth" in content

    def test_handles_https_variant(self, content):
        assert "HTTPS" in content
        assert "https" in content.lower() or "tls" in content

    def test_handles_http_variant(self, content):
        assert "http://" in content or "HTTP" in content

    def test_has_systemd_unit_via_sed(self, content):
        assert "sed" in content

    def test_has_manifest_copy_to_frontdoor(self, content):
        assert "/opt/frontdoor/manifests" in content

    def test_has_enable_and_start_services(self, content):
        assert "systemctl enable" in content
        assert "systemctl" in content and ("restart" in content or "start" in content)

    def test_references_ports_py(self, content):
        # The install script template should reference ports.py for port allocation guidance
        assert "ports.py" in content

    def test_has_bash_syntax_check(self):
        """Template must pass bash -n syntax check."""
        import subprocess

        # We need to temporarily strip APPNAME_ placeholders for syntax checking
        # OR just check that it at least has valid bash structure
        # For a template with placeholders, we check via a looser check.
        # The template file should at minimum be valid bash ignoring the placeholders.
        path = template_path("install.sh.template")
        result = subprocess.run(
            ["bash", "-n", path],
            capture_output=True,
            text=True,
        )
        assert result.returncode == 0, (
            f"install.sh.template failed bash syntax check:\n{result.stderr}"
        )


# ---------------------------------------------------------------------------
# frontdoor.json.template
# ---------------------------------------------------------------------------


class TestFrontdoorJsonTemplate:
    @pytest.fixture(scope="class")
    def content(self):
        return read_template("frontdoor.json.template")

    def test_has_app_display_name_field(self, content):
        assert "APP_DISPLAY_NAME" in content

    def test_has_app_description_field(self, content):
        assert "APP_DESCRIPTION" in content

    def test_has_app_icon_field(self, content):
        assert "APP_ICON" in content

    def test_looks_like_json_structure(self, content):
        # Should have curly braces and key/value pairs
        assert "{" in content
        assert "}" in content
        assert ":" in content

    def test_uses_name_key_not_display_name(self, content):
        # Spec requires "name" as the key, not "display_name"
        assert '"name"' in content
        assert '"display_name"' not in content


# ---------------------------------------------------------------------------
# signout-link.html.template
# ---------------------------------------------------------------------------


class TestSignoutLinkTemplate:
    @pytest.fixture(scope="class")
    def content(self):
        return read_template("signout-link.html.template")

    def test_has_html_form(self, content):
        assert "<form" in content

    def test_form_posts_to_logout_endpoint(self, content):
        assert "/api/auth/logout" in content

    def test_form_uses_post_method(self, content):
        assert 'method="post"' in content.lower() or "POST" in content

    def test_has_frontdoor_fqdn_placeholder(self, content):
        assert "FRONTDOOR_FQDN" in content

    def test_has_submit_button(self, content):
        assert "<button" in content or 'type="submit"' in content

    def test_has_comment_explaining_signout(self, content):
        # Should have a comment explaining it signs out of all apps
        assert "<!--" in content
        assert "sign" in content.lower() or "logout" in content.lower()

    def test_form_method_is_uppercase_POST(self, content):
        # Spec requires method="POST" (uppercase)
        assert 'method="POST"' in content

    def test_form_has_display_inline_style(self, content):
        # Spec requires style="display:inline"
        assert 'style="display:inline"' in content

    def test_button_has_signout_link_class(self, content):
        # Spec requires class="signout-link" on the button
        assert 'class="signout-link"' in content

    def test_button_text_is_Sign_Out(self, content):
        # Spec requires button text "Sign Out" (capital O)
        assert "Sign Out" in content
