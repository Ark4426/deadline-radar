"""Shared pytest fixtures."""

from __future__ import annotations

import pytest

from backend import create_app
from backend.security import clear_failed_logins


@pytest.fixture(autouse=True)
def reset_rate_limits():
    clear_failed_logins()
    yield
    clear_failed_logins()


@pytest.fixture()
def app(tmp_path):
    application = create_app(
        {
            "TESTING": True,
            "SECRET_KEY": "test-secret-key",
            "DATABASE": str(tmp_path / "test.db"),
            "MODEL_PATH": str(tmp_path / "missing-model.joblib"),
        }
    )
    yield application


@pytest.fixture()
def client(app):
    return app.test_client()


@pytest.fixture()
def register(client):
    def _register(
        email: str = "ada@example.com",
        password: str = "correct-horse",
        display_name: str = "Ada Lovelace",
    ):
        response = client.post(
            "/api/auth/register",
            json={"email": email, "password": password, "display_name": display_name},
        )
        assert response.status_code == 201, response.get_json()
        return response.get_json()

    return _register


@pytest.fixture()
def auth_headers(client, register):
    payload = register()

    def _headers() -> dict[str, str]:
        return {"X-CSRF-Token": payload["csrf_token"]}

    _headers.user = payload["user"]  # type: ignore[attr-defined]
    _headers.csrf_token = payload["csrf_token"]  # type: ignore[attr-defined]
    return _headers
