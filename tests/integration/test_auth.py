"""认证、会话、CSRF、邀请与审计 API 测试。"""

from __future__ import annotations

from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from roommate_billing.db.models import User
from roommate_billing.security.passwords import hash_password

PASSWORD = "correct-horse-battery-staple"
NEW_PASSWORD = "new-correct-horse-battery-staple"


def _login(client: TestClient, email: str, password: str = PASSWORD):
    return client.post(
        "/api/v1/auth/login",
        json={"email": email, "password": password},
    )


def _csrf(response) -> str:
    return response.json()["data"]["csrf_token"]


def test_login_csrf_and_logout(auth_client, seed) -> None:
    response = _login(auth_client, "owner@example.com")
    assert response.status_code == 200, response.text
    csrf = _csrf(response)

    me = auth_client.get("/api/v1/auth/me")
    assert me.status_code == 200
    assert me.json()["data"]["user"]["email"] == "owner@example.com"

    no_csrf = auth_client.post("/api/v1/households", json={"name": "无 CSRF"})
    assert no_csrf.status_code == 403
    assert no_csrf.json()["error"]["code"] == "CSRF_INVALID"

    created = auth_client.post(
        "/api/v1/households",
        json={"name": "第二账本"},
        headers={"X-CSRF-Token": csrf},
    )
    assert created.status_code == 201, created.text
    new_household = created.json()["data"]["id"]

    selected = auth_client.get(
        f"/api/v1/households/{new_household}",
        headers={"X-Household-ID": new_household},
    )
    assert selected.status_code == 200
    assert selected.json()["data"]["name"] == "第二账本"

    logout = auth_client.post("/api/v1/auth/logout", headers={"X-CSRF-Token": csrf})
    assert logout.status_code == 204
    assert auth_client.get("/api/v1/auth/me").status_code == 401


def test_wrong_password_and_lockout(auth_client, seed, db_session: Session) -> None:
    for _ in range(4):
        response = _login(auth_client, "owner@example.com", "wrong-password")
        assert response.status_code == 401
        assert response.json()["error"]["code"] == "INVALID_CREDENTIALS"

    fifth = _login(auth_client, "owner@example.com", "wrong-password")
    assert fifth.status_code == 401
    user = db_session.scalar(select(User).where(User.email == "owner@example.com"))
    assert user is not None
    assert user.locked_until is not None

    locked = _login(auth_client, "owner@example.com", PASSWORD)
    assert locked.status_code == 423
    assert locked.json()["error"]["code"] == "ACCOUNT_LOCKED"


def test_password_change(auth_client, seed) -> None:
    response = _login(auth_client, "owner@example.com")
    assert response.status_code == 200
    csrf = _csrf(response)
    changed = auth_client.post(
        "/api/v1/auth/password",
        json={"current_password": PASSWORD, "new_password": NEW_PASSWORD},
        headers={"X-CSRF-Token": csrf},
    )
    assert changed.status_code == 204, changed.text

    old = _login(auth_client, "owner@example.com", PASSWORD)
    assert old.status_code == 401
    new = _login(auth_client, "owner@example.com", NEW_PASSWORD)
    assert new.status_code == 200


def test_invite_accept_flow(auth_client, auth_app, seed, db_session: Session) -> None:
    invitee = User(
        email="invitee@example.com",
        display_name="Invitee",
        password_hash=hash_password(PASSWORD),
    )
    db_session.add(invitee)
    db_session.commit()

    owner_login = _login(auth_client, "owner@example.com")
    csrf = _csrf(owner_login)
    created = auth_client.post(
        f"/api/v1/households/{seed.household_id}/invites",
        json={"role": "member", "email": "invitee@example.com"},
        headers={"X-CSRF-Token": csrf},
    )
    assert created.status_code == 201, created.text
    token = created.json()["data"]["token"]

    with TestClient(auth_app) as invitee_client:
        login = _login(invitee_client, "invitee@example.com")
        assert login.status_code == 200, login.text
        invitee_csrf = _csrf(login)
        accepted = invitee_client.post(
            "/api/v1/auth/invites/accept",
            json={"token": token},
            headers={"X-CSRF-Token": invitee_csrf},
        )
        assert accepted.status_code == 200, accepted.text
        selected = invitee_client.get(f"/api/v1/households/{seed.household_id}")
        assert selected.status_code == 200
        assert selected.json()["data"]["name"] == "Test Household"

        members = auth_client.get(f"/api/v1/households/{seed.household_id}/members")
        assert members.status_code == 200
        assert any(row["email"] == "invitee@example.com" for row in members.json()["data"]["items"])


def test_audit_logs_admin_only(auth_client, auth_app, seed) -> None:
    owner_login = _login(auth_client, "owner@example.com")
    owner_csrf = _csrf(owner_login)
    # 产生一条可查询的写审计。
    created = auth_client.post(
        f"/api/v1/households/{seed.household_id}/invites",
        json={"role": "member"},
        headers={"X-CSRF-Token": owner_csrf},
    )
    assert created.status_code == 201

    logs = auth_client.get(f"/api/v1/households/{seed.household_id}/audit-logs")
    assert logs.status_code == 200
    assert logs.json()["data"]["items"]

    with TestClient(auth_app) as member_client:
        login = _login(member_client, "member@example.com")
        assert login.status_code == 200
        forbidden = member_client.get(f"/api/v1/households/{seed.household_id}/audit-logs")
        assert forbidden.status_code == 403


def test_origin_check(auth_client, seed) -> None:
    response = auth_client.post(
        "/api/v1/auth/login",
        json={"email": "owner@example.com", "password": PASSWORD},
        headers={"Origin": "https://evil.example"},
    )
    assert response.status_code == 403
    assert response.json()["error"]["code"] == "ORIGIN_INVALID"


def test_member_role_update_and_permission(client, seed) -> None:
    # 这个测试使用测试 Principal，验证现有 RBAC 路由；真实成员变更在 auth 流程中覆盖。
    response = client.patch(
        f"/api/v1/households/{seed.household_id}/members/{seed.member_user_id}",
        json={"role": "admin"},
    )
    assert response.status_code == 200, response.text
    assert response.json()["data"]["role"] == "admin"

    # 恢复 member，避免后续测试假设。
    restored = client.patch(
        f"/api/v1/households/{seed.household_id}/members/{seed.member_user_id}",
        json={"role": "member"},
    )
    assert restored.status_code == 200
