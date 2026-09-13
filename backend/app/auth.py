"""Password hashing and bearer-token authentication.

Standalone infrastructure: nothing in ``openapi.yaml`` currently requires
auth (the app is link-based, no accounts — see docs/spec.md), so no
existing endpoint is gated by this yet. ``get_current_user`` is available
for routes that opt in (currently just ``GET /auth/me``).
"""

from __future__ import annotations

import bcrypt
from fastapi import Depends, HTTPException, Request, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from app.store import Store, StoredUser

bearer_scheme = HTTPBearer(auto_error=False)


def hash_password(password: str) -> str:
    return bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")


def verify_password(password: str, password_hash: str) -> bool:
    return bcrypt.checkpw(password.encode("utf-8"), password_hash.encode("utf-8"))


def get_store(request: Request) -> Store:
    return request.app.state.store


def get_current_user(
    store: Store = Depends(get_store),
    credentials: HTTPAuthorizationCredentials | None = Depends(bearer_scheme),
) -> StoredUser:
    if credentials is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Not authenticated",
            headers={"WWW-Authenticate": "Bearer"},
        )
    user = store.get_user_by_token(credentials.credentials)
    if user is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired token",
            headers={"WWW-Authenticate": "Bearer"},
        )
    return user
