"""Service discovery by parsing Caddy configuration files."""

import json
import logging
import re
import socket
import subprocess
from pathlib import Path

from .ports import RESERVED_PORTS


logger = logging.getLogger(__name__)


def _name_from_filename(filename: str) -> str:
    """Convert a .caddy filename to a human-readable service name.

    Examples:
        'dev-machine-monitor.caddy' -> 'Dev Machine Monitor'
        'filebrowser.caddy'         -> 'Filebrowser'
    """
    stem = filename.removesuffix(".caddy")
    return stem.replace("-", " ").title()


def _parse_site_block(text: str, name: str) -> dict | None:
    """Parse a single Caddy site block and return a service info dict.

    Returns a dict with ``name``, ``external_url``, and ``internal_port``,
    or ``None`` when the block should be skipped or is malformed.
    """
    # Site address is the first non-whitespace token before the opening brace.
    addr_match = re.search(r"^(\S+)\s*\{", text, re.MULTILINE)
    if not addr_match:
        return None
    site_addr = addr_match.group(1)

    # Locate the reverse_proxy directive and its target.
    proxy_match = re.search(r"reverse_proxy\s+(\S+)", text)
    if not proxy_match:
        return None
    proxy_target = proxy_match.group(1)

    # Extract the port number from the proxy target (e.g. "localhost:8445" → 8445).
    port_match = re.search(r":(\d+)$", proxy_target)
    if not port_match:
        return None
    internal_port = int(port_match.group(1))

    # Skip frontdoor's own port.
    if internal_port == 8420:
        return None

    external_url = f"https://{site_addr}"
    return {
        "name": name,
        "external_url": external_url,
        "internal_port": internal_port,
    }


def parse_caddy_configs(main_config: Path, conf_d: Path) -> list[dict]:
    """Parse Caddy configuration files and extract service information.

    Reads the main Caddyfile and all ``*.caddy`` files inside *conf_d*.
    Returns a list of service dicts, each containing ``name``,
    ``external_url``, and ``internal_port``.  Malformed files and a missing
    *conf_d* directory are handled silently.
    """
    services: list[dict] = []

    # --- Main Caddyfile -------------------------------------------------------
    if main_config.exists():
        try:
            content = main_config.read_text()
            # Split the file into top-level blocks.  Each block begins at a
            # line that starts in column 0 (non-whitespace after a newline).
            blocks = re.split(r"\n(?=\S)", content)
            for block in blocks:
                block = block.strip()
                if not block:
                    continue
                first_line = block.splitlines()[0].strip()
                # Skip comment lines and import directives.
                if first_line.startswith("#") or first_line.startswith("import"):
                    continue
                name = _name_from_filename(main_config.name)
                result = _parse_site_block(block, name)
                if result:
                    services.append(result)
        except Exception:
            logger.debug("Failed to parse main Caddyfile: %s", main_config)

    # --- conf.d/*.caddy files -------------------------------------------------
    if not conf_d.exists():
        return services

    for caddy_file in sorted(conf_d.glob("*.caddy")):
        try:
            content = caddy_file.read_text()
            name = _name_from_filename(caddy_file.name)
            result = _parse_site_block(content, name)
            if result:
                services.append(result)
        except Exception:
            logger.debug("Failed to parse Caddy config: %s", caddy_file)

    return services
