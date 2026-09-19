"""REST endpoints and auth, against a real Postgres."""

from __future__ import annotations

import uuid

import pytest

from app.seed import SEED_USER_EMAIL, SEED_USER_PASSWORD


def _email() -> str:
    return f"user-{uuid.uuid4().hex[:8]}@example.com"


def test_each_created_session_gets_a_distinct_id(stack):
    ids = {stack.new_session() for _ in range(5)}
    assert len(ids) == 5


def test_creating_a_session_needs_no_account(stack):
    # Link-based access: no Authorization header is sent at all.
    assert stack.http.post("/sessions").status_code == 201


def test_register_then_login_then_me(stack):
    email = _email()
    registered = stack.http.post(
        "/auth/register", json={"email": email, "password": "correct horse", "name": "Ada"})
    assert registered.status_code == 201
    assert registered.json()["user"]["email"] == email

    login = stack.http.post("/auth/login", json={"email": email, "password": "correct horse"})
    assert login.status_code == 200

    me = stack.http.get(
        "/auth/me", headers={"Authorization": f"Bearer {login.json()['access_token']}"})
    assert me.status_code == 200
    assert me.json()["email"] == email
    assert me.json()["name"] == "Ada"


def test_the_seeded_demo_user_can_log_in(stack):
    # Seeding ran against Postgres, and the password hash survived the round trip.
    response = stack.http.post(
        "/auth/login", json={"email": SEED_USER_EMAIL, "password": SEED_USER_PASSWORD})
    assert response.status_code == 200


def test_bad_credentials_are_rejected(stack):
    email = _email()
    stack.http.post("/auth/register", json={"email": email, "password": "correct horse"})
    assert stack.http.post(
        "/auth/login", json={"email": email, "password": "wrong password"}).status_code == 401
    assert stack.http.post(
        "/auth/login", json={"email": _email(), "password": "correct horse"}).status_code == 401


def test_protected_endpoint_requires_a_valid_token(stack):
    assert stack.http.get("/auth/me").status_code == 401
    assert stack.http.get(
        "/auth/me", headers={"Authorization": "Bearer not-a-real-token"}).status_code == 401


def test_a_too_short_password_is_a_validation_error(stack):
    assert stack.http.post(
        "/auth/register", json={"email": _email(), "password": "short"}).status_code == 422


def test_duplicate_email_is_a_conflict_regardless_of_case(stack):
    # SQLite and Postgres collate text differently; case-insensitivity is done
    # in the application, so it has to hold on Postgres too.
    local = uuid.uuid4().hex[:8]
    first = stack.http.post(
        "/auth/register", json={"email": f"{local}@example.com", "password": "correct horse"})
    assert first.status_code == 201

    same_address_shouting = stack.http.post(
        "/auth/register", json={"email": f"{local}@EXAMPLE.com", "password": "correct horse"})
    assert same_address_shouting.status_code == 409


def test_passwords_are_stored_as_bcrypt_hashes_not_plaintext(stack):
    email = _email()
    stack.http.post("/auth/register", json={"email": email, "password": "correct horse"})
    stored = stack.psql(f"select password_hash from users where email='{email}'")
    assert stored.startswith("$2")
    assert "correct horse" not in stored


@pytest.mark.parametrize("bad", [{"email": "not-an-email", "password": "correct horse"}, {}])
def test_malformed_registration_is_rejected(stack, bad):
    assert stack.http.post("/auth/register", json=bad).status_code == 422
