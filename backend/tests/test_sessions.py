from __future__ import annotations

from app import store
from app.seed import SEED_SESSION_ID

from .conftest import run_db


def test_create_session_returns_new_id(bare_client):
    resp = bare_client.post("/sessions")
    assert resp.status_code == 201
    body = resp.json()
    assert isinstance(body["sessionId"], str)
    assert body["sessionId"]


def test_create_session_requires_no_auth(bare_client):
    # No Authorization header sent at all — must still succeed.
    resp = bare_client.post("/sessions")
    assert resp.status_code == 201


def test_each_created_session_has_a_unique_id(bare_client):
    ids = {bare_client.post("/sessions").json()["sessionId"] for _ in range(5)}
    assert len(ids) == 5


def test_seed_session_exists_on_a_freshly_seeded_app(app):
    session = run_db(app, lambda db: store.get_session(db, SEED_SESSION_ID))
    assert session is not None


def test_seed_session_has_board_objects(app):
    objects = run_db(app, lambda db: store.get_session_objects(db, SEED_SESSION_ID))
    assert len(objects) > 0
