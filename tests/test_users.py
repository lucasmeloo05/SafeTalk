from datetime import date

import pytest
from fastapi.testclient import TestClient


def test_registers_user_and_creates_default_privacy_settings(
    client: TestClient,
    db_session,
):
    response = client.post(
        "/users/",
        json={
            "username": "ana_teste",
            "email": "ana@example.com",
            "password": "Senha-Teste-123!",
            "birth_date": "1997-05-20",
        },
    )

    assert response.status_code == 201
    body = response.json()
    assert body["username"] == "ana_teste"
    assert body["email"] == "ana@example.com"
    assert body["birth_date"] == "1997-05-20"
    assert body["is_active"] is True
    assert body["is_verified"] is False
    assert "password" not in body
    assert "password_hash" not in body

    from app.models import UserPrivacySettings

    settings = db_session.get(UserPrivacySettings, body["id"])
    assert settings is not None
    assert settings.allow_messages_from_strangers is False


@pytest.mark.parametrize("duplicate_email", [False, True])
def test_duplicate_username_or_email_returns_conflict(
    client: TestClient,
    create_user,
    duplicate_email: bool,
):
    create_user(username="original", email="original@example.com")
    response = client.post(
        "/users/",
        json={
            "username": "original" if not duplicate_email else "different",
            "email": "different@example.com" if not duplicate_email else "original@example.com",
            "password": "Senha-Teste-123!",
            "birth_date": "1990-01-01",
        },
    )

    assert response.status_code == 409


@pytest.mark.parametrize("login_field", ["username", "email"])
def test_login_accepts_username_and_email(
    client: TestClient,
    create_user,
    login_field: str,
):
    user = create_user(username="login_teste", email="login@example.com")

    response = client.post(
        "/users/login",
        json={"login": user[login_field], "password": user["password"]},
    )

    assert response.status_code == 200
    assert response.json()["token_type"] == "bearer"
    assert response.json()["access_token"]


def test_login_rejects_wrong_password(client: TestClient, create_user):
    user = create_user()

    response = client.post(
        "/users/login",
        json={"login": user["username"], "password": "senha-incorreta"},
    )

    assert response.status_code == 401


def test_jwt_authentication_returns_current_profile(
    client: TestClient,
    create_user,
    auth_headers,
):
    user = create_user()

    response = client.get("/users/me", headers=auth_headers(user))

    assert response.status_code == 200
    assert response.json()["id"] == user["id"]
    assert response.json()["username"] == user["username"]


@pytest.mark.parametrize("authorization", [None, "Bearer invalid-token"])
def test_profile_rejects_missing_or_invalid_jwt(
    client: TestClient,
    authorization: str | None,
):
    headers = {} if authorization is None else {"Authorization": authorization}

    response = client.get("/users/me", headers=headers)

    assert response.status_code == 401


def test_registration_rejects_invalid_username_and_future_birth_date(
    client: TestClient,
):
    invalid_username = client.post(
        "/users/",
        json={
            "username": "nome inválido",
            "email": "valid@example.com",
            "password": "Senha-Teste-123!",
            "birth_date": "1990-01-01",
        },
    )
    future_birth_date = client.post(
        "/users/",
        json={
            "username": "valid_name",
            "email": "future@example.com",
            "password": "Senha-Teste-123!",
            "birth_date": date(date.today().year + 1, 1, 1).isoformat(),
        },
    )

    assert invalid_username.status_code == 422
    assert future_birth_date.status_code == 422
