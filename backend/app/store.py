"""In-memory data store.

Everything here lives in process memory and is lost on restart. Each
``Store`` instance is independent, which is what lets tests create a fresh,
isolated store per test via the ``app`` fixture rather than sharing global
state.
"""

from __future__ import annotations

import secrets
from dataclasses import dataclass, field

from app.models import Participant


@dataclass
class StoredUser:
    id: str
    email: str
    name: str | None
    password_hash: str


@dataclass
class SessionState:
    id: str
    objects: dict[str, dict] = field(default_factory=dict)
    participants: dict[str, Participant] = field(default_factory=dict)


def _new_id(prefix: str) -> str:
    return f"{prefix}_{secrets.token_urlsafe(6)}"


class Store:
    """Holds users, auth tokens, and collaboration sessions."""

    def __init__(self) -> None:
        self.users: dict[str, StoredUser] = {}
        self._user_id_by_email: dict[str, str] = {}
        self.tokens: dict[str, str] = {}  # token -> user id
        self.sessions: dict[str, SessionState] = {}

    # -- users -------------------------------------------------------

    def get_user_by_email(self, email: str) -> StoredUser | None:
        user_id = self._user_id_by_email.get(email.lower())
        return self.users.get(user_id) if user_id else None

    def get_user(self, user_id: str) -> StoredUser | None:
        return self.users.get(user_id)

    def create_user(self, email: str, name: str | None, password_hash: str) -> StoredUser:
        user = StoredUser(
            id=_new_id("u"), email=email, name=name, password_hash=password_hash
        )
        self.users[user.id] = user
        self._user_id_by_email[email.lower()] = user.id
        return user

    # -- tokens --------------------------------------------------------

    def issue_token(self, user_id: str) -> str:
        token = secrets.token_urlsafe(32)
        self.tokens[token] = user_id
        return token

    def get_user_by_token(self, token: str) -> StoredUser | None:
        user_id = self.tokens.get(token)
        return self.users.get(user_id) if user_id else None

    # -- sessions --------------------------------------------------------

    def create_session(self) -> SessionState:
        session_id = _new_id("s")
        session = SessionState(id=session_id)
        self.sessions[session_id] = session
        return session

    def get_session(self, session_id: str) -> SessionState | None:
        return self.sessions.get(session_id)


# --------------------------------------------------------------------------
# Seed data
# --------------------------------------------------------------------------

SEED_USER_EMAIL = "demo@example.com"
SEED_USER_PASSWORD = "password123"

_SEED_BOARD_OBJECTS: list[dict] = [
    {
        "id": "seed-client",
        "type": "shape",
        "kind": "box",
        "x": 80,
        "y": 220,
        "width": 160,
        "height": 80,
        "label": "Client",
    },
    {
        "id": "seed-lb",
        "type": "shape",
        "kind": "loadbalancer",
        "x": 360,
        "y": 220,
        "width": 160,
        "height": 80,
        "label": "Load Balancer",
    },
    {
        "id": "seed-api-1",
        "type": "shape",
        "kind": "box",
        "x": 640,
        "y": 100,
        "width": 160,
        "height": 80,
        "label": "API Server 1",
    },
    {
        "id": "seed-api-2",
        "type": "shape",
        "kind": "box",
        "x": 640,
        "y": 340,
        "width": 160,
        "height": 80,
        "label": "API Server 2",
    },
    {
        "id": "seed-queue",
        "type": "shape",
        "kind": "queue",
        "x": 920,
        "y": 220,
        "width": 160,
        "height": 80,
        "label": "Job Queue",
    },
    {
        "id": "seed-db",
        "type": "shape",
        "kind": "database",
        "x": 1200,
        "y": 220,
        "width": 160,
        "height": 80,
        "label": "Primary DB",
    },
    {
        "id": "seed-note",
        "type": "text",
        "x": 360,
        "y": 60,
        "text": "Walk through the request path, then discuss scaling the DB.",
    },
    {
        "id": "seed-edge-client-lb",
        "type": "connector",
        "from": {"objectId": "seed-client"},
        "to": {"objectId": "seed-lb"},
        "label": "",
    },
    {
        "id": "seed-edge-lb-api1",
        "type": "connector",
        "from": {"objectId": "seed-lb"},
        "to": {"objectId": "seed-api-1"},
        "label": "",
    },
    {
        "id": "seed-edge-lb-api2",
        "type": "connector",
        "from": {"objectId": "seed-lb"},
        "to": {"objectId": "seed-api-2"},
        "label": "",
    },
    {
        "id": "seed-edge-api1-queue",
        "type": "connector",
        "from": {"objectId": "seed-api-1"},
        "to": {"objectId": "seed-queue"},
        "label": "async",
    },
    {
        "id": "seed-edge-queue-db",
        "type": "connector",
        "from": {"objectId": "seed-queue"},
        "to": {"objectId": "seed-db"},
        "label": "",
    },
]

SEED_SESSION_ID = "demo"


def seed(store: Store) -> None:
    """Populate a freshly created store with demo data.

    - One demo user (see SEED_USER_EMAIL / SEED_USER_PASSWORD) so the auth
      endpoints have something to log in with out of the box.
    - One pre-populated session (SEED_SESSION_ID) with a small system-design
      diagram, so opening the frontend against this backend shows a board
      instead of a blank canvas.
    """
    from app.auth import hash_password

    store.create_user(
        email=SEED_USER_EMAIL,
        name="Demo Interviewer",
        password_hash=hash_password(SEED_USER_PASSWORD),
    )

    session = SessionState(id=SEED_SESSION_ID)
    session.objects = {obj["id"]: obj for obj in _SEED_BOARD_OBJECTS}
    store.sessions[session.id] = session
