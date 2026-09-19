"""GET /health — is the app up, can it reach its database, and which build is this."""

from __future__ import annotations

import asyncio
import os

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse
from sqlalchemy import text

from app.models import HealthResponse

router = APIRouter(tags=["health"])

# A database that hangs must read as unhealthy, not hang the health check with it.
DB_CHECK_TIMEOUT = 5


@router.get(
    "/health",
    response_model=HealthResponse,
    responses={503: {"model": HealthResponse, "description": "The database is unreachable."}},
)
async def health(request: Request) -> JSONResponse:
    version = os.environ.get("APP_VERSION", "dev")
    try:
        async with asyncio.timeout(DB_CHECK_TIMEOUT):
            async with request.app.state.db_sessionmaker() as db:
                await db.execute(text("SELECT 1"))
    except Exception:  # noqa: BLE001 -- any failure means "not healthy"; don't leak details
        body = HealthResponse(status="unhealthy", database="unreachable", version=version)
        return JSONResponse(body.model_dump(), status_code=503)
    return JSONResponse(HealthResponse(status="ok", database="ok", version=version).model_dump())
