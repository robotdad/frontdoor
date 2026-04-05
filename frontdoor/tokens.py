"""API token management — creation, validation, listing, and revocation.

Tokens are stored as SHA-256 hashes in a JSON file.  The raw token is
returned once at creation time and never persisted.
"""

import hashlib
import json
import logging
import secrets
from datetime import datetime, timezone
from pathlib import Path

from frontdoor.config import settings

logger = logging.getLogger(__name__)


def _hash_token(raw_token: str) -> str:
    """Return the hex SHA-256 digest of *raw_token*."""
    return hashlib.sha256(raw_token.encode()).hexdigest()


def _read_tokens(tokens_file: Path) -> dict:
    """Read the tokens JSON file, returning an empty dict if missing or invalid."""
    try:
        return json.loads(tokens_file.read_text())
    except (FileNotFoundError, json.JSONDecodeError):
        return {}


def _write_tokens(tokens_file: Path, data: dict) -> None:
    """Write the tokens dict to disk, creating parent directories if needed."""
    tokens_file.parent.mkdir(parents=True, exist_ok=True)
    tokens_file.write_text(json.dumps(data, indent=2))


def create_token(
    name: str, *, tokens_file: Path | None = None
) -> tuple[str, str]:
    """Create a new API token.

    Returns ``(token_id, raw_token)``.  The raw token is shown once —
    only its SHA-256 hash is stored on disk.

    Args:
        name: Human-readable label for this token (e.g. "robotdad-macbook").
        tokens_file: Override path to the tokens JSON file (defaults to
            ``settings.tokens_file``).
    """
    tf = tokens_file or settings.tokens_file
    token_id = "tok_" + secrets.token_hex(8)
    raw_token = "ft_" + secrets.token_urlsafe(32)

    data = _read_tokens(tf)
    data[token_id] = {
        "name": name,
        "token_hash": _hash_token(raw_token),
        "created_at": datetime.now(timezone.utc).isoformat(),
        "last_used_at": None,
    }
    _write_tokens(tf, data)

    logger.info("Created API token %s (%s)", token_id, name)
    return token_id, raw_token


def validate_token(
    raw_token: str, *, tokens_file: Path | None = None
) -> str | None:
    """Validate a raw API token.

    Returns the token name on success, ``None`` on failure.  Updates
    ``last_used_at`` on successful validation (best-effort).

    Args:
        raw_token: The ``ft_...`` token string from the Authorization header.
        tokens_file: Override path to the tokens JSON file.
    """
    if not raw_token.startswith("ft_"):
        return None

    tf = tokens_file or settings.tokens_file
    data = _read_tokens(tf)
    if not data:
        return None

    token_hash = _hash_token(raw_token)
    for token_id, entry in data.items():
        if entry.get("token_hash") == token_hash:
            try:
                entry["last_used_at"] = datetime.now(timezone.utc).isoformat()
                _write_tokens(tf, data)
            except Exception:
                pass
            return entry["name"]

    return None


def list_tokens(*, tokens_file: Path | None = None) -> list[dict]:
    """List all tokens — IDs and names, never hashes.

    Args:
        tokens_file: Override path to the tokens JSON file.
    """
    tf = tokens_file or settings.tokens_file
    data = _read_tokens(tf)
    return [
        {
            "id": token_id,
            "name": entry["name"],
            "created_at": entry.get("created_at"),
            "last_used_at": entry.get("last_used_at"),
        }
        for token_id, entry in data.items()
    ]


def revoke_token(
    token_id: str, *, tokens_file: Path | None = None
) -> bool:
    """Revoke a token by its ID.

    Returns ``True`` if the token was found and removed, ``False`` otherwise.

    Args:
        token_id: The ``tok_...`` identifier.
        tokens_file: Override path to the tokens JSON file.
    """
    tf = tokens_file or settings.tokens_file
    data = _read_tokens(tf)
    if token_id not in data:
        return False

    del data[token_id]
    _write_tokens(tf, data)
    logger.info("Revoked API token %s", token_id)
    return True
