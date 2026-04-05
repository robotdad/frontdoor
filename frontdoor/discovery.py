"""Service discovery by parsing Caddy configuration files."""

import json
import logging
import re
import socket
import subprocess
from pathlib import Path

from frontdoor.config import settings
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
        logger.debug("Skipping block %s: no address found", name)
        return None
    site_addr = addr_match.group(1)

    # Locate the reverse_proxy directive and its target.
    # Skip named-matcher directives like "reverse_proxy @terminal ..."
    proxy_match = re.search(r"reverse_proxy\s+(?!@)(\S+)", text)
    if not proxy_match:
        logger.debug("Skipping block %s: no reverse_proxy found", name)
        return None
    proxy_target = proxy_match.group(1)

    # Extract the port number from the proxy target (e.g. "localhost:8445" → 8445).
    port_match = re.search(r":(\d+)$", proxy_target)
    if not port_match:
        return None
    internal_port = int(port_match.group(1))

    # Skip frontdoor's own port.
    if internal_port == settings.port:
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
            logger.warning("Failed to parse main Caddyfile: %s", main_config)

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
            logger.warning("Failed to parse Caddy config: %s", caddy_file)

    logger.info("Parsed %d services from Caddy configs", len(services))
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
        except json.JSONDecodeError as e:
            logger.debug("Invalid manifest for %s: %s", slug, e)
        except FileNotFoundError:
            logger.debug("No manifest for %s", slug)
        enriched.append(merged)

    return enriched


_RE_SS_PORT = re.compile(r":(\d+)\s")
_RE_SS_PROC = re.compile(r'users:\(\("([^"]+)",pid=(\d+)')


def _run_ss_tlnp() -> str | None:
    """Run ``ss -tlnp`` and return stdout, or ``None`` on any failure."""
    try:
        result = subprocess.run(
            ["ss", "-tlnp"],
            capture_output=True,
            text=True,
            timeout=5,
        )
    except Exception as e:
        logger.warning("ss command error: %s", e)
        return None
    if result.returncode != 0:
        logger.warning("ss command failed (returncode=%d)", result.returncode)
        return None
    return result.stdout


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
    stdout = _run_ss_tlnp()
    if stdout is None:
        return []

    exclude: set[int] = RESERVED_PORTS | skip_ports | {settings.port}

    services: list[dict] = []
    listen_count = 0
    for line in stdout.splitlines():
        if "LISTEN" not in line:
            continue
        listen_count += 1

        port_match = _RE_SS_PORT.search(line)
        if not port_match:
            continue
        port = int(port_match.group(1))

        if port in exclude:
            continue

        proc_match = _RE_SS_PROC.search(line)
        if not proc_match:
            continue

        services.append(
            {
                "name": proc_match.group(1),
                "port": port,
                "pid": int(proc_match.group(2)),
            }
        )

    logger.debug(
        "Process scan found %d listeners, %d unregistered", listen_count, len(services)
    )
    return services


def get_port_pids() -> dict[int, int]:
    """Return {port: pid} for all listening TCP ports via ``ss -tlnp``.

    Returns an empty dict on any subprocess failure.
    """
    stdout = _run_ss_tlnp()
    if stdout is None:
        return {}

    port_pids: dict[int, int] = {}
    for line in stdout.splitlines():
        if "LISTEN" not in line:
            continue
        port_match = _RE_SS_PORT.search(line)
        proc_match = _RE_SS_PROC.search(line)
        if port_match and proc_match:
            port_pids[int(port_match.group(1))] = int(proc_match.group(2))

    return port_pids


def next_available_ports(start: int = 8440) -> tuple[int, int]:
    """Return the next available ``(internal_port, external_port)`` pair.

    Checks three sources for used ports:

    1. Caddy ``conf.d`` — external **and** internal ports from existing vhost configs
       (handles services that are registered but currently down)
    2. ``ss -tlnp`` — all currently-bound ports (live reality)
    3. :data:`RESERVED_PORTS` from ``frontdoor/ports.py``

    The union of sources 1 and 2 prevents reusing a port that belongs
    to a registered-but-down service.

    Returns two distinct free ports starting from *start*.

    Raises:
        RuntimeError: If no free port pair is found before port 65535.
    """
    # Collect Caddy-used ports (both external vhost ports and internal proxy targets)
    caddy_used: set[int] = set()
    parsed = parse_caddy_configs(settings.caddy_main_config, settings.caddy_conf_d)
    for svc in parsed:
        caddy_used.add(svc["internal_port"])
    if settings.caddy_conf_d.exists():
        for caddy_file in settings.caddy_conf_d.glob("*.caddy"):
            try:
                content = caddy_file.read_text()
                addr_match = re.search(r":(\d+)\s*\{", content)
                if addr_match:
                    caddy_used.add(int(addr_match.group(1)))
            except Exception:
                pass

    # Collect live-used ports from ss
    port_pids = get_port_pids()
    live_used: set[int] = set(port_pids.keys())

    # Union of all used ports
    all_used = caddy_used | live_used | RESERVED_PORTS | {settings.port}

    # Find two distinct free ports
    found: list[int] = []
    port = start
    while len(found) < 2 and port <= 65535:
        if port not in all_used:
            found.append(port)
        port += 1

    if len(found) < 2:
        raise RuntimeError(f"No available port pair found starting from {start}")

    return found[0], found[1]


def get_systemd_unit(pid: int, proc_root: Path | None = None) -> str | None:
    """Return the systemd unit name for *pid*, or ``None``.

    Reads ``/proc/<pid>/cgroup`` and extracts the service name::

        0::/system.slice/muxplex.service  →  "muxplex.service"

    Returns ``None`` for processes not running under a systemd ``.service``
    unit, or when the cgroup file cannot be read.

    Args:
        pid: Process ID to look up.
        proc_root: Override for ``/proc`` (used in tests).
    """
    root = proc_root or Path("/proc")
    cgroup_path = root / str(pid) / "cgroup"
    try:
        content = cgroup_path.read_text()
    except (FileNotFoundError, PermissionError):
        return None

    for line in content.splitlines():
        # Format: hierarchy-ID:controller-list:cgroup-path
        # e.g. "0::/system.slice/muxplex.service"
        parts = line.strip().split(":")
        if len(parts) >= 3:
            cgroup = parts[2]
            # Extract the last path component if it ends with .service
            basename = cgroup.rsplit("/", 1)[-1]
            if basename.endswith(".service"):
                return basename

    return None
