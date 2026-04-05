"""Admin API router — all /api/admin/* endpoints.

Protected by require_admin_auth (three-tier: localhost → bearer → cookie).
"""

import logging

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel

from frontdoor.auth import require_admin_auth
from frontdoor.tokens import create_token, list_tokens, revoke_token

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
