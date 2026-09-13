from __future__ import annotations

from app.store import SEED_SESSION_ID


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
    assert app.state.store.get_session(SEED_SESSION_ID) is not None


def test_seed_session_has_board_objects(app):
    session = app.state.store.get_session(SEED_SESSION_ID)
    assert len(session.objects) > 0
