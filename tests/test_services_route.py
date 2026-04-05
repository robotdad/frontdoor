"""End-to-end integration tests for GET /api/services."""

import json
from unittest.mock import MagicMock, patch

import pytest
from starlette.testclient import TestClient

import frontdoor.config as config_module
from frontdoor.auth import create_session_token
from frontdoor.main import app

# Single ss output line: java process listening on port 9200.
SS_FIXTURE = (
    "tcp   LISTEN 0      128    0.0.0.0:9200      0.0.0.0:*         "
    'users:(("java",pid=5000,fd=10))\n'
)


@pytest.fixture
def service_client(tmp_caddy_dir, tmp_manifest_dir):
    """TestClient wired to fixture Caddy configs and a filebrowser manifest.

    Writes a filebrowser.json manifest into *tmp_manifest_dir*, overrides
    ``config.settings`` to point at the fixture directories, yields a
    ``TestClient``, and restores the original settings on teardown.
    """
    # Write the filebrowser manifest so overlay_manifests can enrich the service.
    (tmp_manifest_dir / "filebrowser.json").write_text(
        json.dumps(
            {
                "name": "File Browser",
                "description": "Browse and manage files",
                "icon": "folder",
            }
        )
    )

    # Persist original settings so we can restore them after the test.
    orig_caddy_main_config = config_module.settings.caddy_main_config
    orig_caddy_conf_d = config_module.settings.caddy_conf_d
    orig_manifest_dir = config_module.settings.manifest_dir

    # Point the live settings at the temporary fixture directories.
    config_module.settings.caddy_main_config = tmp_caddy_dir / "Caddyfile"
    config_module.settings.caddy_conf_d = tmp_caddy_dir / "conf.d"
    config_module.settings.manifest_dir = tmp_manifest_dir

    # Generate a valid session token so the protected /api/services endpoint
    # accepts requests from this test client.
    token = create_session_token("testuser", config_module.settings.secret_key)

    with TestClient(app, base_url="https://testserver") as client:
        client.cookies.set("frontdoor_session", token)
        yield client

    # Restore original settings unconditionally.
    config_module.settings.caddy_main_config = orig_caddy_main_config
    config_module.settings.caddy_conf_d = orig_caddy_conf_d
    config_module.settings.manifest_dir = orig_manifest_dir


def _make_ss_mock(output: str) -> MagicMock:
    """Return a MagicMock that simulates a successful ``subprocess.run`` result."""
    mock_result = MagicMock()
    mock_result.returncode = 0
    mock_result.stdout = output
    return mock_result


class TestGetServices:
    def test_returns_services_and_unregistered(self, service_client):
        """GET /api/services returns HTTP 200 with 'services' and 'unregistered' keys."""
        with (
            patch("socket.create_connection"),
            patch(
                "frontdoor.discovery.subprocess.run",
                return_value=_make_ss_mock(SS_FIXTURE),
            ),
        ):
            resp = service_client.get("/api/services")

        assert resp.status_code == 200
        data = resp.json()
        assert "services" in data
        assert "unregistered" in data

    def test_services_have_required_fields(self, service_client):
        """Each service object contains 'name', 'url', and 'status' in ('up', 'down')."""
        with (
            patch("socket.create_connection"),
            patch(
                "frontdoor.discovery.subprocess.run",
                return_value=_make_ss_mock(SS_FIXTURE),
            ),
        ):
            resp = service_client.get("/api/services")

        services = resp.json()["services"]
        assert len(services) > 0
        for svc in services:
            assert "name" in svc
            assert "url" in svc
            assert "status" in svc
            assert svc["status"] in ("up", "down")

    def test_manifest_overlay_applied(self, service_client):
        """The 'File Browser' service appears with the description from its manifest."""
        with (
            patch("socket.create_connection"),
            patch(
                "frontdoor.discovery.subprocess.run",
                return_value=_make_ss_mock(SS_FIXTURE),
            ),
        ):
            resp = service_client.get("/api/services")

        services = resp.json()["services"]
        names = [s["name"] for s in services]
        assert "File Browser" in names

        fb = next(s for s in services if s["name"] == "File Browser")
        assert fb["description"] == "Browse and manage files"

    def test_tcp_probe_status(self, service_client):
        """Port 8443 up → File Browser='up'; port 8445 down → Dev Machine Monitor='down'."""

        def tcp_side_effect(addr, timeout=1.0):
            _, port = addr
            if port == 8443:
                # Simulate a successful connection (context-manager compatible).
                return MagicMock()
            raise ConnectionRefusedError()

        with (
            patch("socket.create_connection", side_effect=tcp_side_effect),
            patch(
                "frontdoor.discovery.subprocess.run",
                return_value=_make_ss_mock(""),
            ),
        ):
            resp = service_client.get("/api/services")

        assert resp.status_code == 200
        services = resp.json()["services"]

        fb = next(s for s in services if s["name"] == "File Browser")
        dmm = next(s for s in services if s["name"] == "Dev Machine Monitor")

        assert fb["status"] == "up"
        assert dmm["status"] == "down"

    def test_unregistered_processes(self, service_client):
        """Exactly one unregistered process is detected: java on port 9200."""
        with (
            patch("socket.create_connection"),
            patch(
                "frontdoor.discovery.subprocess.run",
                return_value=_make_ss_mock(SS_FIXTURE),
            ),
        ):
            resp = service_client.get("/api/services")

        assert resp.status_code == 200
        unregistered = resp.json()["unregistered"]
        assert len(unregistered) == 1
        assert unregistered[0]["name"] == "java"
        assert unregistered[0]["port"] == 9200

    def test_services_include_systemd_unit(self, service_client):
        """Each service object includes a 'systemd_unit' field (may be null)."""
        from unittest.mock import patch

        with (
            patch("socket.create_connection"),
            patch(
                "frontdoor.routes.services.get_port_pids",
                return_value={8445: 1111, 8443: 2222},
            ),
            patch(
                "frontdoor.routes.services.get_systemd_unit",
                side_effect=lambda pid, **kw: {
                    1111: "dev-machine-monitor.service",
                    2222: "filebrowser.service",
                }.get(pid),
            ),
        ):
            resp = service_client.get("/api/services")

        assert resp.status_code == 200
        services = resp.json()["services"]
        for svc in services:
            assert "systemd_unit" in svc

    def test_frontdoor_excluded(self, service_client):
        """No service URL references port 8420 (frontdoor's own port is always excluded)."""
        with (
            patch("socket.create_connection"),
            patch(
                "frontdoor.discovery.subprocess.run",
                return_value=_make_ss_mock(SS_FIXTURE),
            ),
        ):
            resp = service_client.get("/api/services")

        services = resp.json()["services"]
        for svc in services:
            assert "8420" not in svc["url"]
