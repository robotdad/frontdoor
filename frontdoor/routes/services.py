"""GET /api/services endpoint — discovers Caddy-proxied and unregistered services."""

from fastapi import APIRouter
from starlette.concurrency import run_in_threadpool

from frontdoor.config import settings
from frontdoor.discovery import (
    overlay_manifests,
    parse_caddy_configs,
    scan_processes,
    tcp_probe,
)

router = APIRouter()


def _collect_services() -> dict:
    """Synchronous orchestration — filesystem reads, TCP probes, subprocess scan."""
    # 1. Parse Caddy configuration files.
    parsed = parse_caddy_configs(settings.caddy_main_config, settings.caddy_conf_d)

    # 2. Build service list with live-status probing.
    services: list[dict] = []
    for svc in parsed:
        is_up = tcp_probe("127.0.0.1", svc["internal_port"])
        services.append(
            {
                "name": svc["name"],
                "url": svc["external_url"],
                "status": "up" if is_up else "down",
            }
        )

    # 3. Enrich services with manifest metadata.
    services = overlay_manifests(services, settings.manifest_dir)

    # 4. Collect Caddy-managed internal ports so scan_processes can skip them.
    caddy_ports: set[int] = {svc["internal_port"] for svc in parsed}

    # 5. Scan for processes listening on ports not managed by Caddy.
    unregistered = scan_processes(skip_ports=caddy_ports)

    return {"services": services, "unregistered": unregistered}


@router.get("/api/services")
async def get_services() -> dict:
    """Return all known services and any unregistered listening processes."""
    return await run_in_threadpool(_collect_services)
