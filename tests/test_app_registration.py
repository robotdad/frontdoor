"""Tests for frontdoor/app_registration.py — template rendering and registration."""

import pytest
from unittest.mock import patch, call


class TestRenderCaddyConfig:
    def test_basic_config(self):
        """render_caddy_config produces valid Caddy config for a simple app."""
        from frontdoor.app_registration import render_caddy_config

        result = render_caddy_config(
            slug="myapp",
            fqdn="ambrose.tail09557f.ts.net",
            cert_path="/etc/ssl/tailscale/ambrose.crt",
            key_path="/etc/ssl/tailscale/ambrose.key",
            internal_port=8450,
            external_port=8451,
            websocket_paths=None,
            frontdoor_port=8420,
        )

        assert "ambrose.tail09557f.ts.net:8451" in result
        assert "tls /etc/ssl/tailscale/ambrose.crt /etc/ssl/tailscale/ambrose.key" in result
        assert "forward_auth localhost:8420" in result
        assert "reverse_proxy localhost:8450" in result
        assert "/api/auth/validate" in result

    def test_with_websocket_paths(self):
        """render_caddy_config adds handle blocks for websocket paths."""
        from frontdoor.app_registration import render_caddy_config

        result = render_caddy_config(
            slug="muxplex",
            fqdn="ambrose.tail09557f.ts.net",
            cert_path="/etc/ssl/tailscale/ambrose.crt",
            key_path="/etc/ssl/tailscale/ambrose.key",
            internal_port=8088,
            external_port=8448,
            websocket_paths=["/terminal*", "/ws*"],
            frontdoor_port=8420,
        )

        assert "handle /terminal*" in result
        assert "handle /ws*" in result
        # WebSocket paths bypass forward_auth
        assert result.count("forward_auth") == 1  # only in the main handle block

    def test_without_tls(self):
        """render_caddy_config omits tls line when cert_path is None."""
        from frontdoor.app_registration import render_caddy_config

        result = render_caddy_config(
            slug="myapp",
            fqdn="myhost.local",
            cert_path=None,
            key_path=None,
            internal_port=8450,
            external_port=8451,
            websocket_paths=None,
            frontdoor_port=8420,
        )

        assert "http://myhost.local:8451" in result
        assert "tls" not in result


class TestRenderServiceUnit:
    def test_basic_unit(self):
        """render_service_unit produces a valid systemd unit."""
        from frontdoor.app_registration import render_service_unit

        result = render_service_unit(
            slug="myapp",
            exec_start="/opt/myapp/.venv/bin/uvicorn myapp.main:app",
            service_user="robotdad",
            kill_mode=None,
            description="My Application",
        )

        assert "[Unit]" in result
        assert "Description=My Application" in result
        assert "[Service]" in result
        assert "User=robotdad" in result
        assert "ExecStart=/opt/myapp/.venv/bin/uvicorn myapp.main:app" in result
        assert "[Install]" in result
        assert "KillMode" not in result

    def test_with_kill_mode(self):
        """render_service_unit includes KillMode when specified."""
        from frontdoor.app_registration import render_service_unit

        result = render_service_unit(
            slug="muxplex",
            exec_start="/home/robotdad/.local/bin/muxplex serve",
            service_user="robotdad",
            kill_mode="process",
            description="Muxplex tmux session dashboard",
        )

        assert "KillMode=process" in result
