"""Static console routes for the backend dashboard."""

from __future__ import annotations

import logging
from pathlib import Path

from fastapi import APIRouter
from fastapi.responses import FileResponse

logger = logging.getLogger("BackendConsolePageAPI")
router = APIRouter(tags=["console"])

_STATIC_DIR = Path(__file__).resolve().parents[2] / "static"
_CONSOLE_HTML = _STATIC_DIR / "console.html"


def _console_file_response() -> FileResponse:
    """Return the console HTML file response."""
    return FileResponse(_CONSOLE_HTML, media_type="text/html")


@router.get("/", include_in_schema=False)
async def serve_console_root():
    """Serve the console HTML from the backend root."""
    logger.info("START: /")
    response = _console_file_response()
    logger.info("SUCCESS: /")
    return response


@router.get("/console", include_in_schema=False)
async def serve_console_page():
    """Serve the console HTML from /console."""
    logger.info("START: /console")
    response = _console_file_response()
    logger.info("SUCCESS: /console")
    return response
