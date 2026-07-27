"""Registration, sign-in, and session token behaviour."""

from __future__ import annotations

import uuid

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from apps.api.app.errors import EmailAlreadyRegisteredError, InvalidCredentialsError
from apps.api.app.models.enums import UserStatus
from apps.api.app.security.passwords import hash_password, verify_password
from apps.api.app.security.tokens import create_access_token, decode_access_token
from apps.api.app.services.accounts import authenticate, get_user_by_email, register_user
from apps.api.tests.helpers import VALID_PASSWORD, register

REGISTRATION = {
    "email": "learner@example.com",
    "password": VALID_PASSWORD,
    "display_name": "Test Learner",
    "daily_minutes": 40,
}


def test_register_creates_account_and_profile(client: TestClient) -> None:
    response = client.post("/api/v1/auth/register", json=REGISTRATION)
    assert response.status_code == 201
    body = response.json()
    assert body["account"]["email"] == "learner@example.com"
    assert body["token"]["token_type"] == "bearer"
    assert body["token"]["expires_in"] > 0


def test_register_normalises_email_case(client: TestClient, db_session: Session) -> None:
    payload = REGISTRATION | {"email": "Learner@Example.COM"}
    assert client.post("/api/v1/auth/register", json=payload).status_code == 201
    assert get_user_by_email(db_session, "learner@example.com") is not None


def test_register_rejects_duplicate_email(client: TestClient) -> None:
    client.post("/api/v1/auth/register", json=REGISTRATION)
    response = client.post("/api/v1/auth/register", json=REGISTRATION)
    assert response.status_code == 409
    assert response.json()["code"] == "email_already_registered"


def test_register_rejects_short_password(client: TestClient) -> None:
    response = client.post("/api/v1/auth/register", json=REGISTRATION | {"password": "short"})
    assert response.status_code == 422
    assert response.json()["code"] == "weak_password"


def test_register_rejects_low_variety_password(client: TestClient) -> None:
    response = client.post(
        "/api/v1/auth/register", json=REGISTRATION | {"password": "aaaaaaaaaaaa"}
    )
    assert response.status_code == 422
    assert response.json()["code"] == "weak_password"


def test_weak_password_creates_no_account(client: TestClient, db_session: Session) -> None:
    client.post("/api/v1/auth/register", json=REGISTRATION | {"password": "short"})
    assert get_user_by_email(db_session, REGISTRATION["email"]) is None


def test_password_hash_is_never_returned(client: TestClient) -> None:
    body = client.post("/api/v1/auth/register", json=REGISTRATION).text
    assert "password" not in body
    assert "$2b$" not in body


def test_login_returns_token(client: TestClient) -> None:
    client.post("/api/v1/auth/register", json=REGISTRATION)
    response = client.post(
        "/api/v1/auth/login",
        json={"email": REGISTRATION["email"], "password": VALID_PASSWORD},
    )
    assert response.status_code == 200
    assert response.json()["access_token"]


def test_login_with_wrong_password_is_rejected(client: TestClient) -> None:
    client.post("/api/v1/auth/register", json=REGISTRATION)
    response = client.post(
        "/api/v1/auth/login",
        json={"email": REGISTRATION["email"], "password": "wrong-password-1"},
    )
    assert response.status_code == 401
    assert response.json()["code"] == "invalid_credentials"


def test_unknown_email_is_indistinguishable_from_wrong_password(client: TestClient) -> None:
    """Error responses must not reveal whether an address is registered."""
    client.post("/api/v1/auth/register", json=REGISTRATION)
    wrong_password = client.post(
        "/api/v1/auth/login",
        json={"email": REGISTRATION["email"], "password": "wrong-password-1"},
    )
    unknown_email = client.post(
        "/api/v1/auth/login",
        json={"email": "nobody@example.com", "password": VALID_PASSWORD},
    )
    assert wrong_password.status_code == unknown_email.status_code == 401
    assert wrong_password.json()["code"] == unknown_email.json()["code"]
    assert wrong_password.json()["message"] == unknown_email.json()["message"]


def test_me_requires_authentication(client: TestClient) -> None:
    response = client.get("/api/v1/auth/me")
    assert response.status_code == 401
    assert response.json()["code"] == "not_authenticated"


def test_me_rejects_malformed_token(client: TestClient) -> None:
    response = client.get("/api/v1/auth/me", headers={"Authorization": "Bearer not-a-token"})
    assert response.status_code == 401


def test_me_returns_account_for_valid_token(client: TestClient) -> None:
    headers = register(client)
    response = client.get("/api/v1/auth/me", headers=headers)
    assert response.status_code == 200
    assert response.json()["email"] == "learner@example.com"


def test_suspended_account_cannot_use_a_valid_token(
    client: TestClient, db_session: Session
) -> None:
    headers = register(client)
    user = get_user_by_email(db_session, "learner@example.com")
    assert user is not None
    user.status = UserStatus.SUSPENDED
    db_session.commit()

    response = client.get("/api/v1/auth/me", headers=headers)
    assert response.status_code == 403
    assert response.json()["code"] == "account_inactive"


# --- Service and primitive level -------------------------------------------------


def test_hash_is_salted_and_verifiable() -> None:
    first = hash_password(VALID_PASSWORD)
    second = hash_password(VALID_PASSWORD)
    assert first != second
    assert verify_password(VALID_PASSWORD, first)
    assert not verify_password("something-else-1", first)


def test_verify_password_tolerates_corrupt_hash() -> None:
    assert verify_password(VALID_PASSWORD, "not-a-bcrypt-hash") is False


def test_token_round_trip() -> None:
    user_id = uuid.uuid4()
    token, expires_in = create_access_token(user_id)
    claims = decode_access_token(token)
    assert claims.user_id == user_id
    assert 0 < claims.expires_in_seconds <= expires_in


def test_register_service_rejects_duplicates(db_session: Session) -> None:
    register_user(db_session, email="a@example.com", password=VALID_PASSWORD, display_name="A")
    db_session.commit()
    with pytest.raises(EmailAlreadyRegisteredError):
        register_user(db_session, email="A@Example.com", password=VALID_PASSWORD, display_name="A")


def test_authenticate_updates_last_login(db_session: Session) -> None:
    user = register_user(
        db_session, email="a@example.com", password=VALID_PASSWORD, display_name="A"
    )
    db_session.commit()
    assert user.last_login_at is None

    authenticated = authenticate(db_session, email="a@example.com", password=VALID_PASSWORD)
    assert authenticated.last_login_at is not None


def test_authenticate_rejects_unknown_email(db_session: Session) -> None:
    with pytest.raises(InvalidCredentialsError):
        authenticate(db_session, email="nobody@example.com", password=VALID_PASSWORD)
