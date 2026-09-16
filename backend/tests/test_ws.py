from __future__ import annotations

from app import store
from app.seed import SEED_SESSION_ID

from .conftest import run_db


def _join_event(session_id: str, participant_id: str, role: str = "interviewer") -> dict:
    return {
        "type": "join",
        "sessionId": session_id,
        "participant": {"id": participant_id, "color": "#ff0000", "role": role},
    }


def test_connecting_to_unknown_session_is_rejected(client):
    with client.websocket_connect("/ws/does-not-exist") as ws:
        try:
            ws.receive_json()
            assert False, "expected the connection to be closed"
        except Exception:
            pass  # Starlette raises WebSocketDisconnect on the closed connection.


def test_join_receives_snapshot_with_seeded_objects(client):
    with client.websocket_connect(f"/ws/{SEED_SESSION_ID}") as ws:
        ws.send_json(_join_event(SEED_SESSION_ID, "p1"))
        snapshot = ws.receive_json()

        assert snapshot["type"] == "snapshot"
        object_ids = {obj["id"] for obj in snapshot["objects"]}
        assert "seed-lb" in object_ids
        assert "seed-db" in object_ids
        # "Others" only — p1 doesn't see themselves in their own participant list.
        assert snapshot["participants"] == []


def test_second_join_broadcasts_presence_to_first_participant(bare_client):
    session_id = bare_client.post("/sessions").json()["sessionId"]

    with bare_client.websocket_connect(f"/ws/{session_id}") as ws1:
        ws1.send_json(_join_event(session_id, "p1", "interviewer"))
        ws1.receive_json()  # snapshot

        with bare_client.websocket_connect(f"/ws/{session_id}") as ws2:
            ws2.send_json(_join_event(session_id, "p2", "candidate"))
            ws2.receive_json()  # snapshot for p2

            presence = ws1.receive_json()  # p1 is told p2 joined
            assert presence["type"] == "presence"
            # "Others" only — p1 sees p2, but not themselves.
            assert {p["id"] for p in presence["participants"]} == {"p2"}


def test_ops_from_one_participant_are_broadcast_and_persisted(bare_client, bare_app):
    session_id = bare_client.post("/sessions").json()["sessionId"]

    with bare_client.websocket_connect(f"/ws/{session_id}") as ws1:
        ws1.send_json(_join_event(session_id, "p1"))
        ws1.receive_json()  # snapshot

        with bare_client.websocket_connect(f"/ws/{session_id}") as ws2:
            ws2.send_json(_join_event(session_id, "p2"))
            ws2.receive_json()  # snapshot
            ws1.receive_json()  # presence: p2 joined

            add_op = {
                "type": "ops",
                "sessionId": session_id,
                "from": "p1",
                "ops": [
                    {
                        "op": "add",
                        "objects": [
                            {
                                "id": "shape-1",
                                "type": "shape",
                                "kind": "box",
                                "x": 0,
                                "y": 0,
                                "width": 100,
                                "height": 50,
                                "label": "New Service",
                            }
                        ],
                    }
                ],
            }
            ws1.send_json(add_op)

            relayed = ws2.receive_json()
            assert relayed["type"] == "ops"
            assert relayed["from"] == "p1"
            assert relayed["ops"][0]["objects"][0]["id"] == "shape-1"

    objects = run_db(bare_app, lambda db: store.get_session_objects(db, session_id))
    objects_by_id = {obj["id"]: obj for obj in objects}
    assert "shape-1" in objects_by_id
    assert objects_by_id["shape-1"]["label"] == "New Service"


def test_cursor_update_is_broadcast_as_presence(bare_client):
    session_id = bare_client.post("/sessions").json()["sessionId"]

    with bare_client.websocket_connect(f"/ws/{session_id}") as ws1:
        ws1.send_json(_join_event(session_id, "p1"))
        ws1.receive_json()  # snapshot

        with bare_client.websocket_connect(f"/ws/{session_id}") as ws2:
            ws2.send_json(_join_event(session_id, "p2"))
            ws2.receive_json()  # snapshot
            ws1.receive_json()  # presence: p2 joined

            ws2.send_json(
                {
                    "type": "cursor",
                    "sessionId": session_id,
                    "from": "p2",
                    "cursor": {"x": 42, "y": 7},
                }
            )

            presence = ws1.receive_json()
            assert presence["type"] == "presence"
            p2 = next(p for p in presence["participants"] if p["id"] == "p2")
            assert p2["cursor"] == {"x": 42, "y": 7}


def test_disconnect_removes_participant_and_notifies_remaining(bare_client):
    session_id = bare_client.post("/sessions").json()["sessionId"]

    with bare_client.websocket_connect(f"/ws/{session_id}") as ws1:
        ws1.send_json(_join_event(session_id, "p1"))
        ws1.receive_json()  # snapshot

        with bare_client.websocket_connect(f"/ws/{session_id}") as ws2:
            ws2.send_json(_join_event(session_id, "p2"))
            ws2.receive_json()  # snapshot
            ws1.receive_json()  # presence: p2 joined

        # ws2's `with` block exited -> disconnected.
        presence = ws1.receive_json()
        assert presence["type"] == "presence"
        # p1 is alone again now — "others" list is empty.
        assert presence["participants"] == []
