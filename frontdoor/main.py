"""Frontdoor FastAPI application entry point."""

import logging
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles

from frontdoor.config import settings
from frontdoor.routes import admin, auth, services

logging.basicConfig(
    level=getattr(logging, settings.log_level.upper(), logging.INFO),
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    force=True,
)
# Suppress noisy third-party DEBUG output that floods the journal when our
# log level is set to debug.  We only want debug detail from our own code.
logging.getLogger("python_multipart").setLevel(logging.INFO)
logger = logging.getLogger(__name__)
logger.info("Frontdoor starting (log_level=%s)", settings.log_level)

app = FastAPI(title="Frontdoor", docs_url=None, redoc_url=None)


@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception) -> JSONResponse:
    """Return a JSON 500 response for any unhandled exception."""
    logger.exception("Unhandled exception for %s %s", request.method, request.url)
    return JSONResponse(
        status_code=500,
        content={"error": "Internal server error", "code": 500},
    )


# Include the auth router (provides GET /api/auth/validate and POST /api/auth/logout).
app.include_router(auth.router)

# Include the services router (provides GET /api/services).
app.include_router(services.router)

# Include the admin router (provides /api/admin/* management endpoints).
app.include_router(admin.router)

# Conditionally mount the static file directory if it exists.
_static_dir = Path(__file__).parent / "static"
if _static_dir.is_dir():
    app.mount("/", StaticFiles(directory=str(_static_dir), html=True), name="static")
