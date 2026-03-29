"""Shared pytest fixtures for frontdoor tests."""

import pytest


@pytest.fixture
def tmp_caddy_dir(tmp_path):
    """Create a temporary Caddy config directory with sample config files.

    Layout:
        <tmp_path>/Caddyfile              ← main config (proxies to :8420 → skipped)
        <tmp_path>/conf.d/
            dev-machine-monitor.caddy    ← external :8447, proxy to :8445
            filebrowser.caddy            ← external :8443, proxy to :8443
    """
    conf_d = tmp_path / "conf.d"
    conf_d.mkdir()

    # Main Caddyfile: proxies to the frontdoor's own port (8420 → must be excluded)
    (tmp_path / "Caddyfile").write_text(
        ":8421 {\n    reverse_proxy localhost:8420\n}\n"
    )

    # Service configs in conf.d
    (conf_d / "dev-machine-monitor.caddy").write_text(
        ":8447 {\n    reverse_proxy localhost:8445\n}\n"
    )
    (conf_d / "filebrowser.caddy").write_text(
        ":8443 {\n    reverse_proxy localhost:8443\n}\n"
    )

    return tmp_path


@pytest.fixture
def tmp_manifest_dir(tmp_path):
    """Create a temporary manifests directory."""
    manifests = tmp_path / "manifests"
    manifests.mkdir()
    return manifests
