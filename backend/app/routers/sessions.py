"""POST /sessions — create a new collaboration session.

Implements the `/sessions` path in openapi.yaml. No auth required.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import get_db
from app.models import CreateSessionResponse
from app import store

router = APIRouter(tags=["sessions"])


@router.post(
    "/sessions", response_model=CreateSessionResponse, status_code=status.HTTP_201_CREATED
)
async def create_session(db: AsyncSession = Depends(get_db)) -> CreateSessionResponse:
    session = await store.create_session(db)
    return CreateSessionResponse(sessionId=session.id)
