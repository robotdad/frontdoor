"""Admin API router — all /api/admin/* endpoints.

Protected by require_admin_auth (three-tier: localhost → bearer → cookie).
"""

import json as json_module
import logging
import re

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel

from frontdoor.auth import require_admin_auth
from frontdoor.config import settings
from frontdoor.discovery import (
    get_port_pids,
    get_systemd_unit,
    next_available_ports,
    parse_caddy_configs,
)
from frontdoor.service_control import run_privileged
from frontdoor.tokens import create_token, list_tokens, revoke_token

SLUG_RE = re.compile(r"^[a-z0-9][a-z0-9\-]*$")


def _validate_slug(slug: str) -> None:
    """Raise HTTP 400 if *slug* is not a valid lowercase identifier."""
    if not SLUG_RE.match(slug):
        raise HTTPException(
            status_code=400,
            detail={"error": f"Invalid slug: {slug!r}", "code": "INVALID_SLUG"},
        )


logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/admin")


# ---------------------------------------------------------------------------
# Request / response models
# ---------------------------------------------------------------------------


class TokenCreateRequest(BaseModel):
    name: str


# ---------------------------------------------------------------------------
# Auth dependency — indirected so tests can patch require_admin_auth
# ---------------------------------------------------------------------------
# FastAPI captures the callable object at Depends() decoration time.  If we
# used Depends(require_admin_auth) directly, patching the module attribute
# wouldn't affect the already-captured reference.  By routing through
# _admin_auth, Python's LOAD_GLOBAL resolves require_admin_auth from this
# module's namespace at *call* time — so unittest.mock.patch works normally.


async def _admin_auth(request: Request) -> str:
    """Dependency shim: delegates to require_admin_auth via LOAD_GLOBAL."""
    return await require_admin_auth(request)


# ---------------------------------------------------------------------------
# Auth helpers for token creation restriction
# ---------------------------------------------------------------------------


def _is_token_auth(identity: str) -> bool:
    """Return True if the identity string indicates bearer token auth."""
    return identity.startswith("token:")


# ---------------------------------------------------------------------------
# Token management — POST/GET/DELETE /api/admin/tokens
# ---------------------------------------------------------------------------


@router.post("/tokens", status_code=201)
async def create_api_token(
    body: TokenCreateRequest,
    request: Request,
    identity: str = Depends(_admin_auth),
) -> dict:
    """Create a new API token.

    Requires Tier 1 (localhost) or Tier 3 (PAM session). Bearer tokens
    cannot create new tokens (prevents escalation if a token leaks).
    """
    if _is_token_auth(identity):
        raise HTTPException(
            status_code=403,
            detail={
                "error": "Token creation requires localhost or session auth",
                "code": "FORBIDDEN",
            },
        )

    token_id, raw_token = create_token(body.name)
    logger.info("Token created: %s (%s) by %s", token_id, body.name, identity)

    # Read back to get the created_at timestamp
    tokens = list_tokens()
    entry = next((t for t in tokens if t["id"] == token_id), {})

    return {
        "id": token_id,
        "name": body.name,
        "token": raw_token,
        "created_at": entry.get("created_at", ""),
    }


@router.get("/tokens")
async def list_api_tokens(
    identity: str = Depends(_admin_auth),
) -> list[dict]:
    """List all tokens — IDs, names, timestamps. Never returns hashes."""
    return list_tokens()


@router.delete("/tokens/{token_id}")
async def revoke_api_token(
    token_id: str,
    identity: str = Depends(_admin_auth),
) -> dict:
    """Revoke a token by ID."""
    if not revoke_token(token_id):
        raise HTTPException(
            status_code=404,
            detail={"error": f"Token {token_id} not found", "code": "NOT_FOUND"},
        )
    logger.info("Token revoked: %s by %s", token_id, identity)
    return {"status": "revoked", "id": token_id}


# ---------------------------------------------------------------------------
# Service control helpers
# ---------------------------------------------------------------------------


def resolve_slug_to_unit(slug: str) -> str | None:
    """Resolve a service slug to its systemd unit name.

    Two-pass strategy:
    1. Live: parse Caddy → find internal port → ss lookup → cgroup unit name
    2. Fallback: convention {slug}.service (for down services)
    """
    parsed = parse_caddy_configs(settings.caddy_main_config, settings.caddy_conf_d)
    port_pids = get_port_pids()

    for svc in parsed:
        svc_slug = svc["name"].lower().replace(" ", "-")
        if svc_slug == slug:
            pid = port_pids.get(svc["internal_port"])
            if pid:
                unit = get_systemd_unit(pid)
                if unit:
                    return unit
            return f"{slug}.service"

    return None


def get_all_services() -> list[dict]:
    """Return all Caddy-registered services with systemd_unit enrichment."""
    from frontdoor.discovery import tcp_probe

    parsed = parse_caddy_configs(settings.caddy_main_config, settings.caddy_conf_d)
    port_pids = get_port_pids()

    services: list[dict] = []
    for svc in parsed:
        pid = port_pids.get(svc["internal_port"])
        unit = get_systemd_unit(pid) if pid else None
        services.append(
            {
                "name": svc["name"],
                "url": svc["external_url"],
                "status": "up"
                if tcp_probe("127.0.0.1", svc["internal_port"])
                else "down",
                "systemd_unit": unit,
            }
        )
    return services


