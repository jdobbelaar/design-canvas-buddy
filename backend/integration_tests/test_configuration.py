"""The environment overrides documented in docker-compose.yaml really work."""

from __future__ import annotations

from .conftest import running_stack


def test_database_credentials_can_be_overridden():
    # The app's DATABASE_URL is assembled from the same variables that
    # initialise Postgres, so a mistake in the interpolation would leave the app
    # unable to log in -- or quietly using the defaults instead.
    custom = {"POSTGRES_USER": "alice", "POSTGRES_PASSWORD": "s3cretpw", "POSTGRES_DB": "appdb"}

    with running_stack(custom) as stack:
        session_id = stack.new_session()  # needs a working app -> database connection

        assert stack.psql(f"select count(*) from board_sessions where id='{session_id}'") == "1"
        assert stack.psql("select current_user || '@' || current_database()") == "alice@appdb"
        # The defaults are not silently created alongside the overrides.
        assert stack.psql("select count(*) from pg_roles where rolname='designcanvas'") == "0"
