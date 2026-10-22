"""迁移与数据库不可变约束测试。"""

from __future__ import annotations

from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select, text, update
from sqlalchemy.exc import DBAPIError
from sqlalchemy.orm import Session

from roommate_billing.db.models import AuditLog, Payment
from roommate_billing.main import create_app
from roommate_billing.services import payments


def test_alembic_head_and_triggers(engine) -> None:
    with engine.connect() as connection:
        version = connection.scalar(text("SELECT version_num FROM alembic_version"))
        assert version == "f9d42243af3a"
        count = connection.scalar(
            text(
                "SELECT count(*) FROM pg_trigger t "
                "JOIN pg_class c ON c.oid = t.tgrelid "
                "WHERE NOT t.tgisinternal"
            )
        )
        assert count == 3


def test_audit_log_append_only(db_session: Session, seed) -> None:
    entry = db_session.scalar(select(AuditLog).limit(1))
    assert entry is not None
    with pytest.raises(DBAPIError):
        db_session.execute(
            update(AuditLog).where(AuditLog.id == entry.id).values(action="tampered")
        )
        db_session.commit()
    db_session.rollback()


def test_payment_trigger_blocks_delete(db_session: Session, seed) -> None:
    from datetime import date

    payment = payments.record_payment(
        db_session,
        household_id=seed.household_id,
        period_id=seed.period_id,
        actor_user_id=seed.user_id,
        person_id=seed.people["lin"],
        amount_cents=100,
        paid_on=date(2026, 10, 2),
        method="cash",
        request_id=uuid4(),
    )
    db_session.commit()
    with pytest.raises(DBAPIError):
        db_session.execute(Payment.__table__.delete().where(Payment.id == payment.id))
        db_session.commit()
    db_session.rollback()


def test_protected_route_requires_principal() -> None:
    app = create_app()
    with TestClient(app) as client:
        response = client.get("/api/v1/households")
        assert response.status_code == 401
        assert response.json()["error"]["code"] == "AUTH_REQUIRED"


def test_health_is_public() -> None:
    app = create_app()
    with TestClient(app) as client:
        assert client.get("/health/live").status_code == 200
        ready = client.get("/health/ready")
        assert ready.status_code == 200
        assert ready.json() == {"status": "ok"}
