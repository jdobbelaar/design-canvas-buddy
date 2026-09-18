"""Serve the built frontend (an SPA shell plus hashed assets) from FastAPI.

The frontend is built in SPA mode (see frontend/vite.config.ts), which emits
`_shell.html` rather than an `index.html`: the client-side router boots from
it for every route. Deep links like `/session/abc` therefore have no file on
disk and must fall back to the shell.
"""

from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI
from starlette.exceptions import HTTPException
from starlette.responses import Response
from starlette.staticfiles import StaticFiles
from starlette.types import Scope

SHELL_FILE = "_shell.html"
IMMUTABLE = "public, max-age=31536000, immutable"


class SPAStaticFiles(StaticFiles):
    async def get_response(self, path: str, scope: Scope) -> Response:
        try:
            response = await super().get_response(path, scope)
        except HTTPException as exc:
            # Only extensionless paths are client-side routes. A missing
            # `/assets/x.js` must stay a 404: answering with HTML makes the
            # browser fail with a baffling "Unexpected token '<'" instead.
            # (Starlette hands us "." for the root, so test the suffix.)
            if exc.status_code != 404 or Path(path).suffix:
                raise
            return await super().get_response(SHELL_FILE, scope)

        # Vite fingerprints everything under assets/, so it never changes.
        if Path(path).parts[:1] == ("assets",):
            response.headers["Cache-Control"] = IMMUTABLE
        return response


def mount_frontend(app: FastAPI, directory: str | Path) -> None:
    """Serve `directory` at `/`. Call after the API routers are included:
    routes are matched in order, so this catch-all must come last."""
    directory = Path(directory)
    if not (directory / SHELL_FILE).is_file():
        raise RuntimeError(
            f"FRONTEND_DIR={directory} has no {SHELL_FILE}; build the frontend "
            "with SPA_BUILD=1 (see the Dockerfile)."
        )
    app.mount("/", SPAStaticFiles(directory=directory), name="frontend")
