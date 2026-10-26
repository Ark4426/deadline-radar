"""Authentication, session, and CSRF tests."""

from __future__ import annotations

import json

import pytest

from backend.database import get_db


def test_register_creates_user_and_default_settings(app, client):
    response = client.post(
        "/api/auth/register",
        json={
            "email": "ada@example.com",
            "password": "correct-horse",
            "display_name": "Ada Lovelace",
        },
    )
    assert response.status_code == 201
    payload = response.get_json()
    assert payload["user"]["email"] == "ada@example.com"
    assert payload["user"]["display_name"] == "Ada Lovelace"
    assert payload["csrf_token"]
    assert "password" not in json.dumps(payload).lower()

    with app.app_context():
        user = get_db().execute("SELECT * FROM users WHERE email = ?", ("ada@example.com",)).fetchone()
        settings = get_db().execute(
            "SELECT * FROM settings WHERE user_id = ?", (user["id"],)
        ).fetchone()
        assert user["password_hash"] != "correct-horse"
        assert settings["auto_priority"] == 1
        assert settings["theme"] == "dark"
        assert "urgent" in settings["high_keywords"]


def test_register_rejects_duplicate_email_case_insensitively(client, register):
    register(email="ada@example.com")
    fresh = client.application.test_client()
    response = fresh.post(
        "/api/auth/register",
        json={
            "email": "ADA@example.com",
            "password": "correct-horse",
            "display_name": "Another Ada",
        },
    )
    assert response.status_code == 409
    assert "already exists" in response.get_json()["error"]


@pytest.mark.parametrize(
    "payload, expected_error",
    [
        ({"email": "not-an-email", "password": "long-enough", "display_name": "Ada"}, "email"),
        ({"email": "ada@example.com", "password": "short", "display_name": "Ada"}, "Password"),
        ({"email": "ada@example.com", "password": "long-enough", "display_name": "A"}, "Display"),
    ],
)
def test_register_validates_input(client, payload, expected_error):
    response = client.post("/api/auth/register", json=payload)
    assert response.status_code == 400
    assert expected_error.lower() in response.get_json()["error"].lower()


def test_login_me_and_logout(client, register):
    payload = register()
    headers = {"X-CSRF-Token": payload["csrf_token"]}

    me = client.get("/api/auth/me")
    assert me.status_code == 200
    assert me.get_json()["user"]["display_name"] == "Ada Lovelace"
    assert me.get_json()["csrf_token"] == payload["csrf_token"]

    logout = client.post("/api/auth/logout", headers=headers)
    assert logout.status_code == 200

    after = client.get("/api/auth/me")
    assert after.status_code == 401


def test_login_rejects_bad_password(client, register):
    payload = register()
    client.post("/api/auth/logout", headers={"X-CSRF-Token": payload["csrf_token"]})
    response = client.post(
        "/api/auth/login",
        json={"email": "ada@example.com", "password": "not-the-password"},
    )
    assert response.status_code == 401
    assert response.get_json()["error"] == "Email or password is incorrect."


def test_login_sets_a_fresh_session(client, register):
    register()
    fresh = client.application.test_client()
    response = fresh.post(
        "/api/auth/login",
        json={"email": "ada@example.com", "password": "correct-horse"},
    )
    assert response.status_code == 200
    assert response.get_json()["user"]["email"] == "ada@example.com"
    assert fresh.get("/api/auth/me").status_code == 200


def test_login_is_rate_limited(client):
    for attempt in range(6):
        response = client.post(
            "/api/auth/login",
            json={"email": "target@example.com", "password": f"wrong-{attempt}"},
        )
        assert response.status_code == 401

    blocked = client.post(
        "/api/auth/login",
        json={"email": "target@example.com", "password": "wrong-again"},
    )
    assert blocked.status_code == 429
    assert "Too many attempts" in blocked.get_json()["error"]


def test_mutating_requests_require_csrf_token(client, register):
    register()
    response = client.post("/api/auth/logout")
    assert response.status_code == 403
    assert client.get("/api/auth/me").status_code == 200


def test_cross_origin_mutation_is_rejected(client, register):
    register()
    response = client.post(
        "/api/auth/logout",
        headers={"Origin": "https://evil.example", "X-CSRF-Token": "anything"},
    )
    assert response.status_code == 403
    assert "Cross-origin" in response.get_json()["error"]


def test_protected_endpoint_returns_401_without_session(client):
    response = client.get("/api/auth/me")
    assert response.status_code == 401
    assert response.get_json()["error"] == "Not signed in."
