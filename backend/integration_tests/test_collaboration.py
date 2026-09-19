"""Real-time collaboration between live WebSocket participants."""

from __future__ import annotations

import pytest
from websockets.exceptions import ConnectionClosed

from .collab import Participant, shape, unique


def test_joining_the_seeded_demo_board_shows_its_diagram(stack):
    with Participant(stack, "demo", "p1") as p:
        snapshot = p.join()

    objects = {o["id"]: o for o in snapshot["objects"]}
    assert len(objects) == 12
    assert objects["seed-lb"]["label"] == "Load Balancer"
    # Connector endpoints use the reserved word "from"; make sure it survives the
    # trip through Postgres JSONB and back out over the wire.
    assert objects["seed-edge-client-lb"]["from"] == {"objectId": "seed-client"}
    assert objects["seed-edge-client-lb"]["to"] == {"objectId": "seed-lb"}


def test_a_new_session_starts_empty(stack, session_id):
    with Participant(stack, session_id, "p1") as p:
        snapshot = p.join()
    assert snapshot["objects"] == []
    assert snapshot["participants"] == []  # "others only" -- nobody else is here


def test_an_unknown_session_is_refused(stack):
    with Participant(stack, "no-such-session", "p1") as p:
        with pytest.raises(ConnectionClosed) as closed:
            p.recv()
    assert closed.value.rcvd.code == 4404


def test_the_first_message_must_be_a_join(stack, session_id):
    with Participant(stack, session_id, "p1") as p:
        p.cursor(1, 2)
        with pytest.raises(ConnectionClosed) as closed:
            p.recv()
    assert closed.value.rcvd.code == 4400


def test_participants_see_each_other_but_never_themselves(stack, session_id):
    with Participant(stack, session_id, "alice", "interviewer") as alice:
        assert alice.join()["participants"] == []

        with Participant(stack, session_id, "bob") as bob:
            # Bob is told about Alice in his snapshot...
            assert [p["id"] for p in bob.join()["participants"]] == ["alice"]
            # ...and Alice is told about Bob.
            presence = alice.recv_until("presence")
            assert [p["id"] for p in presence["participants"]] == ["bob"]
            assert presence["participants"][0]["role"] == "candidate"


def test_edits_are_relayed_to_the_other_participant(stack, session_id):
    with Participant(stack, session_id, "alice") as alice, Participant(stack, session_id, "bob") as bob:
        alice.join()
        bob.join()
        alice.recv_until("presence")

        obj = unique("s")
        alice.add(shape(obj, "API"))
        added = bob.recv_until("ops")
        assert added["from"] == "alice"
        assert added["ops"][0]["objects"][0]["label"] == "API"

        alice.update(obj, x=250, label="Gateway")
        updated = bob.recv_until("ops")
        assert updated["ops"][0]["updates"][0] == {"id": obj, "patch": {"x": 250, "label": "Gateway"}}

        alice.delete(obj)
        assert bob.recv_until("ops")["ops"][0] == {"op": "delete", "ids": [obj]}


def test_a_participant_is_not_sent_an_echo_of_their_own_edits(stack, session_id):
    with Participant(stack, session_id, "alice") as alice, Participant(stack, session_id, "bob") as bob:
        alice.join()
        bob.join()
        alice.recv_until("presence")

        alice.add(shape(unique("s")))
        bob.recv_until("ops")  # the server has processed it by now
        alice.cursor(1, 1)
        bob.recv_until("presence")

        # Everything Alice would have been sent is already queued; it must be
        # nothing but presence.
        with pytest.raises(TimeoutError):
            alice.recv_until("ops", timeout=1)


def test_cursor_and_viewport_movement_reaches_the_other_participant(stack, session_id):
    with Participant(stack, session_id, "alice") as alice, Participant(stack, session_id, "bob") as bob:
        alice.join()
        bob.join()
        alice.recv_until("presence")

        bob.cursor(42, 7)
        seen = alice.recv_until("presence")["participants"][0]
        assert seen["id"] == "bob" and seen["cursor"] == {"x": 42, "y": 7}

        bob.viewport(100, 200, 1280, 720)
        seen = alice.recv_until("presence")["participants"][0]
        assert seen["viewport"] == {"x": 100, "y": 200, "width": 1280, "height": 720}


def test_leaving_updates_everyone_still_present(stack, session_id):
    with Participant(stack, session_id, "alice") as alice, Participant(stack, session_id, "bob") as bob:
        alice.join()
        bob.join()
        alice.recv_until("presence")

        bob.leave()
        assert alice.recv_until("presence")["participants"] == []


def test_a_dropped_connection_is_treated_as_leaving(stack, session_id):
    with Participant(stack, session_id, "alice") as alice:
        alice.join()
        bob = Participant(stack, session_id, "bob")
        bob.join()
        alice.recv_until("presence")

        bob.close()  # no `leave` message: the tab was simply closed
        assert alice.recv_until("presence")["participants"] == []


def test_a_malformed_message_does_not_drop_the_connection(stack, session_id):
    with Participant(stack, session_id, "alice") as alice, Participant(stack, session_id, "bob") as bob:
        alice.join()
        bob.join()
        alice.recv_until("presence")

        alice.send({"type": "definitely-not-a-real-event"})
        alice.send({"type": "ops", "sessionId": session_id, "from": "alice", "ops": "nonsense"})
        alice.cursor(5, 5)  # still connected, and still understood
        assert bob.recv_until("presence")["participants"][0]["cursor"] == {"x": 5, "y": 5}


def test_sessions_are_isolated_from_each_other(stack):
    one, two = stack.new_session(), stack.new_session()
    with Participant(stack, one, "alice") as alice, Participant(stack, two, "bob") as bob:
        alice.join()
        bob.join()
        alice.add(shape(unique("only-in-one")))
        alice.cursor(1, 1)
        with pytest.raises(TimeoutError):
            bob.recv_until("ops", timeout=1.5)
        with pytest.raises(TimeoutError):
            bob.recv_until("presence", timeout=0.5)
