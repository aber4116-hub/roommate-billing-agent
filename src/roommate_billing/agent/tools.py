"""Agent 工具网关：白名单、参数校验、只读查询与待确认动作。"""

from __future__ import annotations

import hashlib
import json
from datetime import date, timedelta
from typing import Any
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..db.base import utcnow
from ..db.models import (
    BillingPeriod,
    PendingAction,
    Person,
    RuleVersion,
    Settlement,
)
from ..domain.money import MAX_BILL_CENTS, validate_cents
from ..security.principal import Principal
from ..services import bills, ledger, payments, periods, rules, settlements
from ..services.audit import jsonable, record_audit
from ..services.errors import ConflictError, ForbiddenError, NotFoundError, ValidationError
from .types import ToolCall

TOOL_NAMES = {
    "get_current_ledger",
    "get_billing_period",
    "preview_split",
    "explain_settlement",
    "propose_rule_change",
    "record_payment",
    "create_settlement",
    "get_settlement_history",
    "export_settlement",
    "create_bill",
    "update_bill",
    "void_bill",
    "set_occupancies",
}

CATEGORIES = ("electricity", "water", "internet", "trash", "other")
METHODS = ("cash", "bank", "wechat", "alipay", "other")


class ToolError(Exception):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


def tool_specs() -> list[dict[str, Any]]:
    """发送给模型的工具 schema；confirm_rule_change 故意不在列表。"""
    return [
        _spec(
            "get_current_ledger",
            "获取当前账本、当前账期、人员、规则和合计。",
            {},
        ),
        _spec(
            "get_billing_period",
            "查询指定账期的账单、入住天数、实收和结算历史。",
            {
                "period_key": _string("YYYY-MM；省略时用当前账期"),
                "relative_period": {
                    "type": "string",
                    "enum": ["current", "previous"],
                    "description": "current 或 previous；与 period_key 二选一",
                },
            },
        ),
        _spec(
            "preview_split",
            "预览分摊结果，不写正式账目。",
            {
                "period_key": _string("账期；省略时用当前"),
                "rule_version_id": _string("可选规则版本 UUID"),
                "occupancies": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "person_slug": {"type": "string"},
                            "days": {"type": "integer", "minimum": 0, "maximum": 31},
                        },
                        "required": ["person_slug", "days"],
                    },
                },
                "bills": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "category": {"type": "string", "enum": list(CATEGORIES)},
                            "name": {"type": "string"},
                            "amount_cents": {"type": "integer", "minimum": 0},
                        },
                        "required": ["category", "amount_cents"],
                    },
                },
            },
        ),
        _spec(
            "explain_settlement",
            "解释某人的应承担、实收和差额。",
            {
                "person_slug": _string("人员 slug"),
                "period_key": _string("可选账期"),
                "settlement_id": _string("可选结算 UUID"),
            },
        ),
        _spec(
            "propose_rule_change",
            "创建规则草稿并预览影响。激活需要用户在界面确认。",
            {
                "items": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "category": {"type": "string", "enum": list(CATEGORIES)},
                            "split_method": {
                                "type": "string",
                                "enum": ["days", "equal_household"],
                            },
                            "fallback_method": {
                                "type": "string",
                                "enum": ["equal_household"],
                            },
                        },
                        "required": ["category", "split_method"],
                    },
                },
                "remainder_owner_slug": _string("零头归属人 slug"),
                "note": _string("变更说明"),
            },
        ),
        _spec(
            "record_payment",
            "准备登记实际收款；用户在界面确认后才落账。",
            {
                "period_key": _string("账期"),
                "person_slug": _string("付款人 slug"),
                "amount_cents": {"type": "integer", "minimum": 1},
                "paid_on": _string("ISO 日期"),
                "method": {"type": "string", "enum": list(METHODS)},
                "reference": _string("可选流水号"),
                "note": _string("可选备注"),
            },
            required=["person_slug", "amount_cents", "paid_on"],
        ),
        _spec(
            "create_settlement",
            "准备正式结算；用户确认后才创建快照。",
            {"period_key": _string("账期"), "note": _string("备注")},
        ),
        _spec(
            "get_settlement_history",
            "查询账期结算历史。",
            {"period_key": _string("账期；省略当前")},
        ),
        _spec(
            "export_settlement",
            "获取结算 CSV 下载路径。",
            {"settlement_id": _string("结算 UUID"), "period_key": _string("账期")},
        ),
        _spec(
            "create_bill",
            "准备新增账单；用户确认后才入账。",
            {
                "period_key": _string("账期"),
                "category": {"type": "string", "enum": list(CATEGORIES)},
                "name": _string("账单名称"),
                "amount_cents": {"type": "integer", "minimum": 0},
                "incurred_on": _string("可选 ISO 日期"),
            },
            required=["category", "name", "amount_cents"],
        ),
        _spec(
            "update_bill",
            "准备修改账单；用户确认后才入账。",
            {
                "bill_id": _string("账单 UUID"),
                "fields": {
                    "type": "object",
                    "properties": {
                        "name": {"type": "string"},
                        "amount_cents": {"type": "integer", "minimum": 0},
                        "incurred_on": {"type": "string"},
                    },
                },
                "expected_version": {"type": "integer", "minimum": 1},
            },
            required=["bill_id", "fields", "expected_version"],
        ),
        _spec(
            "void_bill",
            "准备作废账单；用户确认后才执行。",
            {
                "bill_id": _string("账单 UUID"),
                "reason": _string("作废原因"),
                "expected_version": {"type": "integer", "minimum": 1},
            },
            required=["bill_id", "reason", "expected_version"],
        ),
        _spec(
            "set_occupancies",
            "准备设置入住天数；用户确认后才执行。",
            {
                "period_key": _string("账期"),
                "items": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "person_slug": {"type": "string"},
                            "days": {"type": "integer", "minimum": 0, "maximum": 31},
                        },
                        "required": ["person_slug", "days"],
                    },
                },
                "expected_period_version": {"type": "integer", "minimum": 1},
            },
            required=["items", "expected_period_version"],
        ),
    ]


