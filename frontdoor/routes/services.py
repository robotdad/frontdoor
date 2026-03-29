"""GET /api/services endpoint — discovers Caddy-proxied and unregistered services."""

import logging

from fastapi import APIRouter, Depends
from starlette.concurrency import run_in_threadpool

from frontdoor.auth import require_auth
from frontdoor.config import settings
from frontdoor.discovery import (
    overlay_manifests,
    parse_caddy_configs,
    scan_processes,
    tcp_probe,
)

router = APIRouter()

logger = logging.getLogger(__name__)


def _collect_services() -> dict:
    """Synchronous orchestration — filesystem reads, TCP probes, subprocess scan."""
    # 1. Parse Caddy configuration files.
    parsed = parse_caddy_configs(settings.caddy_main_config, settings.caddy_conf_d)
    logger.debug("Parsed %d services from Caddy config", len(parsed))

    # 2. Build service list with live-status probing.
    services: list[dict] = []
    up_count = 0
    down_count = 0
    for svc in parsed:
        is_up = tcp_probe("127.0.0.1", svc["internal_port"])
        if is_up:
            up_count += 1
        else:
            down_count += 1
        services.append(
            {
                "name": svc["name"],
                "url": svc["external_url"],
                "status": "up" if is_up else "down",
            }
        )
    logger.debug("TCP probes complete: %d up, %d down", up_count, down_count)

    # 3. Enrich services with manifest metadata.
    services = overlay_manifests(services, settings.manifest_dir)

    # 4. Collect Caddy-managed internal ports so scan_processes can skip them.
    caddy_ports: set[int] = {svc["internal_port"] for svc in parsed}

    # 5. Scan for processes listening on ports not managed by Caddy.
    unregistered = scan_processes(skip_ports=caddy_ports)
    logger.debug("Process scan: %d unregistered services", len(unregistered))

    logger.info(
        "Services: %d configured, %d unregistered", len(services), len(unregistered)
    )
    return {"services": services, "unregistered": unregistered}


@router.get("/api/services")
async def get_services(username: str = Depends(require_auth)) -> dict:
    """Return all known services and any unregistered listening processes."""
    logger.debug("Services request user=%s", username)
    return await run_in_threadpool(_collect_services)
