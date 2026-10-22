"""API 请求模型。"""

from __future__ import annotations

from datetime import date
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from ..domain.money import MAX_BILL_CENTS

Category = Literal["electricity", "water", "internet", "trash", "other"]
SplitMethod = Literal["days", "equal_household"]
PaymentMethod = Literal["cash", "bank", "wechat", "alipay", "other"]


class RequestModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class PeriodCreate(RequestModel):
    period_key: str = Field(pattern=r"^[0-9]{4}-(0[1-9]|1[0-2])$")
    starts_on: date | None = None
    ends_on: date | None = None


class HouseholdCreate(RequestModel):
    name: str = Field(min_length=1, max_length=120)


class LoginRequest(RequestModel):
    email: str = Field(min_length=3, max_length=320)
    password: str = Field(min_length=1, max_length=128)


class RegisterRequest(RequestModel):
    email: str = Field(min_length=3, max_length=320)
    password: str = Field(min_length=12, max_length=128)
    display_name: str = Field(min_length=1, max_length=80)


class ChangePasswordRequest(RequestModel):
    current_password: str = Field(min_length=1, max_length=128)
    new_password: str = Field(min_length=12, max_length=128)


class InviteCreate(RequestModel):
    role: Literal["admin", "member"] = "member"
    email: str | None = Field(default=None, max_length=320)


class InviteAccept(RequestModel):
    token: str = Field(min_length=20, max_length=200)


class MemberUpdate(RequestModel):
    role: Literal["admin", "member"] | None = None
    status: Literal["active", "left"] | None = None

    @model_validator(mode="after")
    def require_change(self) -> MemberUpdate:
        if self.role is None and self.status is None:
            raise ValueError("至少提供 role 或 status")
        return self


class VersionRequest(RequestModel):
    expected_version: int = Field(ge=1)


class OccupancyItem(RequestModel):
    person_id: UUID
    days: int = Field(ge=0, le=31)


class OccupanciesUpdate(VersionRequest):
    items: list[OccupancyItem] = Field(min_length=1, max_length=100)


class BillCreate(RequestModel):
    category: Category
    name: str = Field(min_length=1, max_length=120)
    amount_cents: int = Field(ge=0, le=MAX_BILL_CENTS)
    incurred_on: date | None = None


class BillUpdate(RequestModel):
    expected_version: int = Field(ge=1)
    name: str | None = Field(default=None, min_length=1, max_length=120)
    amount_cents: int | None = Field(default=None, ge=0, le=MAX_BILL_CENTS)
    incurred_on: date | None = None

    @model_validator(mode="after")
    def require_change(self) -> BillUpdate:
        if self.name is None and self.amount_cents is None and self.incurred_on is None:
            raise ValueError("至少提供一个要修改的字段")
        return self


class BillVoid(RequestModel):
    expected_version: int = Field(ge=1)
    reason: str = Field(min_length=1, max_length=300)


class PreviewOccupancy(RequestModel):
    person_id: UUID
    days: int = Field(ge=0, le=31)


class PreviewBill(RequestModel):
    category: Category
    name: str | None = Field(default=None, max_length=120)
    amount_cents: int = Field(ge=0, le=MAX_BILL_CENTS)


class SplitPreviewRequest(RequestModel):
    rule_version_id: UUID | None = None
    occupancies: list[PreviewOccupancy] | None = Field(default=None, max_length=100)
    bills: list[PreviewBill] | None = Field(default=None, max_length=200)


class PaymentCreate(RequestModel):
    person_id: UUID
    amount_cents: int = Field(gt=0, le=MAX_BILL_CENTS)
    paid_on: date
    method: PaymentMethod = "other"
    reference: str | None = Field(default=None, max_length=120)
    note: str | None = Field(default=None, max_length=500)


class PaymentAdjust(RequestModel):
    amount_cents: int
    reason: str = Field(min_length=1, max_length=300)

    @field_validator("amount_cents")
    @classmethod
    def nonzero(cls, value: int) -> int:
        if value == 0:
            raise ValueError("调整金额不能为 0")
        return value


class RuleItemRequest(RequestModel):
    category: Category
    split_method: SplitMethod
    fallback_method: Literal["equal_household"] = "equal_household"


class RuleDraftCreate(RequestModel):
    owner_person_id: UUID
    items: list[RuleItemRequest] = Field(min_length=1, max_length=5)
    note: str = Field(min_length=1, max_length=500)


class RuleActivate(RequestModel):
    expected_active_version_no: int = Field(ge=0)
    expected_preview_hash: str = Field(min_length=64, max_length=64)
    expected_row_version: int = Field(ge=1)


class SettlementCreate(RequestModel):
    expected_period_version: int = Field(ge=1)
    preview_hash: str = Field(min_length=64, max_length=64)
    note: str | None = Field(default=None, max_length=500)


class PersonCreate(RequestModel):
    display_name: str = Field(min_length=1, max_length=80)
    slug: str | None = Field(default=None, pattern=r"^[a-z][a-z0-9_]{0,39}$")
    user_id: UUID | None = None


class ReopenPeriod(VersionRequest):
    reason: str = Field(min_length=1, max_length=300)


class ConversationCreate(RequestModel):
    title: str | None = Field(default=None, max_length=160)


class ConversationUpdate(RequestModel):
    title: str | None = Field(default=None, max_length=160)
    archived: bool | None = None


class AgentMessageCreate(RequestModel):
    content: str = Field(min_length=1, max_length=4000)
    client_message_id: UUID | None = None


class ActionConfirm(RequestModel):
    expected_payload_hash: str = Field(min_length=64, max_length=64)
