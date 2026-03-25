"""Auth endpoints: Caddy forward_auth validate and logout."""

from fastapi import APIRouter, Depends, Form, Query
from fastapi.responses import RedirectResponse, Response

from frontdoor.auth import authenticate_pam, create_session_token, require_auth
from frontdoor.config import settings

router = APIRouter()


@router.get("/api/auth/validate")
async def validate(username: str = Depends(require_auth)) -> Response:
    """Caddy forward_auth endpoint: returns 200 with X-Authenticated-User header."""
    return Response(
        status_code=200,
        headers={"X-Authenticated-User": username},
    )


@router.post("/api/auth/login")
async def login(
    username: str = Form(...),
    password: str = Form(...),
    next_url: str = Query(default="/", alias="next"),
) -> RedirectResponse:
    """Login endpoint: validates PAM credentials and issues a session cookie."""
    if not authenticate_pam(username, password):
        return RedirectResponse(
            url=f"/login?error=1&next={next_url}",
            status_code=303,
        )
    token = create_session_token(username, settings.secret_key)
    response = RedirectResponse(url=next_url, status_code=303)
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
