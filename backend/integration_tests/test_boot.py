"""The stack comes up correctly, and is wired the way docker-compose.yaml says."""

from __future__ import annotations


def test_both_services_are_running_and_healthy(stack):
    services = stack.services()
    assert set(services) == {"app", "postgres"}
    for name, row in services.items():
        assert row["State"] == "running", name
        assert row["Health"] == "healthy", name


def test_app_did_not_crash_while_waiting_for_postgres(stack):
    # The app creates its tables on startup and doesn't retry a refused
    # connection. On a fresh volume Postgres takes seconds to initialise, so if
    # depends_on didn't wait for its healthcheck the app would have crashed and
    # been restarted by `restart: unless-stopped`.
    assert stack.inspect("app")["RestartCount"] == 0


def test_app_started_cleanly(stack):
    logs = stack.logs("app")
    assert "Application startup complete" in logs
    assert "Traceback" not in logs


def test_postgres_is_not_published_to_the_host(stack):
    # Deliberate (see the comment in docker-compose.yaml): it can't clash with
    # a Postgres already on the host, and only the app can reach it.
    inspected = stack.inspect("postgres")
    assert inspected["HostConfig"]["PortBindings"] in ({}, None)
    assert all(bindings is None for bindings in inspected["NetworkSettings"]["Ports"].values())


def test_the_app_is_on_the_port_the_compose_file_maps(stack):
    bindings = stack.inspect("app")["NetworkSettings"]["Ports"]["8000/tcp"]
    assert {b["HostPort"] for b in bindings} == {str(stack.port)}


def test_api_docs_are_served(stack):
    spec = stack.http.get("/openapi.json").json()
    assert "/sessions" in spec["paths"]


def test_the_app_really_uses_postgres(stack):
    # Guards against a silent fall-back to SQLite: the schema must exist in
    # Postgres, with the JSONB column type only the Postgres dialect produces.
    tables = set(stack.psql(
        "select tablename from pg_tables where schemaname='public'").splitlines())
    assert {"users", "tokens", "board_sessions", "board_objects"} <= tables
    assert stack.psql(
        "select data_type from information_schema.columns "
        "where table_name='board_objects' and column_name='data'") == "jsonb"


def test_data_written_through_the_api_lands_in_postgres(stack):
    before = int(stack.psql("select count(*) from board_sessions"))
    session_id = stack.new_session()
    after = int(stack.psql("select count(*) from board_sessions"))
    assert after == before + 1
    assert stack.psql(f"select count(*) from board_sessions where id='{session_id}'") == "1"


def test_demo_data_was_seeded_exactly_once(stack):
    assert stack.psql("select count(*) from users where email='demo@example.com'") == "1"
    assert stack.psql("select count(*) from board_objects where session_id='demo'") == "12"
