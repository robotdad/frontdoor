"""App registration — Caddy/systemd template rendering and lifecycle management.

Generates configuration files from request parameters and delegates
privileged filesystem writes to ``frontdoor-priv`` via
``service_control.run_privileged()``.
"""

import json
import logging
import subprocess
from pathlib import Path

from frontdoor.config import settings
from frontdoor.service_control import run_privileged

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Environment detection
# ---------------------------------------------------------------------------


def detect_fqdn() -> str:
    """Detect the machine's FQDN.

    Tries ``tailscale status --json`` first, falls back to ``hostname -f``.
    """
    try:
        result = subprocess.run(
            ["tailscale", "status", "--json"],
            capture_output=True,
            text=True,
            timeout=5,
        )
        if result.returncode == 0:
            data = json.loads(result.stdout)
            dns_name = data.get("Self", {}).get("DNSName", "")
            if dns_name:
                return dns_name.rstrip(".")
    except Exception:
        pass

    try:
        result = subprocess.run(
            ["hostname", "-f"],
            capture_output=True,
            text=True,
            timeout=5,
        )
        if result.returncode == 0:
            return result.stdout.strip()
    except Exception:
        pass

    return "localhost"


def detect_cert_paths() -> tuple[str | None, str | None]:
    """Detect TLS certificate paths.

    Checks ``/etc/ssl/tailscale/`` then ``/etc/ssl/self-signed/``.

    Returns:
        ``(cert_path, key_path)`` or ``(None, None)`` if not found.
    """
    fqdn = detect_fqdn()
    for cert_dir in ["/etc/ssl/tailscale", "/etc/ssl/self-signed"]:
        cert = Path(cert_dir) / f"{fqdn}.crt"
        key = Path(cert_dir) / f"{fqdn}.key"
        if cert.exists() and key.exists():
            return str(cert), str(key)
    return None, None


# ---------------------------------------------------------------------------
# Template rendering
# ---------------------------------------------------------------------------


def render_caddy_config(
    slug: str,
    fqdn: str,
    cert_path: str | None,
    key_path: str | None,
    internal_port: int,
    external_port: int,
    websocket_paths: list[str] | None,
    frontdoor_port: int = 8420,
) -> str:
    """Render a Caddy vhost config for an app.

    Args:
        slug: App identifier (used in comments only).
        fqdn: Fully qualified domain name for the vhost address.
        cert_path: Path to TLS certificate, or ``None`` for HTTP.
        key_path: Path to TLS key, or ``None`` for HTTP.
        internal_port: Port the app process binds to (127.0.0.1 only).
        external_port: Port Caddy exposes externally (all interfaces).
        websocket_paths: List of paths that bypass forward_auth, or ``None``.
        frontdoor_port: frontdoor's internal port for forward_auth.
    """
    if cert_path and key_path:
        addr = f"{fqdn}:{external_port}"
        tls_line = f"    tls {cert_path} {key_path}"
    else:
        addr = f"http://{fqdn}:{external_port}"
        tls_line = ""

    lines = [f"{addr} {{"]
    if tls_line:
        lines.append(tls_line)
    lines.append("")

    # WebSocket bypass handles (before the main handle)
    if websocket_paths:
        for ws_path in websocket_paths:
            ws_path = ws_path.strip()
            lines.append(f"    handle {ws_path} {{")
            lines.append(f"        reverse_proxy localhost:{internal_port} {{")
            lines.append("            header_up -X-Forwarded-For")
            lines.append("        }")
            lines.append("    }")
            lines.append("")

    # Main handle block with forward_auth
    if websocket_paths:
        lines.append("    handle {")
        lines.append(f"        forward_auth localhost:{frontdoor_port} {{")
        lines.append("            uri /api/auth/validate")
        lines.append("            copy_headers X-Authenticated-User")
        lines.append("        }")
        lines.append(f"        reverse_proxy localhost:{internal_port} {{")
        lines.append("            header_up -X-Forwarded-For")
        lines.append("        }")
        lines.append("    }")
    else:
        lines.append(f"    forward_auth localhost:{frontdoor_port} {{")
        lines.append("        uri /api/auth/validate")
        lines.append("        copy_headers X-Authenticated-User")
        lines.append("    }")
        lines.append("")
        lines.append(f"    reverse_proxy localhost:{internal_port}")

    lines.append("}")
    return "\n".join(lines) + "\n"


