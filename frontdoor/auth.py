import logging
import os
import pwd

import pam
from itsdangerous import TimestampSigner, BadSignature, SignatureExpired
from fastapi import Request, HTTPException
from frontdoor.config import settings


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
