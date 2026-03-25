"""Auth endpoints: Caddy forward_auth validate and logout."""

from fastapi import APIRouter, Depends
from fastapi.responses import RedirectResponse, Response

from frontdoor.auth import require_auth
from frontdoor.config import settings

router = APIRouter()


@router.get("/api/auth/validate")
async def validate(username: str = Depends(require_auth)) -> Response:
    """Caddy forward_auth endpoint: returns 200 with X-Authenticated-User header."""
    return Response(
        status_code=200,
        headers={"X-Authenticated-User": username},
    )


@router.post("/api/auth/logout")
async def logout() -> RedirectResponse:
    """Clear the session cookie and redirect to /login."""
    response = RedirectResponse(url="/login", status_code=303)
    response.delete_cookie(
        key="frontdoor_session",
        domain=settings.cookie_domain or None,
    )
    return response
