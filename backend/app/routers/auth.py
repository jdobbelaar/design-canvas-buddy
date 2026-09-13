"""Auth endpoints: register, login, and a protected `me` endpoint.

Not part of openapi.yaml's documented contract (that spec has no auth at
all, per the frontend's link-based, no-accounts design). This is
standalone auth infrastructure, added so hashed-password + bearer-token
auth exists and is exercised end to end, without gating any existing
session/collaboration endpoint.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status

from app.auth import get_current_user, get_store, hash_password, verify_password
from app.models import LoginRequest, RegisterRequest, TokenResponse, UserPublic
from app.store import Store, StoredUser

router = APIRouter(prefix="/auth", tags=["auth"])


def _to_public(user: StoredUser) -> UserPublic:
    return UserPublic(id=user.id, email=user.email, name=user.name)


@router.post("/register", response_model=TokenResponse, status_code=status.HTTP_201_CREATED)
def register(body: RegisterRequest, store: Store = Depends(get_store)) -> TokenResponse:
    if store.get_user_by_email(body.email) is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT, detail="Email already registered"
        )
    user = store.create_user(
        email=body.email, name=body.name, password_hash=hash_password(body.password)
    )
    token = store.issue_token(user.id)
    return TokenResponse(access_token=token, user=_to_public(user))


@router.post("/login", response_model=TokenResponse)
def login(body: LoginRequest, store: Store = Depends(get_store)) -> TokenResponse:
    user = store.get_user_by_email(body.email)
    if user is None or not verify_password(body.password, user.password_hash):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid email or password"
        )
    token = store.issue_token(user.id)
    return TokenResponse(access_token=token, user=_to_public(user))


@router.get("/me", response_model=UserPublic)
def me(current_user: StoredUser = Depends(get_current_user)) -> UserPublic:
    return _to_public(current_user)
