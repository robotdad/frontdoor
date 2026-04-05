import logging
import os
import pwd

import pam
from itsdangerous import TimestampSigner, BadSignature, SignatureExpired
from fastapi import Request, HTTPException
from frontdoor.config import settings
from frontdoor.tokens import validate_token


logger = logging.getLogger(__name__)


def authenticate_pam(username: str, password: str) -> bool:
    # Single-user guard: frontdoor runs as one OS user and only that user may
    # authenticate through it.  Checking at the socket/UID level (not just
    # comparing strings) means a multi-user machine can't cross-authenticate
    # even if PAM would otherwise accept the other user's credentials.
    # Pattern sourced from muxplex auth.py.
    running_user = pwd.getpwuid(os.getuid()).pw_name
    if username != running_user:
        logger.warning(
            "PAM auth rejected: submitted username=%s does not match process owner=%s",
            username,
            running_user,
        )
        return False
    p = pam.pam()
    success = p.authenticate(username, password)
    if success:
        logger.debug("PAM auth succeeded: user=%s", username)
    else:
        logger.warning("PAM auth failed: user=%s", username)
    return success


def create_session_token(username: str, secret_key: str) -> str:
    signer = TimestampSigner(secret_key)
    return signer.sign(username).decode()


def validate_session_token(token: str, secret_key: str, max_age: int) -> str | None:
    signer = TimestampSigner(secret_key)
    try:
        return signer.unsign(token, max_age=max_age).decode()
    except SignatureExpired:
        logger.debug("Session token expired")
        return None
    except BadSignature:
        logger.warning("Bad session token signature (possible tampering)")
        return None


async def require_auth(request: Request) -> str:
    token = request.cookies.get("frontdoor_session")
    if not token:
        logger.debug("Auth: no session cookie")
        raise HTTPException(
            status_code=401,
            detail={"error": "Not authenticated", "code": "UNAUTHORIZED"},
        )
    username = validate_session_token(
        token, settings.secret_key, settings.session_timeout
    )
    if not username:
        logger.warning("Auth rejected: invalid session token")
        raise HTTPException(
            status_code=401,
            detail={"error": "Session expired or invalid", "code": "UNAUTHORIZED"},
        )
    return username


async def require_admin_auth(request: Request) -> str:
    """FastAPI dependency — authenticate for admin endpoints.

    Checks three tiers in order (first match wins):

    1. Localhost bypass (``request.client.host == "127.0.0.1"``).
       Uses the actual TCP connection host, not X-Forwarded-For.
    2. API token (``Authorization: Bearer ft_...``)
    3. PAM session cookie (existing ``frontdoor_session``)

    Returns:
        The authenticated identity string:
        - ``"localhost"`` for tier 1
        - ``"token:<name>"`` for tier 2
        - ``"<username>"`` for tier 3

    Raises:
        HTTPException: HTTP 401 if all tiers fail.
    """
    # Tier 1: Localhost bypass
    client_host = request.client.host if request.client else None
    if client_host == "127.0.0.1" and settings.allow_localhost_admin:
        logger.debug("Admin auth: localhost bypass")
        return "localhost"

    # Tier 2: API token
    auth_header = request.headers.get("authorization", "")
    if auth_header.startswith("Bearer "):
        raw_token = auth_header[7:]
        token_name = validate_token(raw_token, tokens_file=settings.tokens_file)
        if token_name:
            logger.debug("Admin auth: token %s", token_name)
            return f"token:{token_name}"

    # Tier 3: PAM session cookie
    session_cookie = request.cookies.get("frontdoor_session")
    if session_cookie:
        username = validate_session_token(
            session_cookie, settings.secret_key, settings.session_timeout
        )
        if username:
            logger.debug("Admin auth: session cookie user=%s", username)
            return username

    logger.warning("Admin auth: all tiers failed from %s", client_host)
    raise HTTPException(
        status_code=401,
        detail={"error": "Admin authentication required", "code": "UNAUTHORIZED"},
    )
