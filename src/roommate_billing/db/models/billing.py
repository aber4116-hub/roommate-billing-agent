"""账期、入住天数、账单与分摊模型。"""

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
    Integer,
    SmallInteger,
    String,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column

from ..base import Base, utcnow


class BillingPeriod(Base):
    __tablename__ = "billing_periods"
    __table_args__ = (
        UniqueConstraint("household_id", "period_key", name="uq_billing_periods_key"),
        UniqueConstraint("household_id", "id", name="uq_billing_periods_household_id"),
        CheckConstraint("status IN ('open','locked','settled')", name="status"),
        CheckConstraint("starts_on <= ends_on", name="date_range"),
        CheckConstraint("period_key ~ '^[0-9]{4}-(0[1-9]|1[0-2])$'", name="period_key_format"),
        Index("ix_billing_periods_household_status", "household_id", "status"),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    household_id: Mapped[UUID] = mapped_column(ForeignKey("households.id"), nullable=False)
    period_key: Mapped[str] = mapped_column(String(7), nullable=False)
    starts_on: Mapped[date] = mapped_column(Date, nullable=False)
    ends_on: Mapped[date] = mapped_column(Date, nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="open")
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    locked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    settled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_by: Mapped[UUID] = mapped_column(ForeignKey("users.id"), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utcnow, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=utcnow,
        onupdate=utcnow,
        server_default=func.now(),
    )


class Occupancy(Base):
    __tablename__ = "occupancies"
    __table_args__ = (
        CheckConstraint("days BETWEEN 0 AND 31", name="days_range"),
        ForeignKeyConstraint(
            ["household_id", "period_id"],
            ["billing_periods.household_id", "billing_periods.id"],
            name="fk_occupancies_period",
        ),
        ForeignKeyConstraint(
            ["household_id", "person_id"],
            ["people.household_id", "people.id"],
            name="fk_occupancies_person",
        ),
    )

    household_id: Mapped[UUID] = mapped_column(ForeignKey("households.id"), nullable=False)
    period_id: Mapped[UUID] = mapped_column(nullable=False, primary_key=True)
    person_id: Mapped[UUID] = mapped_column(nullable=False, primary_key=True)
    days: Mapped[int] = mapped_column(SmallInteger, nullable=False, default=0)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utcnow, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=utcnow,
        onupdate=utcnow,
        server_default=func.now(),
    )


class Bill(Base):
    __tablename__ = "bills"
    __table_args__ = (
        UniqueConstraint("household_id", "id", name="uq_bills_household_id"),
        ForeignKeyConstraint(
            ["household_id", "period_id"],
            ["billing_periods.household_id", "billing_periods.id"],
            name="fk_bills_period",
        ),
        CheckConstraint(
            "category IN ('electricity','water','internet','trash','other')",
            name="category",
        ),
        CheckConstraint("status IN ('active','voided')", name="status"),
        CheckConstraint("amount_cents BETWEEN 0 AND 100000000000", name="amount_range"),
        CheckConstraint(
            "status <> 'voided' OR (voided_at IS NOT NULL AND void_reason IS NOT NULL)",
            name="void_fields",
        ),
        Index("ix_bills_period_status", "period_id", "status", "category"),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    household_id: Mapped[UUID] = mapped_column(ForeignKey("households.id"), nullable=False)
    period_id: Mapped[UUID] = mapped_column(nullable=False)
    category: Mapped[str] = mapped_column(String(24), nullable=False)
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    amount_cents: Mapped[int] = mapped_column(BigInteger, nullable=False)
    incurred_on: Mapped[date | None] = mapped_column(Date, nullable=True)
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="active")
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    created_by: Mapped[UUID] = mapped_column(ForeignKey("users.id"), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utcnow, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=utcnow,
        onupdate=utcnow,
        server_default=func.now(),
    )
    voided_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    voided_by: Mapped[UUID | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    void_reason: Mapped[str | None] = mapped_column(String(300), nullable=True)


class BillAllocation(Base):
    __tablename__ = "bill_allocations"
    __table_args__ = (
        UniqueConstraint("bill_id", "person_id", name="uq_bill_allocations_bill_person"),
        UniqueConstraint("household_id", "id", name="uq_bill_allocations_household_id"),
        ForeignKeyConstraint(
            ["household_id", "bill_id"],
            ["bills.household_id", "bills.id"],
            name="fk_bill_allocations_bill",
        ),
        ForeignKeyConstraint(
            ["household_id", "person_id"],
            ["people.household_id", "people.id"],
            name="fk_bill_allocations_person",
        ),
        ForeignKeyConstraint(
            ["household_id", "rule_version_id"],
            ["rule_versions.household_id", "rule_versions.id"],
            name="fk_bill_allocations_rule",
        ),
        CheckConstraint("weight_units >= 0", name="weight_nonnegative"),
        CheckConstraint("base_cents >= 0", name="base_nonnegative"),
        CheckConstraint("remainder_cents >= 0", name="remainder_nonnegative"),
        CheckConstraint("amount_cents = base_cents + remainder_cents", name="amount_sum"),
        Index("ix_bill_allocations_person", "person_id", "rule_version_id"),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    household_id: Mapped[UUID] = mapped_column(ForeignKey("households.id"), nullable=False)
    bill_id: Mapped[UUID] = mapped_column(nullable=False)
    person_id: Mapped[UUID] = mapped_column(nullable=False)
    rule_version_id: Mapped[UUID] = mapped_column(nullable=False)
    weight_units: Mapped[int] = mapped_column(Integer, nullable=False)
    base_cents: Mapped[int] = mapped_column(BigInteger, nullable=False)
    remainder_cents: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)
    amount_cents: Mapped[int] = mapped_column(BigInteger, nullable=False)
    is_remainder_owner: Mapped[bool] = mapped_column(nullable=False, default=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utcnow, server_default=func.now()
    )
