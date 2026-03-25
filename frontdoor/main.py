"""Frontdoor FastAPI application entry point."""

from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles

from frontdoor.routes import services

app = FastAPI(title="Frontdoor", docs_url=None, redoc_url=None)


@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception) -> JSONResponse:
    """Return a JSON 500 response for any unhandled exception."""
    return JSONResponse(
        status_code=500,
        content={"error": str(exc), "code": 500},
    )


# Include the services router (provides GET /api/services).
app.include_router(services.router)

# Conditionally mount the static file directory if it exists.
_static_dir = Path(__file__).parent.parent / "static"
if _static_dir.exists():
    app.mount("/", StaticFiles(directory=str(_static_dir), html=True), name="static")
