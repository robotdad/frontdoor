"""Tests for /api/admin/* endpoints."""

import json
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
