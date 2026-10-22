"""规则版本模型。"""

from __future__ import annotations

from datetime import datetime
from uuid import UUID, uuid4

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    Integer,
    String,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from ..base import Base, utcnow


class RuleVersion(Base):
    __tablename__ = "rule_versions"
    __table_args__ = (
        UniqueConstraint("household_id", "version_no", name="uq_rule_versions_version"),
        UniqueConstraint("household_id", "id", name="uq_rule_versions_household_id"),
        ForeignKeyConstraint(
            ["household_id", "remainder_owner_person_id"],
            ["people.household_id", "people.id"],
            name="fk_rule_versions_owner_person",
        ),
        CheckConstraint("status IN ('draft','active','archived')", name="status"),
        CheckConstraint("version_no >= 1", name="version_no_positive"),
        Index(
            "uq_rule_versions_one_active",
            "household_id",
            unique=True,
            postgresql_where=text("status = 'active'"),
        ),
        Index("ix_rule_versions_household_status", "household_id", "status"),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    household_id: Mapped[UUID] = mapped_column(ForeignKey("households.id"), nullable=False)
    version_no: Mapped[int] = mapped_column(Integer, nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="draft")
    row_version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    remainder_owner_person_id: Mapped[UUID] = mapped_column(nullable=False)
    config_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    preview_snapshot: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    preview_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)
    previewed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    note: Mapped[str | None] = mapped_column(String(500), nullable=True)
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
    activated_by: Mapped[UUID | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    activated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    archived_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    supersedes_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("rule_versions.id"), nullable=True
    )


class RuleVersionItem(Base):
    __tablename__ = "rule_version_items"
    __table_args__ = (
        UniqueConstraint("rule_version_id", "category", name="uq_rule_version_items_category"),
        ForeignKeyConstraint(
            ["household_id", "rule_version_id"],
            ["rule_versions.household_id", "rule_versions.id"],
            name="fk_rule_version_items_version",
        ),
        CheckConstraint(
            "category IN ('electricity','water','internet','trash','other')",
            name="category",
        ),
        CheckConstraint("split_method IN ('days','equal_household')", name="split_method"),
        CheckConstraint("fallback_method = 'equal_household'", name="fallback_method"),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    household_id: Mapped[UUID] = mapped_column(ForeignKey("households.id"), nullable=False)
    rule_version_id: Mapped[UUID] = mapped_column(nullable=False)
    category: Mapped[str] = mapped_column(String(24), nullable=False)
    split_method: Mapped[str] = mapped_column(String(32), nullable=False)
    fallback_method: Mapped[str] = mapped_column(
        String(32), nullable=False, default="equal_household"
    )
    config: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utcnow, server_default=func.now()
    )
