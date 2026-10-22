"""账本与人员基础服务。"""

from __future__ import annotations

import re
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from ..db.models import Household, HouseholdMember, Person
from .audit import record_audit
from .errors import ConflictError, NotFoundError, ValidationError

SLUG_RE = re.compile(r"^[a-z][a-z0-9_]{0,39}$")


def create_household(
    session: Session,
    *,
    name: str,
    actor_user_id: UUID,
    request_id: UUID | None = None,
) -> Household:
    if not name or len(name) > 120:
        raise ValidationError("账本名称长度必须为 1–120")
    household = Household(name=name.strip(), created_by=actor_user_id)
    session.add(household)
    session.flush()
    session.add(
        HouseholdMember(
            household_id=household.id,
            user_id=actor_user_id,
            role="owner",
            status="active",
        )
    )
    session.flush()
    record_audit(
        session,
        household_id=household.id,
        actor_user_id=actor_user_id,
        action="household.create",
        entity_type="household",
        entity_id=household.id,
        after={"name": household.name},
        request_id=request_id,
    )
    return household


def get_household(session: Session, household_id: UUID) -> Household:
    household = session.get(Household, household_id)
    if household is None:
        raise NotFoundError("账本不存在")
    return household


def list_households(session: Session, user_id: UUID) -> list[Household]:
    return list(
        session.scalars(
            select(Household)
            .join(HouseholdMember, HouseholdMember.household_id == Household.id)
            .where(
                HouseholdMember.user_id == user_id,
                HouseholdMember.status == "active",
            )
            .order_by(Household.created_at)
        )
    )


def list_people(session: Session, household_id: UUID) -> list[Person]:
    return list(
        session.scalars(
            select(Person)
            .where(Person.household_id == household_id)
            .order_by(Person.slug, Person.id)
        )
    )


def create_person(
    session: Session,
    *,
    household_id: UUID,
    actor_user_id: UUID,
    display_name: str,
    slug: str | None = None,
    user_id: UUID | None = None,
    request_id: UUID | None = None,
) -> Person:
    if not display_name or len(display_name) > 80:
        raise ValidationError("人员名称长度必须为 1–80")
    if slug is None:
        # 仅允许 ASCII 小写 slug；中文显示名由调用方显式传 slug。
        base = "person"
        index = 1
        while session.scalar(
            select(Person.id).where(
                Person.household_id == household_id,
                Person.slug == f"{base}{index}",
            )
        ):
            index += 1
        slug = f"{base}{index}"
    if not SLUG_RE.fullmatch(slug):
        raise ValidationError("slug 必须是小写字母开头的 1–40 位 ASCII 标识")
    if user_id is not None and session.scalar(
        select(Person.id).where(
            Person.household_id == household_id,
            Person.user_id == user_id,
        )
    ):
        raise ConflictError("该用户已绑定本账本的其他人员")
    person = Person(
        household_id=household_id,
        display_name=display_name.strip(),
        slug=slug,
        user_id=user_id,
        is_active=True,
        version=1,
    )
    session.add(person)
    try:
        session.flush()
    except IntegrityError as exc:
        raise ConflictError("人员 slug 已存在") from exc
    record_audit(
        session,
        household_id=household_id,
        actor_user_id=actor_user_id,
        action="person.create",
        entity_type="person",
        entity_id=person.id,
        after={"display_name": person.display_name, "slug": person.slug},
        request_id=request_id,
    )
    return person


def get_person(session: Session, household_id: UUID, person_id: UUID) -> Person:
    person = session.scalar(
        select(Person).where(
            Person.id == person_id,
            Person.household_id == household_id,
        )
    )
    if person is None:
        raise NotFoundError("人员不存在")
    return person
