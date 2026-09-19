"""Data and service survive restarts. These disrupt the shared stack, so they
run last (files are collected alphabetically) and each waits until the stack is
healthy again before returning."""

from __future__ import annotations

from app.seed import SEED_USER_EMAIL, SEED_USER_PASSWORD

from .collab import Participant, drawn_and_synced, shape, snapshot_ids, unique
from .conftest import wait_until


def test_data_survives_restarting_the_app(stack, session_id):
    a, b = unique("a"), unique("b")
    drawn_and_synced(stack, session_id, lambda p: p.add(shape(a, "Client"), shape(b, "Server")))

    stack.compose("restart", "app")
    stack.wait_for_api()

    assert snapshot_ids(stack, session_id)[:2] == [a, b]
    # ...and the restarted app accepts live collaboration again.
    with Participant(stack, session_id, "carol") as carol:
        assert carol.join()["objects"]


def test_restarting_the_app_does_not_reseed_the_demo_data(stack):
    # Seeding is idempotent; the database outlives every app container.
    stack.compose("restart", "app")
    stack.wait_for_api()

    assert stack.psql("select count(*) from users where email='demo@example.com'") == "1"
    assert stack.psql("select count(*) from board_objects where session_id='demo'") == "12"
    assert stack.http.post(
        "/auth/login", json={"email": SEED_USER_EMAIL, "password": SEED_USER_PASSWORD}
    ).status_code == 200


def test_data_survives_taking_the_whole_stack_down_and_up(stack, session_id):
    # `down` removes the containers and network but keeps the named volume.
    kept = unique("persisted")
    drawn_and_synced(stack, session_id, lambda p: p.add(shape(kept, "Still here")))

    stack.down()
    assert stack.services() == {}, "down should have removed the containers"
    stack.up()
    stack.wait_for_api()

    assert kept in snapshot_ids(stack, session_id)


def test_the_app_recovers_when_postgres_restarts_underneath_it(stack, session_id):
    before = unique("before")
    drawn_and_synced(stack, session_id, lambda p: p.add(shape(before, "Before the outage")))

    stack.compose("restart", "postgres")
    stack.compose("up", "-d", "--wait", "--wait-timeout", "120")  # wait for healthy again

    # The app's pooled connections all died with the old server. It must notice
    # and reconnect on its own -- without anyone restarting it.
    wait_until(
        lambda: stack.http.post("/sessions").status_code == 201,
        timeout=30,
        what="the app to reconnect to the restarted Postgres",
    )
    assert before in snapshot_ids(stack, session_id)

    # New writes work too, and reach the (restarted) database.
    after = unique("after")
    drawn_and_synced(stack, session_id, lambda p: p.add(shape(after, "After the outage")))
    assert after in snapshot_ids(stack, session_id)
