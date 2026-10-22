"""并发结算：只能产生一个 final。"""

from __future__ import annotations

import threading
from concurrent.futures import ThreadPoolExecutor
from uuid import uuid4

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from roommate_billing.db.models import Settlement
from roommate_billing.services import periods, settlements
from roommate_billing.services.errors import ConflictError


def test_concurrent_settlement_only_one_final(db_session: Session, seed, session_factory) -> None:
    period = periods.get_period(db_session, seed.household_id, seed.period_id)
    periods.lock_period(
        db_session,
        household_id=seed.household_id,
        period_id=seed.period_id,
        actor_user_id=seed.user_id,
        expected_version=period.version,
        request_id=uuid4(),
    )
    db_session.commit()
    preview = settlements.preview(
        db_session, household_id=seed.household_id, period_id=seed.period_id
    )
    barrier = threading.Barrier(2)

    def worker() -> str:
        session = session_factory()
        try:
            barrier.wait(timeout=5)
            settlements.create_settlement(
                session,
                household_id=seed.household_id,
                period_id=seed.period_id,
                actor_user_id=seed.user_id,
                expected_period_version=preview["period_version"],
                expected_preview_hash=preview["preview_hash"],
                request_id=uuid4(),
            )
            session.commit()
            return "ok"
        except ConflictError as exc:
            session.rollback()
            return exc.code
        finally:
            session.close()

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(lambda _: worker(), range(2)))
    assert results.count("ok") == 1
    assert any(code in {"PERIOD_NOT_LOCKED", "VERSION_CONFLICT"} for code in results)
    assert (
        db_session.scalar(
            select(func.count())
            .select_from(Settlement)
            .where(
                Settlement.period_id == seed.period_id,
                Settlement.status == "final",
            )
        )
        == 1
    )