def _string(description: str) -> dict[str, Any]:
    return {"type": "string", "description": description}


def _spec(
    name: str,
    description: str,
    properties: dict[str, Any],
    *,
    required: list[str] | None = None,
) -> dict[str, Any]:
    return {
        "type": "function",
        "function": {
            "name": name,
            "description": description,
            "parameters": {
                "type": "object",
                "properties": properties,
                "required": required or [],
                "additionalProperties": False,
            },
        },
    }


class ToolGateway:
    def __init__(
        self,
        session: Session,
        principal: Principal,
        *,
        conversation_id: UUID | None = None,
    ) -> None:
        self.session = session
        self.principal = principal
        self.conversation_id = conversation_id

    def execute(self, call: ToolCall) -> dict[str, Any]:
        if call.name not in TOOL_NAMES:
            return {
                "ok": False,
                "error": {"code": "TOOL_NOT_ALLOWED", "message": "工具不在白名单中"},
            }
        try:
            method = getattr(self, f"_tool_{call.name}")
            return {"ok": True, **method(call.arguments)}
        except (ToolError, ConflictError, ForbiddenError, NotFoundError, ValidationError) as exc:
            code = getattr(exc, "code", "TOOL_ERROR")
            message = getattr(exc, "message", str(exc))
            return {"ok": False, "error": {"code": code, "message": message}}
        except KeyError as exc:
            return {
                "ok": False,
                "error": {
                    "code": "MISSING_ARGUMENT",
                    "message": f"缺少参数：{exc.args[0] if exc.args else 'unknown'}",
                },
            }
        except (TypeError, ValueError) as exc:
            return {
                "ok": False,
                "error": {"code": "INVALID_ARGUMENT", "message": str(exc)},
            }

    # ---------- read tools ----------

    def _tool_get_current_ledger(self, _args: dict) -> dict[str, Any]:
        return {"data": ledger.current_ledger(self.session, self._household_id())}

    def _tool_get_billing_period(self, args: dict) -> dict[str, Any]:
        period = self._period(args)
        people = self._people()
        bills_rows = bills.list_bills(self.session, period.household_id, period.id)
        payments_rows = payments.list_payments(self.session, period.household_id, period.id)
        settlement_rows = settlements.list_settlements(self.session, period.household_id, period.id)
        return {
            "period": {
                "id": str(period.id),
                "period_key": period.period_key,
                "status": period.status,
                "version": period.version,
                "starts_on": period.starts_on.isoformat(),
                "ends_on": period.ends_on.isoformat(),
            },
            "people": [
                {"slug": person.slug, "display_name": person.display_name} for person in people
            ],
            "occupancies": [
                {
                    "person_slug": person.slug,
                    "days": periods.occupancy_map(self.session, period.id).get(person.id, 0),
                }
                for person in people
            ],
            "bills": [
                {
                    "id": str(row.id),
                    "category": row.category,
                    "name": row.name,
                    "amount_cents": row.amount_cents,
                    "status": row.status,
                    "version": row.version,
                }
                for row in bills_rows
            ],
            "payments": [
                {
                    "id": str(row.id),
                    "person_id": str(row.person_id),
                    "amount_cents": row.amount_cents,
                    "kind": row.kind,
                    "paid_on": row.paid_on.isoformat(),
                }
                for row in payments_rows
            ],
            "settlements": [
                {
                    "id": str(row.id),
                    "revision": row.revision,
                    "status": row.status,
                    "bills_total_cents": row.bills_total_cents,
                    "payments_total_cents": row.payments_total_cents,
                    "balance_total_cents": row.balance_total_cents,
                }
                for row in settlement_rows
            ],
        }

    def _tool_preview_split(self, args: dict) -> dict[str, Any]:
        period = self._period(args)
        rule_version_id = args.get("rule_version_id")
        occupancies = None
        if args.get("occupancies") is not None:
            occupancies = [
                {
                    "person_id": self._person(str(item["person_slug"])).id,
                    "days": self._days(item["days"]),
                }
                for item in args["occupancies"]
            ]
        preview_bills = None
        if args.get("bills") is not None:
            preview_bills = [
                {
                    "category": str(item["category"]),
                    "name": str(item.get("name") or item["category"]),
                    "amount_cents": self._cents(item["amount_cents"]),
                }
                for item in args["bills"]
            ]
        return bills.split_preview(
            self.session,
            household_id=period.household_id,
            period_id=period.id,
            rule_version_id=UUID(str(rule_version_id)) if rule_version_id else None,
            occupancies=occupancies,
            bills=preview_bills,
        )

    def _tool_explain_settlement(self, args: dict) -> dict[str, Any]:
        person = self._person(str(args["person_slug"]))
        settlement = self._settlement(args)
        return settlements.explain(
            self.session,
            household_id=self._household_id(),
            settlement_id=settlement.id,
            person_id=person.id,
        )

    def _tool_get_settlement_history(self, args: dict) -> dict[str, Any]:
        period = self._period(args)
        rows = settlements.list_settlements(self.session, period.household_id, period.id)
        return {
            "items": [
                {
                    "id": str(row.id),
                    "revision": row.revision,
                    "status": row.status,
                    "bills_total_cents": row.bills_total_cents,
                    "payments_total_cents": row.payments_total_cents,
                    "balance_total_cents": row.balance_total_cents,
                    "created_at": row.created_at.isoformat(),
                }
                for row in rows
            ]
        }

    def _tool_export_settlement(self, args: dict) -> dict[str, Any]:
        settlement = self._settlement(args)
        period = periods.get_period(self.session, self._household_id(), settlement.period_id)
        return {
            "filename": f"settlement-{period.period_key}-r{settlement.revision}.csv",
            "download_url": (
                f"/api/v1/households/{self._household_id()}/settlements/{settlement.id}/export"
            ),
        }

    # ---------- prepare-write tools ----------

    def _tool_create_bill(self, args: dict) -> dict[str, Any]:
        self._admin()
        period = self._period(args)
        if period.status != "open":
            raise ToolError("PERIOD_NOT_OPEN", "只有开放账期可以新增账单")
        category = str(args["category"])
        name = str(args["name"]).strip()
        amount = self._cents(args["amount_cents"])
        preview = bills.split_preview(
            self.session,
            household_id=period.household_id,
            period_id=period.id,
            bills=[{"category": category, "name": name, "amount_cents": amount}],
        )
        payload = {
            "period_id": str(period.id),
            "category": category,
            "name": name,
            "amount_cents": amount,
            "incurred_on": args.get("incurred_on"),
        }
        action = self._pending(
            action_type="create_bill",
            payload=payload,
            preview={"bill": preview["bills"][0], "period_version": period.version},
        )
        return self._pending_result(action, "账单已准备，确认后才会入账。")

    def _tool_update_bill(self, args: dict) -> dict[str, Any]:
        self._admin()
        bill = bills.get_bill(self.session, self._household_id(), UUID(str(args["bill_id"])))
        period = periods.get_period(self.session, self._household_id(), bill.period_id)
        if period.status != "open":
            raise ToolError("PERIOD_NOT_OPEN", "只有开放账期可以修改账单")
        expected = self._int(args["expected_version"], "expected_version", minimum=1)
        if bill.version != expected:
            raise ToolError("VERSION_CONFLICT", "账单已被修改，请刷新")
        fields = args.get("fields") or {}
        if not isinstance(fields, dict) or not fields:
            raise ToolError("MISSING_ARGUMENT", "缺少修改字段")
        hypothetical = []
        for row in bills.list_bills(self.session, self._household_id(), period.id):
            amount = row.amount_cents
            name = row.name
            if row.id == bill.id:
                amount = self._cents(fields.get("amount_cents", amount))
                name = str(fields.get("name", name))
            hypothetical.append({"category": row.category, "name": name, "amount_cents": amount})
        preview = bills.split_preview(
            self.session,
            household_id=self._household_id(),
            period_id=period.id,
            bills=hypothetical,
        )
        payload = {
            "bill_id": str(bill.id),
            "expected_version": expected,
            "fields": fields,
        }
        action = self._pending(
            action_type="update_bill",
            payload=payload,
            preview={"bills": preview["bills"], "period_version": period.version},
        )
        return self._pending_result(action, "修改已准备，确认后才会生效。")

    def _tool_void_bill(self, args: dict) -> dict[str, Any]:
        self._admin()
        bill = bills.get_bill(self.session, self._household_id(), UUID(str(args["bill_id"])))
        if not str(args.get("reason") or "").strip():
            raise ToolError("MISSING_ARGUMENT", "缺少作废原因")
        action = self._pending(
            action_type="void_bill",
            payload={
                "bill_id": str(bill.id),
                "expected_version": self._int(
                    args["expected_version"], "expected_version", minimum=1
                ),
                "reason": str(args["reason"]),
            },
            preview={
                "bill_id": str(bill.id),
                "name": bill.name,
                "amount_cents": bill.amount_cents,
                "status": bill.status,
            },
        )
        return self._pending_result(action, "作废已准备，确认后才会生效。")

    def _tool_set_occupancies(self, args: dict) -> dict[str, Any]:
        self._admin()
        period = self._period(args)
        if period.status != "open":
            raise ToolError("PERIOD_NOT_OPEN", "只有开放账期可以修改入住天数")
        expected = self._int(args["expected_period_version"], "expected_period_version", minimum=1)
        if period.version != expected:
            raise ToolError("VERSION_CONFLICT", "账期已变化，请重新加载")
        items = []
        for item in args.get("items") or []:
            person = self._person(str(item["person_slug"]))
            items.append({"person_id": str(person.id), "days": self._days(item["days"])})
        if not items:
            raise ToolError("MISSING_ARGUMENT", "缺少入住天数")
        preview = bills.split_preview(
            self.session,
            household_id=self._household_id(),
            period_id=period.id,
            occupancies=[
                {"person_id": UUID(item["person_id"]), "days": item["days"]} for item in items
            ],
        )
        action = self._pending(
            action_type="set_occupancies",
            payload={
                "period_id": str(period.id),
                "items": items,
                "expected_version": expected,
            },
            preview={
                "person_totals": preview["person_totals"],
                "bills": preview["bills"],
                "period_version": period.version,
            },
        )
        return self._pending_result(action, "入住天数已准备，确认后才会生效。")

    def _tool_record_payment(self, args: dict) -> dict[str, Any]:
        period = self._period(args)
        if period.status == "settled":
            raise ToolError("PERIOD_SETTLED", "已结算账期不能直接登记付款")
        person = self._person(str(args["person_slug"]))
        if (
            self.principal.role_for(self._household_id()) == "member"
            and self.principal.person_for(self._household_id()) != person.id
        ):
            raise ForbiddenError("普通成员只能登记自己的付款")
        amount = self._int(args["amount_cents"], "amount_cents", minimum=1)
        validate_cents(amount, max_abs_cents=MAX_BILL_CENTS)
        method = str(args.get("method") or "other")
        if method not in METHODS:
            raise ToolError("INVALID_ARGUMENT", "未知付款方式")
        paid_on = self._date(args["paid_on"])
        existing = payments.totals_by_person(self.session, self._household_id(), period.id).get(
            person.id, 0
        )
        payload = {
            "period_id": str(period.id),
            "person_id": str(person.id),
            "amount_cents": amount,
            "paid_on": paid_on.isoformat(),
            "method": method,
            "reference": args.get("reference"),
            "note": args.get("note"),
        }
        action = self._pending(
            action_type="record_payment",
            payload=payload,
            preview={
                "person": {"slug": person.slug, "display_name": person.display_name},
                "amount_cents": amount,
                "existing_paid_cents": existing,
                "after_paid_cents": existing + amount,
                "period_key": period.period_key,
            },
        )
        return self._pending_result(action, "收款已准备，确认后才会入账。")

    def _tool_create_settlement(self, args: dict) -> dict[str, Any]:
        self._admin()
        period = self._period(args)
        if period.status != "locked":
            raise ToolError("PERIOD_NOT_LOCKED", "正式结算前必须锁定账期")
        preview = settlements.preview(
            self.session, household_id=self._household_id(), period_id=period.id
        )
        action = self._pending(
            action_type="create_settlement",
            payload={
                "period_id": str(period.id),
                "expected_period_version": preview["period_version"],
                "preview_hash": preview["preview_hash"],
                "note": args.get("note"),
            },
            preview={
                "period_key": period.period_key,
                "lines": preview["lines"],
                "bills_total_cents": preview["bills_total_cents"],
                "payments_total_cents": preview["payments_total_cents"],
                "balance_total_cents": preview["balance_total_cents"],
            },
        )
        return self._pending_result(action, "结算已准备，确认后才会生成正式快照。")

    def _tool_propose_rule_change(self, args: dict) -> dict[str, Any]:
        self._admin()
        owner_slug = str(args["remainder_owner_slug"])
        owner = self._person(owner_slug)
        items = args.get("items") or []
        if not isinstance(items, list):
            raise ToolError("INVALID_ARGUMENT", "items 必须是数组")
        note = str(args.get("note") or "").strip()
        if not note:
            raise ToolError("MISSING_ARGUMENT", "缺少变更说明")
        draft = rules.create_draft(
            self.session,
            household_id=self._household_id(),
            owner_person_id=owner.id,
            items=items,
            note=note,
            actor_user_id=self.principal.user_id,
        )
        draft, preview = rules.preview_rule(
            self.session,
            household_id=self._household_id(),
            rule_version_id=draft.id,
            actor_user_id=self.principal.user_id,
        )
        active = self.session.scalar(
            select(RuleVersion).where(
                RuleVersion.household_id == self._household_id(),
                RuleVersion.status == "active",
            )
        )
        action = self._pending(
            action_type="confirm_rule_change",
            payload={
                "rule_version_id": str(draft.id),
                "expected_active_version_no": active.version_no if active else 0,
                "expected_preview_hash": draft.preview_hash,
                "expected_row_version": draft.row_version,
            },
            preview={
                "rule_version_id": str(draft.id),
                "version_no": draft.version_no,
                "periods": preview["periods"],
                "preview_hash": draft.preview_hash,
            },
        )
        return self._pending_result(action, "规则变更已准备，确认后才会生效。")

    # ---------- helpers ----------

    def _household_id(self) -> UUID:
        if self.principal.household_id is None:
            raise ForbiddenError("当前账户没有账本")
        return self.principal.household_id

    def _admin(self) -> None:
        if self.principal.role_for(self._household_id()) not in {"owner", "admin"}:
            raise ForbiddenError("需要管理员权限")

    def _period(self, args: dict) -> BillingPeriod:
        period_key = args.get("period_key")
        if period_key:
            period = self.session.scalar(
                select(BillingPeriod).where(
                    BillingPeriod.household_id == self._household_id(),
                    BillingPeriod.period_key == str(period_key),
                )
            )
            if period is None:
                raise NotFoundError("账期不存在")
            return period
        relative = args.get("relative_period") or "current"
        if relative == "current":
            period = periods.current_period(self.session, self._household_id())
            if period is None:
                raise NotFoundError("没有当前账期")
            return period
        if relative == "previous":
            current = periods.current_period(self.session, self._household_id())
            if current is None:
                period = self.session.scalar(
                    select(BillingPeriod)
                    .where(BillingPeriod.household_id == self._household_id())
                    .order_by(BillingPeriod.period_key.desc())
                )
            else:
                period = self.session.scalar(
                    select(BillingPeriod)
                    .where(
                        BillingPeriod.household_id == self._household_id(),
                        BillingPeriod.period_key < current.period_key,
                    )
                    .order_by(BillingPeriod.period_key.desc())
                )
            if period is None:
                raise NotFoundError("没有上一账期")
            return period
        raise ToolError("INVALID_ARGUMENT", "relative_period 只支持 current/previous")

    def _people(self) -> list[Person]:
        return list(
            self.session.scalars(
                select(Person)
                .where(
                    Person.household_id == self._household_id(),
                    Person.is_active.is_(True),
                )
                .order_by(Person.slug, Person.id)
            )
        )

    def _person(self, slug: str) -> Person:
        person = self.session.scalar(
            select(Person).where(
                Person.household_id == self._household_id(),
                Person.slug == slug,
            )
        )
        if person is None:
            raise NotFoundError("人员不存在")
        return person

    def _settlement(self, args: dict) -> Settlement:
        settlement_id = args.get("settlement_id")
        if settlement_id:
            return settlements.get_settlement(
                self.session, self._household_id(), UUID(str(settlement_id))
            )
        period = self._period(args)
        settlement = self.session.scalar(
            select(Settlement)
            .where(
                Settlement.period_id == period.id,
                Settlement.status == "final",
            )
            .order_by(Settlement.revision.desc())
        )
        if settlement is None:
            raise NotFoundError("该账期没有正式结算")
        return settlement

    def _pending(
        self, *, action_type: str, payload: dict[str, Any], preview: dict[str, Any]
    ) -> PendingAction:
        payload_json = jsonable(payload)
        serialized = json.dumps(
            payload_json, ensure_ascii=False, sort_keys=True, separators=(",", ":")
        )
        action = PendingAction(
            household_id=self._household_id(),
            conversation_id=self.conversation_id,
            requested_by=self.principal.user_id,
            action_type=action_type,
            payload=payload_json,
            payload_hash=hashlib.sha256(serialized.encode("utf-8")).hexdigest(),
            preview=jsonable(preview),
            expires_at=utcnow() + timedelta(minutes=10),
        )
        self.session.add(action)
        self.session.flush()
        record_audit(
            self.session,
            household_id=self._household_id(),
            actor_user_id=self.principal.user_id,
            action="agent.action_prepare",
            entity_type="pending_action",
            entity_id=action.id,
            after={"action_type": action_type, "preview": preview},
            meta={"conversation_id": str(self.conversation_id) if self.conversation_id else None},
        )
        return action

    def _pending_result(self, action: PendingAction, message: str) -> dict[str, Any]:
        return {
            "requires_confirmation": True,
            "pending_action_id": str(action.id),
            "action_type": action.action_type,
            "preview": action.preview,
            "message": message,
            "expires_at": action.expires_at.isoformat(),
        }

    @staticmethod
    def _cents(value: Any) -> int:
        return ToolGateway._int(value, "amount_cents", minimum=0)

    @staticmethod
    def _days(value: Any) -> int:
        return ToolGateway._int(value, "days", minimum=0, maximum=31)

    @staticmethod
    def _int(
        value: Any, name: str, *, minimum: int | None = None, maximum: int | None = None
    ) -> int:
        if isinstance(value, bool) or not isinstance(value, int):
            raise ToolError("INVALID_ARGUMENT", f"{name} 必须是整数")
        if minimum is not None and value < minimum:
            raise ToolError("INVALID_ARGUMENT", f"{name} 不能小于 {minimum}")
        if maximum is not None and value > maximum:
            raise ToolError("INVALID_ARGUMENT", f"{name} 不能大于 {maximum}")
        return value

    @staticmethod
    def _date(value: Any) -> date:
        try:
            return date.fromisoformat(str(value))
        except (TypeError, ValueError) as exc:
            raise ToolError("INVALID_ARGUMENT", "日期必须是 YYYY-MM-DD") from exc
