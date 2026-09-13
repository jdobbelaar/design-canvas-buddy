"""POST /sessions — create a new collaboration session.

Implements the `/sessions` path in openapi.yaml. No auth required.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, status

from app.auth import get_store
from app.models import CreateSessionResponse
from app.store import Store

router = APIRouter(tags=["sessions"])


@router.post(
    "/sessions", response_model=CreateSessionResponse, status_code=status.HTTP_201_CREATED
)
def create_session(store: Store = Depends(get_store)) -> CreateSessionResponse:
    session = store.create_session()
    return CreateSessionResponse(sessionId=session.id)
