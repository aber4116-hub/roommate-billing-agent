"""当前账本摘要。"""

from __future__ import annotations

from typing import Any
from uuid import UUID

from sqlalchemy.orm import Session

from . import periods, settlements


def current_ledger(session: Session, household_id: UUID) -> dict[str, Any]:
    period = periods.current_period(session, household_id)
    if period is None:
        return {"period": None}
    data = settlements.preview(session, household_id=household_id, period_id=period.id)
    return {
        "period": {
            "id": str(period.id),
            "period_key": period.period_key,
            "status": period.status,
            "version": period.version,
            "starts_on": period.starts_on.isoformat(),
            "ends_on": period.ends_on.isoformat(),
        },
        "rule": data["rule_snapshot"],
        "people": data["people"],
        "bills_total_cents": data["bills_total_cents"],
        "payments_total_cents": data["payments_total_cents"],
        "allocated_total_cents": sum(line["allocated_cents"] for line in data["lines"]),
        "balances": [
            {
                "person_id": line["person_id"],
                "allocated_cents": line["allocated_cents"],
                "paid_cents": line["paid_cents"],
                "balance_cents": line["balance_cents"],
            }
            for line in data["lines"]
        ],
    }
