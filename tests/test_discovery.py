"""Tests for frontdoor/discovery.py — parse_caddy_configs()."""


from frontdoor.discovery import parse_caddy_configs


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