def _get_service_units() -> list[dict]:
    """Return name + systemd_unit for all Caddy-registered services.

    Unlike ``get_all_services()``, this does not perform TCP probes —
    restart-all only needs unit names, not live status.
    """
    parsed = parse_caddy_configs(settings.caddy_main_config, settings.caddy_conf_d)
    port_pids = get_port_pids()
    return [
        {
            "name": svc["name"],
            "systemd_unit": get_systemd_unit(port_pids[svc["internal_port"]])
            if svc["internal_port"] in port_pids
            else None,
        }
        for svc in parsed
    ]


# ---------------------------------------------------------------------------
# Service control — POST /api/admin/services/...
# NOTE: restart-all MUST be defined before {slug}/restart
# ---------------------------------------------------------------------------


@router.post("/services/restart-all")
async def restart_all_services(
    identity: str = Depends(_admin_auth),
) -> dict:
    """Restart all services except frontdoor itself.

    Returns a report of what was restarted, failed, skipped, or has no unit.
    """
    services = _get_service_units()

    restarted: list[str] = []
    errors: dict[str, str] = {}
    skipped: list[dict] = []
    no_unit: list[str] = []

    for svc in services:
        unit = svc.get("systemd_unit")
        if not unit:
            no_unit.append(svc["name"])
            continue

        if unit == settings.self_unit:
            skipped.append(
                {
                    "unit": unit,
                    "reason": f"self — restart manually with: sudo systemctl restart {unit}",
                }
            )
            continue

        try:
            run_privileged("systemctl", action="restart", unit=unit)
            restarted.append(unit)
        except RuntimeError as e:
            errors[unit] = str(e)

    logger.info(
        "restart-all by %s: %d restarted, %d errors, %d skipped, %d no_unit",
        identity,
        len(restarted),
        len(errors),
        len(skipped),
        len(no_unit),
    )
    return {
        "restarted": restarted,
        "errors": errors,
        "skipped": skipped,
        "no_unit": no_unit,
    }


@router.post("/services/{slug}/restart")
async def restart_service(
    slug: str,
    identity: str = Depends(_admin_auth),
) -> dict:
    """Restart a single service by slug."""
    unit = resolve_slug_to_unit(slug)
    if not unit:
        raise HTTPException(
            status_code=404,
            detail={"error": f"No service found for slug: {slug}", "code": "NOT_FOUND"},
        )

    try:
        run_privileged("systemctl", action="restart", unit=unit)
    except RuntimeError as e:
        raise HTTPException(
            status_code=500,
            detail={"error": str(e), "code": "RESTART_FAILED"},
        )

    logger.info("Restarted %s (%s) by %s", slug, unit, identity)
    return {"slug": slug, "unit": unit, "status": "restarted"}


# ---------------------------------------------------------------------------
# Port allocation — GET /api/admin/ports/next
# ---------------------------------------------------------------------------


@router.get("/ports/next")
async def get_next_ports(
    start: int = 8440,
    identity: str = Depends(_admin_auth),
) -> dict:
    """Return the next available internal + external port pair."""
    internal, external = next_available_ports(start=start)
    return {"internal_port": internal, "external_port": external}


# ---------------------------------------------------------------------------
# Manifest models
# ---------------------------------------------------------------------------


class ManifestRequest(BaseModel):
    name: str
    description: str = ""
    icon: str = ""


# ---------------------------------------------------------------------------
# Manifests — GET/PUT/DELETE /api/admin/manifests
# ---------------------------------------------------------------------------


@router.get("/manifests")
async def list_manifests(
    identity: str = Depends(_admin_auth),
) -> list[dict]:
    """List all installed manifests."""
    manifest_dir = settings.manifest_dir
    if not manifest_dir.exists():
        return []

    manifests = []
    for path in sorted(manifest_dir.glob("*.json")):
        try:
            data = json_module.loads(path.read_text())
            data["slug"] = path.stem
            manifests.append(data)
        except (json_module.JSONDecodeError, OSError):
            continue
    return manifests


@router.put("/manifests/{slug}")
async def set_manifest(
    slug: str,
    body: ManifestRequest,
    identity: str = Depends(_admin_auth),
) -> dict:
    """Create or update a manifest file."""
    _validate_slug(slug)

    manifest_dir = settings.manifest_dir
    manifest_dir.mkdir(parents=True, exist_ok=True)

    data = {"name": body.name, "description": body.description, "icon": body.icon}
    manifest_path = manifest_dir / f"{slug}.json"
    manifest_path.write_text(json_module.dumps(data, indent=2))

    logger.info("Manifest set: %s by %s", slug, identity)
    return {"slug": slug, "path": str(manifest_path), **data}


@router.delete("/manifests/{slug}")
async def delete_manifest(
    slug: str,
    identity: str = Depends(_admin_auth),
) -> dict:
    """Remove a manifest file."""
    _validate_slug(slug)

    manifest_path = settings.manifest_dir / f"{slug}.json"
    if not manifest_path.exists():
        raise HTTPException(
            status_code=404,
            detail={"error": f"Manifest not found: {slug}", "code": "NOT_FOUND"},
        )

    manifest_path.unlink()
    logger.info("Manifest deleted: %s by %s", slug, identity)
    return {"status": "deleted", "slug": slug}
