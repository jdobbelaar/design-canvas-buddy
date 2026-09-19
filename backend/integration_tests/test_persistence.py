"""What participants draw is written to Postgres and comes back out of it."""

from __future__ import annotations

import random

from .collab import Participant, drawn_and_synced, shape, snapshot_ids, unique


def test_a_drawing_is_stored_in_postgres_and_shown_to_the_next_person(stack, session_id):
    a, b = unique("a"), unique("b")
    drawn_and_synced(stack, session_id, lambda p: p.add(shape(a, "Client"), shape(b, "Server", x=300)))

    # Everyone has left; the session lives only in the database now.
    assert stack.psql(
        f"select count(*) from board_objects where session_id='{session_id}' "
        f"and id in ('{a}','{b}')") == "2"
    assert stack.psql(f"select jsonb_typeof(data) from board_objects where id='{b}'") == "object"
    assert stack.psql(f"select data->>'label' from board_objects where id='{b}'") == "Server"
    assert snapshot_ids(stack, session_id)[:2] == [a, b]


def test_updates_are_persisted_as_a_merge(stack, session_id):
    a = unique("a")
    drawn_and_synced(stack, session_id, lambda p: (
        p.add(shape(a, "Old", x=1, y=2)), p.update(a, label="New", x=99)))

    with Participant(stack, session_id, "reader") as reader:
        objects = {o["id"]: o for o in reader.join()["objects"]}
    assert objects[a]["label"] == "New" and objects[a]["x"] == 99
    assert objects[a]["y"] == 2  # untouched fields survive the patch


def test_deleted_objects_are_removed_from_postgres(stack, session_id):
    keep, drop = unique("keep"), unique("drop")
    drawn_and_synced(stack, session_id, lambda p: (p.add(shape(keep), shape(drop)), p.delete(drop)))

    assert stack.psql(f"select count(*) from board_objects where id='{drop}'") == "0"
    ids = snapshot_ids(stack, session_id)
    assert keep in ids and drop not in ids


def test_stacking_order_survives_heavy_editing(stack, session_id):
    # The order objects are listed in IS the on-screen z-order. Postgres moves a
    # row whenever it is updated, and dragging updates constantly, so without an
    # explicit ORDER BY the stacking used to reshuffle for whoever joined next.
    # Chunky rows (like freehand strokes) spread the table across many pages,
    # which is what makes it show up. See tests/test_store_ordering.py.
    ids = [f"o{i:03d}-{session_id}" for i in range(60)]
    rng = random.Random(7)

    def draw(alice: Participant) -> None:
        for object_id in ids:
            alice.add(shape(object_id, padding="x" * 600))
        for step in range(400):
            alice.update(rng.choice(ids), x=step)

    drawn_and_synced(stack, session_id, draw)

    assert snapshot_ids(stack, session_id)[:60] == ids


def test_another_session_cannot_overwrite_or_take_an_object(stack):
    victim, attacker = stack.new_session(), stack.new_session()
    target = unique("target")
    drawn_and_synced(stack, victim, lambda p: p.add(shape(target, "mine")))

    # The attacker reuses the victim's object id: to add it, then to edit it.
    drawn_and_synced(stack, attacker, lambda p: (
        p.add(shape(target, "hijacked")), p.update(target, label="hijacked", x=999)))

    with Participant(stack, victim, "reader") as reader:
        objects = {o["id"]: o for o in reader.join()["objects"]}
    assert objects[target]["label"] == "mine"
    assert objects[target]["x"] == 0
    assert stack.psql(f"select session_id from board_objects where id='{target}'") == victim
