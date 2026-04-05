"""Service control — privileged operations via frontdoor-priv.

All privileged operations (writing Caddy configs, systemd units, and
running systemctl) are delegated to the ``frontdoor-priv`` helper via
``sudo``.  This module provides the ``run_privileged()`` wrapper that
serializes operations as JSON on stdin.
"""

import json
import logging
import shutil
import subprocess
from pathlib import Path

logger = logging.getLogger(__name__)

# Locate frontdoor-priv relative to this module.
_PRIV_SCRIPT = Path(__file__).parent / "bin" / "frontdoor-priv"


def _find_priv_script() -> str:
    """Return the absolute path to frontdoor-priv.

    Checks the package-relative location first, then falls back to
    ``/opt/frontdoor/bin/frontdoor-priv`` for deployed installs.
    """
    if _PRIV_SCRIPT.exists():
        return str(_PRIV_SCRIPT)
    fallback = Path("/opt/frontdoor/bin/frontdoor-priv")
    if fallback.exists():
        return str(fallback)
    found = shutil.which("frontdoor-priv")
    if found:
        return found
    return str(_PRIV_SCRIPT)  # will fail with a clear error


def run_privileged(operation: str, **kwargs: str) -> None:
    """Call ``frontdoor-priv`` via sudo with a JSON payload on stdin.

    Args:
        operation: One of the allowed operations (write-caddy, delete-caddy,
            write-service, delete-service, systemctl, caddy-reload).
        **kwargs: Additional fields for the JSON payload (e.g. slug, content,
            action, unit).

    Raises:
        RuntimeError: If the helper exits non-zero or times out.
    """
    payload = {"operation": operation, **kwargs}
    priv_path = _find_priv_script()

    logger.info(
        "run_privileged: %s %s",
        operation,
        kwargs.get("slug", kwargs.get("unit", "")),
    )

    try:
        result = subprocess.run(
            ["sudo", priv_path],
            input=json.dumps(payload),
            capture_output=True,
            text=True,
            timeout=30,
        )
    except subprocess.TimeoutExpired:
        raise RuntimeError(f"frontdoor-priv timed out: operation={operation}")

    if result.returncode != 0:
        error_msg = result.stderr.strip() or result.stdout.strip() or "unknown error"
        raise RuntimeError(
            f"frontdoor-priv failed (exit {result.returncode}): {error_msg}"
        )

    logger.debug("run_privileged OK: %s", result.stdout.strip())
