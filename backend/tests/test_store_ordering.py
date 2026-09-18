"""Board-object order is the z-order on screen, so it must survive updates.

The frontend renders shapes in the order a snapshot lists them. SQLite happens
to return rows in insertion order, but Postgres does not: an UPDATE writes a
new row version, and once a table spans several pages the row can come back
somewhere else. These tests exercise ordering on whichever database
TEST_DATABASE_URL selects (see conftest.py).
"""

from __future__ import annotations

import asyncio
import random

from sqlalchemy import inspect, text

from app import store
from app.db import init_db
from app.seed import SEED_SESSION_ID

from .conftest import run_db


def _order(app, session_id):
    objects = run_db(app, lambda db: store.get_session_objects(db, session_id))
    return [o["id"] for o in objects]


def _add_one_at_a_time(app, session_id, ids, payload=""):
    for object_id in ids:
        run_db(
            app,
            lambda db, i=object_id: store.add_objects(
                db, session_id, [{"id": i, "type": "text", "x": 0, "text": payload}]
            ),
        )


def test_order_survives_many_updates(bare_app):
    session = run_db(bare_app, store.create_session)
    ids = [f"o{i:03d}" for i in range(60)]
    # Chunky rows (like freehand strokes) so the table spans many pages --
    # that's what makes Postgres move updated rows.
    _add_one_at_a_time(bare_app, session.id, ids, payload="x" * 600)

    rng = random.Random(1)
    for step in range(600):
        target = rng.choice(ids)
        run_db(
            bare_app,
            lambda db, t=target, s=step: store.update_objects(db, session.id, [(t, {"x": s})]),
        )

    assert _order(bare_app, session.id) == ids


def test_objects_added_in_one_op_keep_their_order(bare_app):
    session = run_db(bare_app, store.create_session)
    ids = ["zebra", "apple", "mango", "banana"]  # deliberately not alphabetical
    run_db(
        bare_app,
        lambda db: store.add_objects(
            db, session.id, [{"id": i, "type": "text", "x": 0, "text": ""} for i in ids]
        ),
    )
    assert _order(bare_app, session.id) == ids


def test_readding_an_existing_object_does_not_move_it(bare_app):
    session = run_db(bare_app, store.create_session)
    _add_one_at_a_time(bare_app, session.id, ["a", "b", "c"])
    run_db(
        bare_app,
        lambda db: store.add_objects(db, session.id, [{"id": "a", "type": "text", "x": 5, "text": ""}]),
    )
    objects = run_db(bare_app, lambda db: store.get_session_objects(db, session.id))
    assert [o["id"] for o in objects] == ["a", "b", "c"]
    assert objects[0]["x"] == 5  # ...but its contents did update


def test_cannot_overwrite_another_sessions_object(bare_app):
    first = run_db(bare_app, store.create_session)
    second = run_db(bare_app, store.create_session)
    _add_one_at_a_time(bare_app, first.id, ["shared-id"], payload="mine")

    run_db(
        bare_app,
        lambda db: store.add_objects(
            db, second.id, [{"id": "shared-id", "type": "text", "x": 0, "text": "hijacked"}]
        ),
    )

    objects = run_db(bare_app, lambda db: store.get_session_objects(db, first.id))
    assert [o["text"] for o in objects] == ["mine"]
    assert _order(bare_app, second.id) == []


def test_seed_board_keeps_its_authored_order(app):
    ids = _order(app, SEED_SESSION_ID)
    assert ids[0] == "seed-client"
    assert ids.index("seed-lb") < ids.index("seed-note") < ids.index("seed-edge-client-lb")


def test_existing_database_without_the_order_column_is_upgraded(bare_app):
    """Databases created before ordering existed have no `seq` column."""

    async def _downgrade_then_upgrade():
        engine = bare_app.state.db_engine
        async with engine.begin() as conn:
            await conn.execute(text("ALTER TABLE board_objects DROP COLUMN seq"))
            cols = await conn.run_sync(lambda c: [x["name"] for x in inspect(c).get_columns("board_objects")])
            assert "seq" not in cols
        await init_db(engine)
        async with engine.begin() as conn:
            return await conn.run_sync(lambda c: [x["name"] for x in inspect(c).get_columns("board_objects")])

    assert "seq" in asyncio.run(_downgrade_then_upgrade())

    session = run_db(bare_app, store.create_session)
    _add_one_at_a_time(bare_app, session.id, ["b", "a"])
    assert _order(bare_app, session.id) == ["b", "a"]
