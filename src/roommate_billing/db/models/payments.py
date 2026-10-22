"""实际收款/调整流水模型（只追加）。"""

from __future__ import annotations

from datetime import date, datetime
from uuid import UUID, uuid4

from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    Date,
    DateTime,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    String,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column

from ..base import Base, utcnow


class Payment(Base):
    __tablename__ = "payments"
    __table_args__ = (
        UniqueConstraint("household_id", "id", name="uq_payments_household_id"),
        ForeignKeyConstraint(
            ["household_id", "period_id"],
            ["billing_periods.household_id", "billing_periods.id"],
            name="fk_payments_period",
        ),
        ForeignKeyConstraint(
            ["household_id", "person_id"],
            ["people.household_id", "people.id"],
            name="fk_payments_person",
        ),
        CheckConstraint("amount_cents <> 0", name="amount_nonzero"),
        CheckConstraint("kind IN ('payment','adjustment')", name="kind"),
        CheckConstraint("method IN ('cash','bank','wechat','alipay','other')", name="method"),
        CheckConstraint(
            "(kind = 'payment' AND amount_cents > 0 AND adjusts_payment_id IS NULL) "
            "OR (kind = 'adjustment' AND adjusts_payment_id IS NOT NULL)",
            name="kind_amount",
        ),
        Index("ix_payments_period_person", "period_id", "person_id", "paid_on"),
        Index("ix_payments_adjusts", "adjusts_payment_id"),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    household_id: Mapped[UUID] = mapped_column(ForeignKey("households.id"), nullable=False)
    period_id: Mapped[UUID] = mapped_column(nullable=False)
    person_id: Mapped[UUID] = mapped_column(nullable=False)
    amount_cents: Mapped[int] = mapped_column(BigInteger, nullable=False)
    kind: Mapped[str] = mapped_column(String(16), nullable=False, default="payment")
    method: Mapped[str] = mapped_column(String(16), nullable=False, default="other")
    paid_on: Mapped[date] = mapped_column(Date, nullable=False)
    reference: Mapped[str | None] = mapped_column(String(120), nullable=True)
    note: Mapped[str | None] = mapped_column(String(500), nullable=True)
    adjusts_payment_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("payments.id"), nullable=True
    )
    created_by: Mapped[UUID] = mapped_column(ForeignKey("users.id"), nullable=False)
    recorded_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utcnow, server_default=func.now()
    )
