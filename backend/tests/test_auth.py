from __future__ import annotations

from app import store
from app.seed import SEED_USER_EMAIL, SEED_USER_PASSWORD

from .conftest import run_db


def test_register_returns_token_and_user(bare_client):
    resp = bare_client.post(
        "/auth/register",
        json={"email": "new@example.com", "password": "hunter22", "name": "New User"},
    )
    assert resp.status_code == 201
    body = resp.json()
    assert body["token_type"] == "bearer"
    assert body["access_token"]
    assert body["user"]["email"] == "new@example.com"
    assert body["user"]["name"] == "New User"
    assert "id" in body["user"]


def test_register_duplicate_email_rejected(bare_client):
    payload = {"email": "dup@example.com", "password": "hunter22"}
    first = bare_client.post("/auth/register", json=payload)
    assert first.status_code == 201

    second = bare_client.post("/auth/register", json=payload)
    assert second.status_code == 409


def test_register_password_too_short_rejected(bare_client):
    resp = bare_client.post(
        "/auth/register", json={"email": "short@example.com", "password": "short"}
    )
    assert resp.status_code == 422


def test_passwords_are_hashed_not_stored_in_plaintext(bare_app, bare_client):
    bare_client.post(
        "/auth/register", json={"email": "hash@example.com", "password": "hunter22"}
    )
    user = run_db(bare_app, lambda db: store.get_user_by_email(db, "hash@example.com"))
    assert user is not None
    assert user.password_hash != "hunter22"
    assert user.password_hash.startswith("$2b$")


def test_login_with_correct_credentials_succeeds(client):
    resp = client.post(
        "/auth/login", json={"email": SEED_USER_EMAIL, "password": SEED_USER_PASSWORD}
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["access_token"]
    assert body["user"]["email"] == SEED_USER_EMAIL


def test_login_with_wrong_password_rejected(client):
    resp = client.post(
        "/auth/login", json={"email": SEED_USER_EMAIL, "password": "wrong-password"}
    )
    assert resp.status_code == 401


def test_login_with_unknown_email_rejected(client):
    resp = client.post(
        "/auth/login", json={"email": "nobody@example.com", "password": "whatever1"}
    )
    assert resp.status_code == 401


def test_me_requires_bearer_token(client):
    resp = client.get("/auth/me")
    assert resp.status_code == 401


def test_me_rejects_invalid_token(client):
    resp = client.get("/auth/me", headers={"Authorization": "Bearer not-a-real-token"})
    assert resp.status_code == 401


def test_me_returns_current_user_for_valid_token(client):
    login = client.post(
        "/auth/login", json={"email": SEED_USER_EMAIL, "password": SEED_USER_PASSWORD}
    )
    token = login.json()["access_token"]

    resp = client.get("/auth/me", headers={"Authorization": f"Bearer {token}"})
    assert resp.status_code == 200
    assert resp.json()["email"] == SEED_USER_EMAIL


def test_two_logins_issue_different_tokens(client):
    first = client.post(
        "/auth/login", json={"email": SEED_USER_EMAIL, "password": SEED_USER_PASSWORD}
    )
    second = client.post(
        "/auth/login", json={"email": SEED_USER_EMAIL, "password": SEED_USER_PASSWORD}
    )
    assert first.json()["access_token"] != second.json()["access_token"]
