"""Service discovery by parsing Caddy configuration files."""

import json
import logging
import re
import socket
import subprocess
from pathlib import Path

from frontdoor.ports import RESERVED_PORTS


logger = logging.getLogger(__name__)


def tcp_probe(host: str, port: int, timeout: float = 1.0) -> bool:
    """Check whether a TCP connection to *host*:*port* can be established.

    Returns ``True`` on success, ``False`` on any connection failure.
    """
    try:
        with socket.create_connection((host, port), timeout=timeout):
            pass
        return True
    except Exception:
        return False


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


def overlay_manifests(services: list[dict], manifest_dir: Path) -> list[dict]:
    """Enrich service dicts with metadata from per-service JSON manifest files.

    For each service, computes a slug from its ``name`` field and attempts to
    load ``manifest_dir/{slug}.json``.  When the file exists and contains valid
    JSON, the ``name``, ``description``, and ``icon`` keys from the manifest
    are merged (shallow copy) into the service dict.

    Missing directories, missing files, and malformed JSON are all handled
    silently.  Returns a new list of enriched dicts (original dicts are not
    mutated).
    """
    _MERGE_KEYS = ("name", "description", "icon")

    if not manifest_dir.exists():
        return [dict(svc) for svc in services]

    enriched: list[dict] = []
    for svc in services:
        slug = svc["name"].lower().replace(" ", "-")
        manifest_path = manifest_dir / f"{slug}.json"
        merged = dict(svc)
        try:
            data = json.loads(manifest_path.read_text())
            for key in _MERGE_KEYS:
                if key in data:
                    merged[key] = data[key]
        except (FileNotFoundError, json.JSONDecodeError):
            pass
        enriched.append(merged)

    return enriched


def scan_processes(skip_ports: set[int]) -> list[dict]:
    """Detect unregistered services by scanning listening TCP ports via ``ss -tlnp``.

    Runs ``ss -tlnp`` and parses the output to identify processes listening on
    ports that are not registered in Caddy configuration.

    Args:
        skip_ports: Set of ports already known to Caddy (should be excluded).

    Returns:
        A list of dicts with ``name``, ``port``, and ``pid`` for each
        discovered unregistered service.  Returns an empty list on any
        subprocess failure.
    """
    try:
        result = subprocess.run(
            ["ss", "-tlnp"],
            capture_output=True,
            text=True,
            timeout=5,
        )
    except Exception:
        return []

    exclude: set[int] = RESERVED_PORTS | skip_ports | {8420}

    services: list[dict] = []
    for line in result.stdout.splitlines():
        if "LISTEN" not in line:
            continue

        port_match = re.search(r":(\d+)\s", line)
        if not port_match:
            continue
        port = int(port_match.group(1))

        if port in exclude:
            continue

        proc_match = re.search(r'users:\(\("([^"]+)",pid=(\d+)', line)
        if not proc_match:
            continue

        services.append(
            {
                "name": proc_match.group(1),
                "port": port,
                "pid": int(proc_match.group(2)),
            }
        )

    return services
