from __future__ import annotations

import pytest

from app.db import create_engine, normalize_database_url


def _render(url: str) -> str:
    return normalize_database_url(url).render_as_string(hide_password=False)


@pytest.mark.parametrize(
    ("given", "expected"),
    [
        # Bare URLs, as Heroku/Neon/RDS/most docs hand them out, name no driver.
        ("postgres://u:p@host:5432/db", "postgresql+asyncpg://u:p@host:5432/db"),
        ("postgresql://u:p@host/db", "postgresql+asyncpg://u:p@host/db"),
        ("sqlite:///./app.db", "sqlite+aiosqlite:///./app.db"),
        # An explicit driver is never overridden.
        ("postgresql+asyncpg://u:p@host/db", "postgresql+asyncpg://u:p@host/db"),
        ("sqlite+aiosqlite:///:memory:", "sqlite+aiosqlite:///:memory:"),
    ],
)
def test_bare_urls_get_the_async_driver(given, expected):
    assert _render(given) == expected


def test_libpq_sslmode_becomes_asyncpgs_ssl():
    # asyncpg would reject `sslmode` outright ("unexpected keyword argument").
    assert (
        _render("postgres://u:p@host/db?sslmode=require")
        == "postgresql+asyncpg://u:p@host/db?ssl=require"
    )


def test_other_query_parameters_are_preserved():
    rendered = _render("postgres://u:p@host/db?sslmode=verify-full&connect_timeout=5")
    assert "ssl=verify-full" in rendered
    assert "connect_timeout=5" in rendered
    assert "sslmode" not in rendered


def test_sslmode_is_left_alone_for_other_drivers():
    # Only asyncpg renames it; psycopg spells it `sslmode` natively.
    assert "sslmode=require" in _render("postgresql+psycopg://u:p@host/db?sslmode=require")


def test_password_with_special_characters_survives():
    # str(url) would mask the password as ***; normalizing must not lose it.
    url = normalize_database_url("postgres://u:p%40ss%2Fw%3Ard@host/db")
    assert url.password == "p@ss/w:rd"
    assert url.render_as_string(hide_password=False).endswith("u:p%40ss%2Fw%3Ard@host/db")


def test_engine_keeps_the_password_and_uses_the_async_driver():
    engine = create_engine("postgres://u:s3cret@localhost:5432/db")
    assert engine.url.drivername == "postgresql+asyncpg"
    assert engine.url.password == "s3cret"


def test_server_databases_get_connection_health_checks_but_sqlite_does_not():
    assert create_engine("postgresql://u:p@localhost/db").pool._pre_ping is True
    assert create_engine("sqlite+aiosqlite:///:memory:").pool._pre_ping is False
