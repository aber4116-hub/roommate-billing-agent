"""本地/CI 演示数据（不用于生产）。

用法：
  $env:DEMO_PASSWORD="至少十二位密码"
  .\\.venv\\Scripts\\python.exe scripts/seed_demo.py
"""

from __future__ import annotations

import os
from datetime import date
from uuid import uuid4

from sqlalchemy import select

from roommate_billing.db.models import BillingPeriod, Household, Person, RuleVersion, User
from roommate_billing.db.session import SessionLocal
from roommate_billing.security.passwords import hash_password
from roommate_billing.services import bills, households, payments, periods, rules


def main() -> None:
    email = os.environ.get("DEMO_EMAIL", "demo@example.com").strip().lower()
    password = os.environ.get("DEMO_PASSWORD", "")
    if len(password) < 12:
        raise SystemExit("设置 DEMO_PASSWORD（至少 12 位）后再运行")
    household_name = os.environ.get("DEMO_HOUSEHOLD", "演示合租账本")
    today = date.today()
    period_key = f"{today.year:04d}-{today.month:02d}"

    with SessionLocal() as session:
        user = session.scalar(select(User).where(User.email == email))
        if user is None:
            user = User(
                email=email,
                display_name="演示房东",
                password_hash=hash_password(password),
            )
            session.add(user)
            session.flush()
        household = session.scalar(
            select(Household).where(
                Household.name == household_name,
                Household.created_by == user.id,
            )
        )
        if household is None:
            household = households.create_household(
                session,
                name=household_name,
                actor_user_id=user.id,
                request_id=uuid4(),
            )
        existing = session.scalar(
            select(BillingPeriod).where(
                BillingPeriod.household_id == household.id,
                BillingPeriod.period_key == period_key,
            )
        )
        if existing is not None:
            session.commit()
            print(f"demo already exists: {email} / {household.name} / {period_key}")
            return

        people = {}
        for slug, name, linked_user in (
            ("lin", "小林", None),
            ("zhe", "阿哲", None),
            ("zhou", "小周", None),
        ):
            person = session.scalar(
                select(Person).where(
                    Person.household_id == household.id,
                    Person.slug == slug,
                )
            )
            if person is None:
                person = Person(
                    household_id=household.id,
                    display_name=name,
                    slug=slug,
                    user_id=linked_user,
                    is_active=True,
                    version=1,
                )
                session.add(person)
                session.flush()
            people[slug] = person

        if not session.scalar(
            select(Person).where(
                Person.household_id == household.id,
                Person.is_active.is_(True),
            )
        ):
            raise SystemExit("demo people missing")
        if not session.scalar(
            select(RuleVersion).where(
                RuleVersion.household_id == household.id,
                RuleVersion.status == "active",
            )
        ):
            rules.create_initial_rule(
                session,
                household_id=household.id,
                owner_person_id=people["zhou"].id,
                actor_user_id=user.id,
                request_id=uuid4(),
            )
        period = periods.create_period(
            session,
            household_id=household.id,
            actor_user_id=user.id,
            period_key=period_key,
            request_id=uuid4(),
        )
        periods.set_occupancies(
            session,
            household_id=household.id,
            period_id=period.id,
            actor_user_id=user.id,
            items=[
                {"person_id": people["lin"].id, "days": 18},
                {"person_id": people["zhe"].id, "days": 30},
                {"person_id": people["zhou"].id, "days": 30},
            ],
            expected_version=period.version,
            request_id=uuid4(),
        )
        for category, name, amount in (
            ("electricity", "电费", 28765),
            ("water", "水费", 9640),
            ("internet", "宽带费", 8900),
            ("trash", "垃圾清运费", 2000),
        ):
            bills.create_bill(
                session,
                household_id=household.id,
                period_id=period.id,
                actor_user_id=user.id,
                category=category,
                name=name,
                amount_cents=amount,
                request_id=uuid4(),
            )
        payments.record_payment(
            session,
            household_id=household.id,
            period_id=period.id,
            actor_user_id=user.id,
            person_id=people["lin"].id,
            amount_cents=12000,
            paid_on=today,
            method="wechat",
            request_id=uuid4(),
        )
        session.commit()
        print(f"demo ready: {email} / {household.name} / {period_key}")


if __name__ == "__main__":
    main()
