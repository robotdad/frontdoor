"""Tests for /api/admin/* endpoints."""

import pytest
from starlette.testclient import TestClient
from unittest.mock import patch

import frontdoor.config as config_module
from frontdoor.main import app
from frontdoor.tokens import create_token


@pytest.fixture
def admin_client(tmp_path):
    """TestClient with temporary tokens file and localhost admin enabled."""
    tokens_file = tmp_path / "tokens.json"
    tokens_file.write_text("{}")

    orig_tokens_file = config_module.settings.tokens_file
    orig_allow = config_module.settings.allow_localhost_admin

    config_module.settings.tokens_file = tokens_file
    config_module.settings.allow_localhost_admin = True

    # Patch require_admin_auth to always return "localhost" so TestClient
    # (which connects as "testclient", not "127.0.0.1") passes admin auth
    with patch("frontdoor.routes.admin.require_admin_auth", return_value="localhost"):
        with TestClient(app) as client:
            yield client, tokens_file

    config_module.settings.tokens_file = orig_tokens_file
    config_module.settings.allow_localhost_admin = orig_allow


class TestTokenEndpoints:
    def test_create_token(self, admin_client):
        """POST /api/admin/tokens creates a token and returns id + raw token."""
        client, tokens_file = admin_client
        resp = client.post("/api/admin/tokens", json={"name": "test-device"})
        assert resp.status_code == 201
        data = resp.json()
        assert data["id"].startswith("tok_")
        assert data["token"].startswith("ft_")
        assert data["name"] == "test-device"

    def test_list_tokens(self, admin_client):
        """GET /api/admin/tokens lists tokens without hashes."""
        client, tokens_file = admin_client
        create_token("device-a", tokens_file=tokens_file)
        resp = client.get("/api/admin/tokens")
        assert resp.status_code == 200
        data = resp.json()
        assert len(data) == 1
        assert data[0]["name"] == "device-a"
        assert "token_hash" not in data[0]

    def test_revoke_token(self, admin_client):
        """DELETE /api/admin/tokens/{id} removes the token."""
        client, tokens_file = admin_client
        token_id, _ = create_token("ephemeral", tokens_file=tokens_file)
        resp = client.delete(f"/api/admin/tokens/{token_id}")
        assert resp.status_code == 200
        list_resp = client.get("/api/admin/tokens")
        assert len(list_resp.json()) == 0

    def test_revoke_nonexistent_returns_404(self, admin_client):
        """DELETE /api/admin/tokens/{bad_id} returns 404."""
        client, _ = admin_client
        resp = client.delete("/api/admin/tokens/tok_doesnotexist")
        assert resp.status_code == 404

    def test_create_token_via_bearer_rejected(self, tmp_path):
        """POST /api/admin/tokens via bearer token identity returns 403."""
        # Patch require_admin_auth to return bearer identity (simulates remote token auth)
        with patch(
            "frontdoor.routes.admin.require_admin_auth",
            return_value="token:some-device",
        ):
            with TestClient(app) as client:
                resp = client.post(
                    "/api/admin/tokens",
                    json={"name": "escalated"},
                )
        assert resp.status_code == 403


class TestServiceControlEndpoints:
    def test_restart_single_service(self, admin_client):
        """POST /api/admin/services/{slug}/restart calls run_privileged."""
        client, _ = admin_client

        with (
            patch(
                "frontdoor.routes.admin.resolve_slug_to_unit",
                return_value="muxplex.service",
            ),
            patch("frontdoor.routes.admin.run_privileged") as mock_priv,
        ):
            resp = client.post("/api/admin/services/muxplex/restart")

        assert resp.status_code == 200
        data = resp.json()
        assert data["unit"] == "muxplex.service"
        assert data["status"] == "restarted"
        mock_priv.assert_called_once_with(
            "systemctl", action="restart", unit="muxplex.service"
        )

    def test_restart_unknown_slug_returns_404(self, admin_client):
        """POST /api/admin/services/{slug}/restart returns 404 for unknown slug."""
        client, _ = admin_client

        with patch("frontdoor.routes.admin.resolve_slug_to_unit", return_value=None):
            resp = client.post("/api/admin/services/nonexistent/restart")

        assert resp.status_code == 404

    def test_restart_all(self, admin_client):
        """POST /api/admin/services/restart-all restarts all except frontdoor."""
        client, _ = admin_client

        services = [
            {
                "name": "Muxplex",
                "url": "https://...",
                "status": "up",
                "systemd_unit": "muxplex.service",
            },
            {
                "name": "Filebrowser",
                "url": "https://...",
                "status": "up",
                "systemd_unit": "filebrowser.service",
            },
            {
                "name": "Frontdoor",
                "url": "https://...",
                "status": "up",
                "systemd_unit": "frontdoor.service",
            },
            {
                "name": "DevProc",
                "url": "https://...",
                "status": "up",
                "systemd_unit": None,
            },
        ]

        with (
            patch("frontdoor.routes.admin._get_service_units", return_value=services),
            patch("frontdoor.routes.admin.run_privileged") as mock_priv,
        ):
            resp = client.post("/api/admin/services/restart-all")

        assert resp.status_code == 200
        data = resp.json()
        assert "muxplex.service" in data["restarted"]
        assert "filebrowser.service" in data["restarted"]
        assert any(s["unit"] == "frontdoor.service" for s in data["skipped"])
        assert "DevProc" in data["no_unit"]
        assert mock_priv.call_count == 2

    def test_restart_all_error_handling(self, admin_client):
        """POST /api/admin/services/restart-all reports errors per-service."""
        client, _ = admin_client

        services = [
            {
                "name": "Muxplex",
                "url": "https://...",
                "status": "up",
                "systemd_unit": "muxplex.service",
            },
        ]

        with (
            patch("frontdoor.routes.admin._get_service_units", return_value=services),
            patch(
                "frontdoor.routes.admin.run_privileged",
                side_effect=RuntimeError("timeout"),
            ),
        ):
            resp = client.post("/api/admin/services/restart-all")

        assert resp.status_code == 200
        data = resp.json()
        assert "muxplex.service" in data["errors"]

    def test_restart_service_propagates_runtime_error(self, admin_client):
        """POST /api/admin/services/{slug}/restart returns 500 on run_privileged failure."""
        client, _ = admin_client

        with (
            patch(
                "frontdoor.routes.admin.resolve_slug_to_unit",
                return_value="muxplex.service",
            ),
            patch(
                "frontdoor.routes.admin.run_privileged",
                side_effect=RuntimeError("timeout"),
            ),
        ):
            resp = client.post("/api/admin/services/muxplex/restart")

        assert resp.status_code == 500
        assert resp.json()["detail"]["code"] == "RESTART_FAILED"
