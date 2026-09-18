from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app.main import create_app
from app.spa import IMMUTABLE

SHELL = "<!doctype html><title>shell</title>"


@pytest.fixture
def frontend_dir(tmp_path):
    (tmp_path / "_shell.html").write_text(SHELL)
    (tmp_path / "assets").mkdir()
    (tmp_path / "assets" / "app-abc123.js").write_text("console.log('hi')")
    (tmp_path / "favicon.ico").write_bytes(b"\x00\x01")
    # Sits next to the served directory, so a traversal bug would expose it.
    (tmp_path.parent / "secret.txt").write_text("do not serve")
    return tmp_path


@pytest.fixture
def spa_client(frontend_dir):
    app = create_app(
        database_url="sqlite+aiosqlite:///:memory:",
        with_seed_data=False,
        frontend_dir=str(frontend_dir),
    )
    with TestClient(app) as c:
        yield c


def test_root_serves_the_shell(spa_client):
    resp = spa_client.get("/")
    assert resp.status_code == 200
    assert resp.text == SHELL


def test_client_side_routes_fall_back_to_the_shell(spa_client):
    resp = spa_client.get("/session/s_abc")
    assert resp.status_code == 200
    assert resp.text == SHELL


def test_real_files_are_served_as_themselves(spa_client):
    assert spa_client.get("/favicon.ico").content == b"\x00\x01"
    assert spa_client.get("/assets/app-abc123.js").text == "console.log('hi')"


def test_fingerprinted_assets_are_cached_forever_but_the_shell_is_not(spa_client):
    assert spa_client.get("/assets/app-abc123.js").headers["cache-control"] == IMMUTABLE
    assert "immutable" not in spa_client.get("/").headers.get("cache-control", "")


def test_missing_asset_is_a_404_not_html(spa_client):
    # Returning the shell here makes the browser fail with a baffling
    # "Unexpected token '<'" while parsing it as JavaScript.
    resp = spa_client.get("/assets/does-not-exist.js")
    assert resp.status_code == 404
    assert SHELL not in resp.text


def test_api_routes_take_precedence_over_the_catch_all(spa_client):
    resp = spa_client.post("/sessions")
    assert resp.status_code == 201
    assert "sessionId" in resp.json()
    assert spa_client.get("/openapi.json").json()["info"]["title"]


def test_websocket_still_works_alongside_the_frontend(spa_client):
    session_id = spa_client.post("/sessions").json()["sessionId"]
    with spa_client.websocket_connect(f"/ws/{session_id}") as ws:
        ws.send_json(
            {
                "type": "join",
                "sessionId": session_id,
                "participant": {"id": "p1", "color": "#fff", "role": "interviewer"},
            }
        )
        assert ws.receive_json()["type"] == "snapshot"


@pytest.mark.parametrize("path", ["/../secret.txt", "/%2e%2e/secret.txt", "/assets/../../secret.txt"])
def test_cannot_traverse_out_of_the_frontend_directory(spa_client, path):
    resp = spa_client.get(path)
    assert "do not serve" not in resp.text


def test_frontend_is_not_mounted_unless_configured(bare_client):
    # Local dev runs the frontend on its own Vite server; the API alone must
    # not start answering "/" with anything.
    assert bare_client.get("/").status_code == 404


def test_missing_shell_fails_loudly_at_startup(tmp_path):
    with pytest.raises(RuntimeError, match="_shell.html"):
        create_app(
            database_url="sqlite+aiosqlite:///:memory:",
            with_seed_data=False,
            frontend_dir=str(tmp_path),
        )
