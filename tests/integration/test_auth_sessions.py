"""会话轮换、过期和密码吊销测试。"""

from __future__ import annotations

from datetime import timedelta

from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from roommate_billing.db.base import utcnow
from roommate_billing.db.models import AuthSession

PASSWORD = "correct-horse-battery-staple"
NEW_PASSWORD = "new-correct-horse-battery-staple"


def _login(client: TestClient, password: str = PASSWORD):
    return client.post(
        "/api/v1/auth/login",
        json={"email": "owner@example.com", "password": password},
    )


def test_csrf_rotation_and_session_expiry(auth_client, seed, db_session: Session) -> None:
    login = _login(auth_client)
    assert login.status_code == 200
    old_csrf = login.json()["data"]["csrf_token"]

    rotated = auth_client.get("/api/v1/auth/csrf")
    assert rotated.status_code == 200
    new_csrf = rotated.json()["data"]["csrf_token"]
    assert new_csrf != old_csrf

    old_attempt = auth_client.post(
        "/api/v1/households",
        json={"name": "旧 CSRF"},
        headers={"X-CSRF-Token": old_csrf},
    )
    assert old_attempt.status_code == 403
    new_attempt = auth_client.post(
        "/api/v1/households",
        json={"name": "新 CSRF"},
        headers={"X-CSRF-Token": new_csrf},
    )
    assert new_attempt.status_code == 201

    session = db_session.scalar(select(AuthSession))
    assert session is not None
    session.created_at = utcnow() - timedelta(days=2)
    session.expires_at = utcnow() - timedelta(seconds=1)
    db_session.commit()
    assert auth_client.get("/api/v1/auth/me").status_code == 401


def test_password_change_revokes_other_sessions(auth_app, auth_client, seed) -> None:
    first = _login(auth_client)
    assert first.status_code == 200
    first_csrf = first.json()["data"]["csrf_token"]

    with TestClient(auth_app) as second_client:
        second = _login(second_client)
        assert second.status_code == 200
        assert second_client.get("/api/v1/auth/me").status_code == 200

        changed = auth_client.post(
            "/api/v1/auth/password",
            json={"current_password": PASSWORD, "new_password": NEW_PASSWORD},
            headers={"X-CSRF-Token": first_csrf},
        )
        assert changed.status_code == 204, changed.text
        assert second_client.get("/api/v1/auth/me").status_code == 401
        assert auth_client.get("/api/v1/auth/me").status_code == 200


def test_session_idle_timeout(auth_client, seed, db_session: Session) -> None:
    login = _login(auth_client)
    assert login.status_code == 200
    session = db_session.scalar(select(AuthSession))
    assert session is not None
    session.last_seen_at = utcnow() - timedelta(days=2)
    db_session.commit()
    assert auth_client.get("/api/v1/auth/me").status_code == 401


def test_registration_disabled(auth_client, seed) -> None:
    response = auth_client.post(
        "/api/v1/auth/register",
        json={
            "email": "new@example.com",
            "password": "another-long-password",
            "display_name": "New",
        },
    )
    assert response.status_code == 403
    assert response.json()["error"]["code"] == "REGISTRATION_DISABLED"
