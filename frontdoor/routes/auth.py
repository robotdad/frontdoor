"""Auth endpoints: Caddy forward_auth validate and logout."""

from urllib.parse import urlencode

from fastapi import APIRouter, Depends, Form, Query, Request
from fastapi.responses import RedirectResponse, Response

from frontdoor.auth import authenticate_pam, create_session_token, require_auth
from frontdoor.config import settings

router = APIRouter()


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


@router.post("/api/auth/login")
async def login(
    request: Request,
    username: str = Form(...),
    password: str = Form(...),
    next_url: str = Query(default="/", alias="next"),
) -> RedirectResponse:
    """Login endpoint: validates PAM credentials and issues a session cookie."""
    safe_next = _safe_next_url(next_url)
    if not authenticate_pam(username, password):
        params = urlencode({"error": "1", "next": safe_next})
        return RedirectResponse(
            url=f"/login?{params}",
            status_code=303,
        )
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
    response = RedirectResponse(url="/login", status_code=303)
    response.delete_cookie(
        key="frontdoor_session",
        domain=settings.cookie_domain or None,
    )
    return response
