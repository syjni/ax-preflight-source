"""Single-process local reviewer app with the built Results Console mounted."""

from __future__ import annotations

import os
from pathlib import Path

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from .api import ROOT, create_local_review_app_from_env


CONSOLE_DIST_ENV = "AX_PRODUCT_CONSOLE_DIST"


def create_local_review_web_app_from_env() -> FastAPI:
    app = create_local_review_app_from_env()
    configured = Path(
        os.environ.get(CONSOLE_DIST_ENV, str(ROOT / "results_console" / "dist"))
    )
    console_dist = configured.resolve() if configured.is_absolute() else (ROOT / configured).resolve()
    if not (console_dist / "index.html").is_file():
        raise RuntimeError(
            f"Results Console build not found at {console_dist}; run npm run build first"
        )
    # API routes are registered first.  The final root mount serves the SPA and
    # assets without changing any /api behavior.
    app.mount("/", StaticFiles(directory=console_dist, html=True), name="results-console")
    return app
