"""正式结算快照模型。"""

from __future__ import annotations

from datetime import datetime
from uuid import UUID, uuid4

from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    DateTime,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    Integer,
    SmallInteger,
    String,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from ..base import Base, utcnow


class Settlement(Base):
    __tablename__ = "settlements"
    __table_args__ = (
        UniqueConstraint("period_id", "revision", name="uq_settlements_period_revision"),
        UniqueConstraint("household_id", "id", name="uq_settlements_household_id"),
        ForeignKeyConstraint(
            ["household_id", "period_id"],
            ["billing_periods.household_id", "billing_periods.id"],
            name="fk_settlements_period",
        ),
        ForeignKeyConstraint(
            ["household_id", "rule_version_id"],
            ["rule_versions.household_id", "rule_versions.id"],
            name="fk_settlements_rule",
        ),
        CheckConstraint("status IN ('final','superseded','voided')", name="status"),
        CheckConstraint("revision >= 1", name="revision_positive"),
        Index(
            "uq_settlements_one_final",
            "period_id",
            unique=True,
            postgresql_where=text("status = 'final'"),
        ),
        Index("ix_settlements_period_created", "period_id", "created_at"),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    household_id: Mapped[UUID] = mapped_column(ForeignKey("households.id"), nullable=False)
    period_id: Mapped[UUID] = mapped_column(nullable=False)
    revision: Mapped[int] = mapped_column(Integer, nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="final")
    rule_version_id: Mapped[UUID] = mapped_column(nullable=False)
    rule_snapshot: Mapped[dict] = mapped_column(JSONB, nullable=False)
    bills_snapshot: Mapped[dict] = mapped_column(JSONB, nullable=False)
    bills_total_cents: Mapped[int] = mapped_column(BigInteger, nullable=False)
    payments_total_cents: Mapped[int] = mapped_column(BigInteger, nullable=False)
    balance_total_cents: Mapped[int] = mapped_column(BigInteger, nullable=False)
    created_by: Mapped[UUID] = mapped_column(ForeignKey("users.id"), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utcnow, server_default=func.now()
    )
    supersedes_id: Mapped[UUID | None] = mapped_column(ForeignKey("settlements.id"), nullable=True)
    superseded_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    note: Mapped[str | None] = mapped_column(String(500), nullable=True)
    request_id: Mapped[UUID] = mapped_column(nullable=False)


class SettlementLine(Base):
    __tablename__ = "settlement_lines"
    __table_args__ = (
        UniqueConstraint("settlement_id", "person_id", name="uq_settlement_lines_person"),
        ForeignKeyConstraint(
            ["household_id", "settlement_id"],
            ["settlements.household_id", "settlements.id"],
            name="fk_settlement_lines_settlement",
        ),
        ForeignKeyConstraint(
            ["household_id", "person_id"],
            ["people.household_id", "people.id"],
            name="fk_settlement_lines_person",
        ),
        CheckConstraint("balance_cents = allocated_cents - paid_cents", name="balance_formula"),
        Index("ix_settlement_lines_settlement", "settlement_id"),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    household_id: Mapped[UUID] = mapped_column(ForeignKey("households.id"), nullable=False)
    settlement_id: Mapped[UUID] = mapped_column(nullable=False)
    person_id: Mapped[UUID] = mapped_column(nullable=False)
    allocated_cents: Mapped[int] = mapped_column(BigInteger, nullable=False)
    paid_cents: Mapped[int] = mapped_column(BigInteger, nullable=False)
    balance_cents: Mapped[int] = mapped_column(BigInteger, nullable=False)
    remainder_cents: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)
    display_order: Mapped[int] = mapped_column(SmallInteger, nullable=False, default=0)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utcnow, server_default=func.now()
    )
