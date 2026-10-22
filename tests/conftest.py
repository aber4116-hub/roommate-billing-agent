"""集成测试夹具：真实 PostgreSQL + Alembic 迁移。"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from uuid import UUID, uuid4

import pytest
from alembic import command
from alembic.config import Config
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session, sessionmaker

from roommate_billing.api.deps import Principal, get_current_principal
from roommate_billing.config import get_settings
from roommate_billing.db.base import Base
from roommate_billing.db.models import Household, HouseholdMember, Person, User
from roommate_billing.db.session import get_db
from roommate_billing.main import create_app
from roommate_billing.security.passwords import hash_password
from roommate_billing.services import bills, periods, rules

ROOT = Path(__file__).resolve().parents[1]
TEST_PASSWORD = "correct-horse-battery-staple"
TEST_PASSWORD_HASH = hash_password(TEST_PASSWORD)


@pytest.fixture(scope="session")
def test_database_url() -> str:
    settings = get_settings()
    url = settings.test_database_url
    if not url:
        pytest.fail("TEST_DATABASE_URL 未配置；集成测试需要 PostgreSQL 16")
    if "/roommate_test" not in url:
        pytest.fail("TEST_DATABASE_URL 必须指向测试数据库 roommate_test")
    return url


@pytest.fixture(scope="session")
def engine(test_database_url: str):
    engine = create_engine(test_database_url, pool_pre_ping=True)
    with engine.begin() as connection:
        connection.execute(text("DROP SCHEMA public CASCADE"))
        connection.execute(text("CREATE SCHEMA public"))
    os.environ["DATABASE_URL"] = test_database_url
    config = Config(str(ROOT / "alembic.ini"))
    config.set_main_option("sqlalchemy.url", test_database_url)
    command.upgrade(config, "head")
    yield engine
    engine.dispose()


@pytest.fixture(scope="session")
def session_factory(engine) -> sessionmaker[Session]:
    return sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)


@pytest.fixture(autouse=True)
def reset_database(engine) -> None:
    tables = ", ".join(f'"{table.name}"' for table in Base.metadata.sorted_tables)
    with engine.begin() as connection:
        connection.execute(text(f"TRUNCATE TABLE {tables} RESTART IDENTITY CASCADE"))


@pytest.fixture
def db_session(session_factory: sessionmaker[Session]):
    session = session_factory()
    try:
        yield session
    finally:
        session.close()


@dataclass(frozen=True)
class SeedData:
    user_id: UUID
    member_user_id: UUID
    household_id: UUID
    people: dict[str, UUID]
    period_id: UUID


@pytest.fixture
def seed(db_session: Session) -> SeedData:
    user = User(
        email="owner@example.com",
        display_name="Owner",
        password_hash=TEST_PASSWORD_HASH,
    )
    member_user = User(
        email="member@example.com",
        display_name="Member",
        password_hash=TEST_PASSWORD_HASH,
    )
    db_session.add_all([user, member_user])
    db_session.flush()

    household = Household(
        name="Test Household",
        created_by=user.id,
    )
    db_session.add(household)
    db_session.flush()
    db_session.add_all(
        [
            HouseholdMember(
                household_id=household.id,
                user_id=user.id,
                role="owner",
                status="active",
            ),
            HouseholdMember(
                household_id=household.id,
                user_id=member_user.id,
                role="member",
                status="active",
            ),
        ]
    )
    db_session.flush()

    people: dict[str, UUID] = {}
    for slug, name, linked_user in (
        ("lin", "小林", member_user.id),
        ("zhe", "阿哲", None),
        ("zhou", "小周", None),
    ):
        person = Person(
            household_id=household.id,
            display_name=name,
            slug=slug,
            user_id=linked_user,
            is_active=True,
            version=1,
        )
        db_session.add(person)
        db_session.flush()
        people[slug] = person.id

    rules.create_initial_rule(
        db_session,
        household_id=household.id,
        owner_person_id=people["zhou"],
        actor_user_id=user.id,
        request_id=uuid4(),
    )
    period = periods.create_period(
        db_session,
        household_id=household.id,
        actor_user_id=user.id,
        period_key="2026-10",
        request_id=uuid4(),
    )
    periods.set_occupancies(
        db_session,
        household_id=household.id,
        period_id=period.id,
        actor_user_id=user.id,
        items=[
            {"person_id": people["lin"], "days": 18},
            {"person_id": people["zhe"], "days": 30},
            {"person_id": people["zhou"], "days": 30},
        ],
        expected_version=1,
        request_id=uuid4(),
    )
    for category, name, amount in (
        ("electricity", "电费", 28765),
        ("water", "水费", 9640),
        ("internet", "宽带费", 8900),
        ("trash", "垃圾清运费", 2000),
    ):
        bills.create_bill(
            db_session,
            household_id=household.id,
            period_id=period.id,
            actor_user_id=user.id,
            category=category,
            name=name,
            amount_cents=amount,
            request_id=uuid4(),
        )
    db_session.commit()
    db_session.refresh(period)
    return SeedData(
        user_id=user.id,
        member_user_id=member_user.id,
        household_id=household.id,
        people=people,
        period_id=period.id,
    )


@pytest.fixture
def owner_principal(seed: SeedData) -> Principal:
    return Principal(
        user_id=seed.user_id,
        household_id=seed.household_id,
        role="owner",
        memberships={seed.household_id: "owner"},
        person_ids={seed.household_id: None},
    )


@pytest.fixture
def member_principal(seed: SeedData) -> Principal:
    return Principal(
        user_id=seed.member_user_id,
        household_id=seed.household_id,
        role="member",
        person_id=seed.people["lin"],
        memberships={seed.household_id: "member"},
        person_ids={seed.household_id: seed.people["lin"]},
    )


@pytest.fixture
def app():
    return create_app()


@pytest.fixture
def client(app, session_factory, owner_principal):
    def override_db():
        session = session_factory()
        try:
            yield session
            session.commit()
        except Exception:
            session.rollback()
            raise
        finally:
            session.close()

    app.dependency_overrides[get_current_principal] = lambda: owner_principal
    app.dependency_overrides[get_db] = override_db
    with TestClient(app) as test_client:
        yield test_client
    app.dependency_overrides.clear()


@pytest.fixture
def member_client(app, session_factory, member_principal):
    def override_db():
        session = session_factory()
        try:
            yield session
            session.commit()
        except Exception:
            session.rollback()
            raise
        finally:
            session.close()

    app.dependency_overrides[get_current_principal] = lambda: member_principal
    app.dependency_overrides[get_db] = override_db
    with TestClient(app) as test_client:
        yield test_client
    app.dependency_overrides.clear()


@pytest.fixture
def auth_app():
    return create_app()


@pytest.fixture
def auth_client(auth_app, session_factory):
    def override_db():
        session = session_factory()
        try:
            yield session
            session.commit()
        except Exception:
            session.rollback()
            raise
        finally:
            session.close()

    auth_app.dependency_overrides[get_db] = override_db
    with TestClient(auth_app) as test_client:
        yield test_client
    auth_app.dependency_overrides.clear()
