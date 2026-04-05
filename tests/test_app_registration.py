"""Tests for frontdoor/app_registration.py — template rendering and registration."""

import frontdoor.config as config_module
from unittest.mock import patch


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
        assert (
            "tls /etc/ssl/tailscale/ambrose.crt /etc/ssl/tailscale/ambrose.key"
            in result
        )
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


class TestRegisterApp:
    def test_register_calls_privileged_operations(self, tmp_path):
        """register_app calls run_privileged for caddy, service, and systemctl."""
        from frontdoor.app_registration import register_app

        orig_manifest_dir = config_module.settings.manifest_dir
        config_module.settings.manifest_dir = tmp_path / "manifests"
        try:
            with (
                patch(
                    "frontdoor.app_registration.detect_fqdn",
                    return_value="ambrose.ts.net",
                ),
                patch(
                    "frontdoor.app_registration.detect_cert_paths",
                    return_value=("/etc/ssl/ts/ambrose.crt", "/etc/ssl/ts/ambrose.key"),
                ),
                patch("frontdoor.app_registration.run_privileged") as mock_priv,
            ):
                result = register_app(
                    slug="myapp",
                    name="My App",
                    description="Test app",
                    icon="rocket",
                    internal_port=8450,
                    external_port=8451,
                    exec_start="/opt/myapp/run",
                    service_user="robotdad",
                )
        finally:
            config_module.settings.manifest_dir = orig_manifest_dir

        assert result["slug"] == "myapp"
        assert result["internal_port"] == 8450

        call_ops = [c.args[0] for c in mock_priv.call_args_list]
        assert "write-caddy" in call_ops
        assert "write-service" in call_ops
        assert "caddy-reload" in call_ops
        assert "systemctl" in call_ops

    def test_register_writes_manifest(self, tmp_path):
        """register_app writes a manifest file to the manifest directory."""
        from frontdoor.app_registration import register_app
        import json

        manifest_dir = tmp_path / "manifests"
        orig_manifest_dir = config_module.settings.manifest_dir
        config_module.settings.manifest_dir = manifest_dir
        try:
            with (
                patch(
                    "frontdoor.app_registration.detect_fqdn", return_value="test.local"
                ),
                patch(
                    "frontdoor.app_registration.detect_cert_paths",
                    return_value=(None, None),
                ),
                patch("frontdoor.app_registration.run_privileged"),
            ):
                register_app(
                    slug="testapp",
                    name="Test App",
                    description="Testing",
                    icon="flask",
                    internal_port=9000,
                    external_port=9001,
                    exec_start="/usr/bin/testapp",
                    service_user="testuser",
                )
        finally:
            config_module.settings.manifest_dir = orig_manifest_dir

        manifest_path = manifest_dir / "testapp.json"
        assert manifest_path.exists()
        data = json.loads(manifest_path.read_text())
        assert data["name"] == "Test App"


class TestUnregisterApp:
    def test_unregister_calls_stop_disable_delete(self, tmp_path):
        """unregister_app stops, disables, and removes all config files."""
        from frontdoor.app_registration import unregister_app

        manifest_dir = tmp_path / "manifests"
        manifest_dir.mkdir()
        (manifest_dir / "myapp.json").write_text('{"name": "My App"}')

        orig_manifest_dir = config_module.settings.manifest_dir
        config_module.settings.manifest_dir = manifest_dir
        try:
            with patch("frontdoor.app_registration.run_privileged") as mock_priv:
                unregister_app("myapp")
        finally:
            config_module.settings.manifest_dir = orig_manifest_dir

        call_ops = [c.args[0] for c in mock_priv.call_args_list]
        assert "delete-caddy" in call_ops
        assert "delete-service" in call_ops
        assert not (manifest_dir / "myapp.json").exists()
