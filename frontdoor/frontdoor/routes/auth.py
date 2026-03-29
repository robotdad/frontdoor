"""Auth endpoints: Caddy forward_auth validate and logout."""

import logging
from pathlib import Path
from urllib.parse import urlencode

from fastapi import APIRouter, Depends, Form, Query, Request, WebSocket
from fastapi.responses import FileResponse, RedirectResponse, Response

from frontdoor.auth import (
    authenticate_pam,
    create_session_token,
    require_auth,
    validate_session_token,
)
from frontdoor.config import settings

router = APIRouter()

logger = logging.getLogger(__name__)

_STATIC_DIR = Path(__file__).parent.parent / "static"


@router.get("/login")
async def login_page() -> FileResponse:
    """Serve the login HTML page."""
    return FileResponse(_STATIC_DIR / "login.html")


def _safe_next_url(url: str) -> str:
    """Return url if it is a safe local path, otherwise return '/'.

    Accepts paths that start with '/' but not '//' (protocol-relative URLs
    would be followed by browsers as external redirects).
    """
    if url.startswith("/") and not url.startswith("//"):
        return url
    return "/"


@router.get("/api/auth/validate")
async def validate(username: str = Depends(require_auth)) -> Response:
    """Caddy forward_auth endpoint: returns 200 with X-Authenticated-User header."""
    return Response(
        status_code=200,
        headers={"X-Authenticated-User": username},
    )


@router.websocket("/api/auth/validate")
async def validate_ws(websocket: WebSocket) -> None:
    """WebSocket variant of the validate endpoint.

    Caddy's forward_auth sends WebSocket upgrade requests for downstream
    WebSocket connections (e.g. filebrowser terminal).  FastAPI needs an
    explicit WebSocket route to prevent the request from falling through
    to the StaticFiles catch-all (which crashes on non-HTTP scopes).

    The cookie is available on the WebSocket handshake headers before
    accept.  We validate the session and either accept (200-equivalent)
    or close with 4001 (401-equivalent) so Caddy can make its auth
    decision.
    """
    token = websocket.cookies.get("frontdoor_session")
    if not token:
        logger.warning("WS validate rejected: no session cookie")
        await websocket.close(code=4001)
        return
    username = validate_session_token(
        token, settings.secret_key, settings.session_timeout
    )
    if not username:
        logger.warning("WS validate rejected: invalid or expired token")
        await websocket.close(code=4001)
        return
    logger.info("WS validate accepted for user=%s", username)
    # Auth succeeded -- accept and send the username, then close.
    # Caddy's forward_auth reads the response headers on accept.
    await websocket.accept(headers=[(b"x-authenticated-user", username.encode())])
    await websocket.close()


@router.post("/api/auth/login")
async def login(
    request: Request,
    username: str = Form(...),
    password: str = Form(...),
    next_url: str = Query(default="/", alias="next"),
) -> RedirectResponse:
    """Login endpoint: validates PAM credentials and issues a session cookie."""
    safe_next = _safe_next_url(next_url)
    client = request.client.host if request.client else "unknown"
    if not authenticate_pam(username, password):
        logger.warning("Login failed for user=%s client=%s", username, client)
        params = urlencode({"error": "1", "next": safe_next})
        return RedirectResponse(
            url=f"/login?{params}",
            status_code=303,
        )
    logger.info("Login success for user=%s client=%s", username, client)
    token = create_session_token(username, settings.secret_key)
    response = RedirectResponse(url=safe_next, status_code=303)
    response.set_cookie(
        key="frontdoor_session",
        value=token,
        httponly=True,
        secure=settings.secure_cookies,
        samesite="lax",
        max_age=settings.session_timeout,
        domain=settings.cookie_domain or None,
    )
    return response


@router.post("/api/auth/logout")
async def logout() -> RedirectResponse:
    """Clear the session cookie and redirect to /login."""
    logger.info("Logout")
    response = RedirectResponse(url="/login", status_code=303)
    response.delete_cookie(
        key="frontdoor_session",
        domain=settings.cookie_domain or None,
    )
    return response