def render_service_unit(
    slug: str,
    exec_start: str,
    service_user: str,
    kill_mode: str | None,
    description: str,
) -> str:
    """Render a systemd service unit file.

    Args:
        slug: App identifier (not embedded in content, used for clarity).
        exec_start: The ExecStart command for the service.
        service_user: The User= directive value.
        kill_mode: If set (e.g. ``"process"``), adds ``KillMode=`` directive.
        description: Human-readable description for the unit.
    """
    exec_start = exec_start.replace("\n", " ").replace("\r", "")
    service_user = service_user.strip()
    description = description.replace("\n", " ").replace("\r", "")

    lines = [
        "[Unit]",
        f"Description={description}",
        "After=network.target",
        "",
        "[Service]",
        "Type=simple",
        f"User={service_user}",
        f"Environment=HOME=/home/{service_user}",
        f"ExecStart={exec_start}",
        "Restart=on-failure",
        "RestartSec=5",
    ]
    if kill_mode:
        lines.append(f"KillMode={kill_mode}")
    lines.extend(
        [
            "",
            "[Install]",
            "WantedBy=multi-user.target",
        ]
    )
    return "\n".join(lines) + "\n"


# ---------------------------------------------------------------------------
# Registration lifecycle
# ---------------------------------------------------------------------------


def register_app(
    slug: str,
    name: str,
    description: str,
    icon: str,
    internal_port: int,
    external_port: int,
    exec_start: str,
    service_user: str,
    kill_mode: str | None = None,
    websocket_paths: list[str] | None = None,
) -> dict:
    """Register a new app: write Caddy config, systemd unit, and manifest.

    Args:
        slug: App identifier.
        name: Human-readable display name.
        description: One-line description for the dashboard card.
        icon: Emoji or Phosphor icon keyword.
        internal_port: Port the app binds to (127.0.0.1 only).
        external_port: Port Caddy listens on.
        exec_start: systemd ExecStart command.
        service_user: systemd User= value.
        kill_mode: Optional KillMode= value (e.g. ``"process"``).
        websocket_paths: Optional WebSocket path patterns to bypass auth.

    Returns:
        Registration result dict with file paths and service status.

    Raises:
        RuntimeError: If any privileged operation fails.
    """
    fqdn = detect_fqdn()
    cert_path, key_path = detect_cert_paths()

    caddy_content = render_caddy_config(
        slug=slug,
        fqdn=fqdn,
        cert_path=cert_path,
        key_path=key_path,
        internal_port=internal_port,
        external_port=external_port,
        websocket_paths=websocket_paths,
        frontdoor_port=settings.port,
    )
    service_content = render_service_unit(
        slug=slug,
        exec_start=exec_start,
        service_user=service_user,
        kill_mode=kill_mode,
        description=description or name,
    )

    run_privileged("write-caddy", slug=slug, content=caddy_content)
    run_privileged("write-service", slug=slug, content=service_content)
    run_privileged("caddy-reload")
    run_privileged("systemctl", action="daemon-reload")
    run_privileged("systemctl", action="enable", unit=f"{slug}.service")
    run_privileged("systemctl", action="start", unit=f"{slug}.service")

    # Write manifest (frontdoor owns this directory — no privilege needed)
    manifest_dir = settings.manifest_dir
    manifest_dir.mkdir(parents=True, exist_ok=True)
    manifest_data = {"name": name, "description": description, "icon": icon}
    (manifest_dir / f"{slug}.json").write_text(json.dumps(manifest_data, indent=2))

    logger.info("Registered app: %s (ports %d/%d)", slug, internal_port, external_port)

    return {
        "slug": slug,
        "caddy_config": f"/etc/caddy/conf.d/{slug}.caddy",
        "service_unit": f"/etc/systemd/system/{slug}.service",
        "manifest": str(manifest_dir / f"{slug}.json"),
        "internal_port": internal_port,
        "external_port": external_port,
        "service_status": "start_requested",
    }


def unregister_app(slug: str) -> None:
    """Unregister an app: stop service, remove all config files.

    Does NOT remove the app's own installation directory (it never touched it).

    Args:
        slug: App identifier.
    """
    unit = f"{slug}.service"

    # Stop and disable the service (ignore errors if already stopped)
    for action in ("stop", "disable"):
        try:
            run_privileged("systemctl", action=action, unit=unit)
        except RuntimeError:
            pass

    run_privileged("delete-service", slug=slug)
    run_privileged("delete-caddy", slug=slug)
    run_privileged("systemctl", action="daemon-reload")
    run_privileged("caddy-reload")

    manifest_path = settings.manifest_dir / f"{slug}.json"
    if manifest_path.exists():
        manifest_path.unlink()

    logger.info("Unregistered app: %s", slug)
