"""Tests for frontdoor/discovery.py — parse_caddy_configs()."""

import json
import socket
from unittest.mock import patch

from frontdoor.discovery import overlay_manifests, parse_caddy_configs, tcp_probe


class TestParseCaddyConfigs:
    def test_parses_conf_d_files(self, tmp_caddy_dir):
        """parse_caddy_configs returns one entry per .caddy file in conf.d."""
        services = parse_caddy_configs(
            main_config=tmp_caddy_dir / "Caddyfile",
            conf_d=tmp_caddy_dir / "conf.d",
        )
        assert len(services) == 2

    def test_extracts_internal_port(self, tmp_caddy_dir):
        """Each service dict contains the correct internal_port."""
        services = parse_caddy_configs(
            main_config=tmp_caddy_dir / "Caddyfile",
            conf_d=tmp_caddy_dir / "conf.d",
        )
        ports = {s["internal_port"] for s in services}
        assert 8445 in ports
        assert 8443 in ports

    def test_extracts_external_url(self, tmp_caddy_dir):
        """Each service dict contains an external_url starting with https://."""
        services = parse_caddy_configs(
            main_config=tmp_caddy_dir / "Caddyfile",
            conf_d=tmp_caddy_dir / "conf.d",
        )
        for svc in services:
            assert svc["external_url"].startswith("https://")

    def test_excludes_frontdoor_port(self, tmp_caddy_dir):
        """Services proxying to port 8420 (frontdoor itself) are excluded."""
        services = parse_caddy_configs(
            main_config=tmp_caddy_dir / "Caddyfile",
            conf_d=tmp_caddy_dir / "conf.d",
        )
        ports = [s["internal_port"] for s in services]
        assert 8420 not in ports

    def test_name_derived_from_filename(self, tmp_caddy_dir):
        """Service names are title-cased words derived from the .caddy filename."""
        services = parse_caddy_configs(
            main_config=tmp_caddy_dir / "Caddyfile",
            conf_d=tmp_caddy_dir / "conf.d",
        )
        names = {s["name"] for s in services}
        assert "Dev Machine Monitor" in names
        assert "Filebrowser" in names

    def test_malformed_file_skipped(self, tmp_caddy_dir):
        """A malformed .caddy file is silently skipped; valid files are still parsed."""
        (tmp_caddy_dir / "conf.d" / "broken.caddy").write_text(
            "this is not valid caddy syntax {\n"
        )
        services = parse_caddy_configs(
            main_config=tmp_caddy_dir / "Caddyfile",
            conf_d=tmp_caddy_dir / "conf.d",
        )
        assert len(services) == 2

    def test_missing_conf_d_returns_empty(self, tmp_path):
        """When conf_d directory does not exist, return an empty list."""
        main_config = tmp_path / "Caddyfile"
        main_config.write_text("")
        services = parse_caddy_configs(
            main_config=main_config,
            conf_d=tmp_path / "nonexistent",
        )
        assert services == []


class TestTcpProbe:
    def test_success(self):
        """tcp_probe returns True when connection succeeds."""
        with patch("socket.create_connection") as mock_conn:
            mock_conn.return_value.__enter__ = lambda s: s
            mock_conn.return_value.__exit__ = lambda s, *a: False
            result = tcp_probe("localhost", 8080)
        assert result is True

    def test_connection_refused(self):
        """tcp_probe returns False when ConnectionRefusedError is raised."""
        with patch("socket.create_connection", side_effect=ConnectionRefusedError):
            result = tcp_probe("localhost", 9999)
        assert result is False

    def test_timeout(self):
        """tcp_probe returns False when socket.timeout is raised."""
        with patch("socket.create_connection", side_effect=socket.timeout):
            result = tcp_probe("localhost", 8080, timeout=0.1)
        assert result is False


class TestOverlayManifests:
    def test_manifest_found(self, tmp_path):
        """overlay_manifests enriches a service when a matching manifest file exists."""
        manifest_dir = tmp_path / "manifests"
        manifest_dir.mkdir()
        manifest_data = {
            "name": "File Browser",
            "description": "A web-based file manager",
            "icon": "folder",
        }
        (manifest_dir / "filebrowser.json").write_text(json.dumps(manifest_data))

        services = [
            {
                "name": "Filebrowser",
                "external_url": "https://files.example.com",
                "internal_port": 8445,
            }
        ]
        result = overlay_manifests(services, manifest_dir)

        assert len(result) == 1
        svc = result[0]
        # Manifest fields merged in
        assert svc["name"] == "File Browser"
        assert svc["description"] == "A web-based file manager"
        assert svc["icon"] == "folder"
        # Original fields preserved
        assert svc["external_url"] == "https://files.example.com"
        assert svc["internal_port"] == 8445

    def test_no_manifest_keeps_original(self, tmp_path):
        """overlay_manifests leaves services unchanged when no manifest file exists."""
        manifest_dir = tmp_path / "manifests"
        manifest_dir.mkdir()

        services = [
            {
                "name": "Filebrowser",
                "external_url": "https://files.example.com",
                "internal_port": 8445,
            }
        ]
        result = overlay_manifests(services, manifest_dir)

        assert len(result) == 1
        svc = result[0]
        assert svc["name"] == "Filebrowser"
        assert "description" not in svc

    def test_malformed_json_skipped(self, tmp_path):
        """overlay_manifests silently skips services whose manifest contains invalid JSON."""
        manifest_dir = tmp_path / "manifests"
        manifest_dir.mkdir()
        (manifest_dir / "filebrowser.json").write_text("{not valid json}")

        services = [
            {
                "name": "Filebrowser",
                "external_url": "https://files.example.com",
                "internal_port": 8445,
            }
        ]
        result = overlay_manifests(services, manifest_dir)

        assert len(result) == 1
        assert result[0]["name"] == "Filebrowser"

    def test_missing_manifest_dir_no_error(self, tmp_path):
        """overlay_manifests does not raise when the manifest directory does not exist."""
        nonexistent_dir = tmp_path / "does_not_exist"

        services = [
            {
                "name": "Filebrowser",
                "external_url": "https://files.example.com",
                "internal_port": 8445,
            }
        ]
        result = overlay_manifests(services, nonexistent_dir)

        assert len(result) == 1
        assert result[0]["name"] == "Filebrowser"
