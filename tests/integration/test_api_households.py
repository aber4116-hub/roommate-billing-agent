"""账本、人员与新建账期 API 测试。"""

from __future__ import annotations


def test_create_household(client, seed) -> None:
    response = client.post("/api/v1/households", json={"name": "第二账本"})
    assert response.status_code == 201, response.text
    assert response.json()["data"]["name"] == "第二账本"
    rows = client.get("/api/v1/households").json()["data"]["items"]
    assert len(rows) == 2


def test_households_people_and_period_creation(client, seed) -> None:
    households = client.get("/api/v1/households")
    assert households.status_code == 200
    assert len(households.json()["data"]["items"]) == 1

    people = client.get(f"/api/v1/households/{seed.household_id}/people")
    assert people.status_code == 200
    assert len(people.json()["data"]["items"]) == 3

    created_person = client.post(
        f"/api/v1/households/{seed.household_id}/people",
        json={"display_name": "新室友", "slug": "newbie"},
    )
    assert created_person.status_code == 201, created_person.text
    assert created_person.json()["data"]["slug"] == "newbie"

    created_period = client.post(
        f"/api/v1/households/{seed.household_id}/periods",
        json={"period_key": "2026-11"},
    )
    assert created_period.status_code == 201, created_period.text
    period = created_period.json()["data"]
    assert period["status"] == "open"
    assert period["version"] == 1

    ledger = client.get(f"/api/v1/households/{seed.household_id}/ledger/current")
    assert ledger.status_code == 200
    from datetime import date

    expected_period = (
        "2026-10" if date(2026, 10, 1) <= date.today() <= date(2026, 10, 31) else "2026-11"
    )
    assert ledger.json()["data"]["period"]["period_key"] == expected_period

    occupancies = client.get(
        f"/api/v1/households/{seed.household_id}/periods/{period['id']}/occupancies"
    )
    assert occupancies.status_code == 200
    assert len(occupancies.json()["data"]["items"]) == 4
    assert all(item["days"] == 0 for item in occupancies.json()["data"]["items"])


def test_duplicate_period_key_conflicts(client, seed) -> None:
    response = client.post(
        f"/api/v1/households/{seed.household_id}/periods",
        json={"period_key": "2026-10"},
    )
    assert response.status_code == 409
    assert response.json()["error"]["code"] == "CONFLICT"
