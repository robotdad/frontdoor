"""
Tests for frontdoor/bundle.md and frontdoor/README.md

These tests verify the Amplifier bundle definition and project README have
all required sections, content, and structure.
"""

import os
import re

import pytest
import yaml

PROJECT_ROOT = os.path.join(os.path.dirname(__file__), "..")
BUNDLE_MD_PATH = os.path.join(PROJECT_ROOT, "bundle.md")
README_MD_PATH = os.path.join(PROJECT_ROOT, "README.md")


@pytest.fixture(scope="module")
def bundle_content():
    """Read bundle.md content."""
    with open(BUNDLE_MD_PATH) as f:
        return f.read()


@pytest.fixture(scope="module")
def readme_content():
    """Read README.md content."""
    with open(README_MD_PATH) as f:
        return f.read()


@pytest.fixture(scope="module")
def bundle_frontmatter(bundle_content):
    """Parse YAML frontmatter from bundle.md."""
    match = re.match(r"^---\n(.*?)\n---", bundle_content, re.DOTALL)
    assert match, "bundle.md must have YAML frontmatter delimited by ---"
    return yaml.safe_load(match.group(1))


# ─────────────────────────────────────────────────────────────────────────────
# bundle.md tests
# ─────────────────────────────────────────────────────────────────────────────


class TestBundleMdExists:
    def test_bundle_md_exists(self):
        assert os.path.exists(BUNDLE_MD_PATH), f"bundle.md not found at {BUNDLE_MD_PATH}"


class TestBundleMdFrontmatter:
    def test_has_valid_yaml_frontmatter(self, bundle_frontmatter):
        assert bundle_frontmatter is not None

    def test_name_is_frontdoor(self, bundle_frontmatter):
        assert bundle_frontmatter.get("name") == "frontdoor"

    def test_version_is_0_1_0(self, bundle_frontmatter):
        assert str(bundle_frontmatter.get("version")) == "0.1.0"


class TestBundleMdSkills:
    def test_lists_host_infra_discovery_skill(self, bundle_content):
        assert "host-infra-discovery" in bundle_content

    def test_lists_web_app_setup_skill(self, bundle_content):
        assert "web-app-setup" in bundle_content

    def test_host_infra_discovery_has_description(self, bundle_content):
        assert "inventory" in bundle_content.lower() or "discovery" in bundle_content.lower()

    def test_web_app_setup_has_description(self, bundle_content):
        assert "provisioning" in bundle_content.lower() or "setup" in bundle_content.lower()


class TestBundleMdTemplates:
    def test_lists_app_caddy_template(self, bundle_content):
        assert "app.caddy.template" in bundle_content

    def test_lists_app_service_template(self, bundle_content):
        assert "app.service.template" in bundle_content

    def test_lists_install_sh_template(self, bundle_content):
        assert "install.sh.template" in bundle_content

    def test_lists_frontdoor_json_template(self, bundle_content):
        assert "frontdoor.json.template" in bundle_content

    def test_lists_signout_link_html_template(self, bundle_content):
        assert "signout-link.html.template" in bundle_content


class TestBundleMdConventions:
    def test_mentions_https_via_caddy_and_tailscale(self, bundle_content):
        lower = bundle_content.lower()
        assert "caddy" in lower and "tailscale" in lower

    def test_mentions_frontdoor_session_cookie(self, bundle_content):
        assert "frontdoor_session" in bundle_content

    def test_mentions_conf_d_discovery(self, bundle_content):
        assert "conf.d" in bundle_content

    def test_mentions_port_allocation_from_8440(self, bundle_content):
        assert "8440" in bundle_content


class TestBundleMdReservedPorts:
    def test_lists_3000_range(self, bundle_content):
        assert "3000" in bundle_content

    def test_lists_4000_range(self, bundle_content):
        assert "4000" in bundle_content

    def test_lists_4200_range(self, bundle_content):
        assert "4200" in bundle_content

    def test_lists_5000_range(self, bundle_content):
        assert "5000" in bundle_content

    def test_lists_5173_range(self, bundle_content):
        assert "5173" in bundle_content

    def test_lists_8000_range(self, bundle_content):
        assert "8000" in bundle_content

    def test_lists_8080_range(self, bundle_content):
        assert "8080" in bundle_content

    def test_lists_8410_range(self, bundle_content):
        assert "8410" in bundle_content

    def test_lists_8888_range(self, bundle_content):
        assert "8888" in bundle_content

    def test_lists_9090_range(self, bundle_content):
        assert "9090" in bundle_content

    def test_mentions_databases(self, bundle_content):
        assert "database" in bundle_content.lower() or "databases" in bundle_content.lower()


# ─────────────────────────────────────────────────────────────────────────────
# README.md tests
# ─────────────────────────────────────────────────────────────────────────────


class TestReadmeMdExists:
    def test_readme_md_exists(self):
        assert os.path.exists(README_MD_PATH), f"README.md not found at {README_MD_PATH}"


class TestReadmeMdWhatFrontdoorDoes:
    def test_describes_service_discovery(self, readme_content):
        lower = readme_content.lower()
        assert "discover" in lower or "caddy" in lower

    def test_mentions_status_indicators(self, readme_content):
        lower = readme_content.lower()
        # green/red dots or status indicators
        assert "green" in lower or "red" in lower or "status" in lower

    def test_mentions_shared_auth(self, readme_content):
        lower = readme_content.lower()
        assert "auth" in lower or "cookie" in lower

    def test_mentions_unregistered_processes(self, readme_content):
        lower = readme_content.lower()
        assert "unregistered" in lower or "tcp" in lower or "probe" in lower

    def test_mentions_domain_cookie(self, readme_content):
        lower = readme_content.lower()
        assert "cookie" in lower or "domain" in lower


class TestReadmeMdInstall:
    def test_has_install_command(self, readme_content):
        assert "deploy/install.sh" in readme_content

    def test_install_uses_sudo(self, readme_content):
        assert "sudo" in readme_content

    def test_install_mentions_opt_frontdoor(self, readme_content):
        assert "/opt/frontdoor" in readme_content

    def test_install_mentions_conf_d(self, readme_content):
        assert "conf.d" in readme_content

    def test_install_mentions_port_443(self, readme_content):
        assert "443" in readme_content

    def test_install_mentions_manifests(self, readme_content):
        assert "manifests" in readme_content.lower() or "manifests/" in readme_content

    def test_install_mentions_filebrowser(self, readme_content):
        lower = readme_content.lower()
        assert "filebrowser" in lower

    def test_install_mentions_8447(self, readme_content):
        assert "8447" in readme_content


class TestReadmeMdAmplifierBundle:
    def test_mentions_amplifier(self, readme_content):
        lower = readme_content.lower()
        assert "amplifier" in lower

    def test_mentions_bundle(self, readme_content):
        lower = readme_content.lower()
        assert "bundle" in lower

    def test_mentions_skills(self, readme_content):
        lower = readme_content.lower()
        assert "skill" in lower


class TestReadmeMdStatusCommands:
    def test_has_status_commands_section(self, readme_content):
        lower = readme_content.lower()
        assert "status" in lower
        # should have some command reference (systemctl, journalctl, or similar)
        assert (
            "systemctl" in readme_content
            or "journalctl" in readme_content
            or "service" in lower
        )
