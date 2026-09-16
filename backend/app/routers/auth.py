"""Auth endpoints: register, login, and a protected `me` endpoint.

Not part of openapi.yaml's documented contract (that spec has no auth at
all, per the frontend's link-based, no-accounts design). This is
standalone auth infrastructure, added so hashed-password + bearer-token
auth exists and is exercised end to end, without gating any existing
session/collaboration endpoint.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth import get_current_user, hash_password, verify_password
from app.db import get_db
from app.db_models import UserRecord
from app.models import LoginRequest, RegisterRequest, TokenResponse, UserPublic
from app.store import create_user, get_user_by_email, issue_token

router = APIRouter(prefix="/auth", tags=["auth"])


def _to_public(user: UserRecord) -> UserPublic:
    return UserPublic(id=user.id, email=user.email, name=user.name)


@router.post("/register", response_model=TokenResponse, status_code=status.HTTP_201_CREATED)
async def register(body: RegisterRequest, db: AsyncSession = Depends(get_db)) -> TokenResponse:
    if await get_user_by_email(db, body.email) is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT, detail="Email already registered"
        )
    try:
        user = await create_user(
            db, email=body.email, name=body.name, password_hash=hash_password(body.password)
        )
    except IntegrityError as exc:
        await db.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT, detail="Email already registered"
        ) from exc
    token = await issue_token(db, user.id)
    return TokenResponse(access_token=token, user=_to_public(user))


@router.post("/login", response_model=TokenResponse)
async def login(body: LoginRequest, db: AsyncSession = Depends(get_db)) -> TokenResponse:
    user = await get_user_by_email(db, body.email)
    if user is None or not verify_password(body.password, user.password_hash):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid email or password"
        )
    token = await issue_token(db, user.id)
    return TokenResponse(access_token=token, user=_to_public(user))


@router.get("/me", response_model=UserPublic)
async def me(current_user: UserRecord = Depends(get_current_user)) -> UserPublic:
    return _to_public(current_user)
