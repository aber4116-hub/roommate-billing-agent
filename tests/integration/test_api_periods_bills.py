"""账期、入住天数与账单修改 API 测试。"""

from __future__ import annotations

from uuid import uuid4


def _period(client, seed) -> dict:
    rows = client.get(f"/api/v1/households/{seed.household_id}/periods").json()["data"]["items"]
    return next(row for row in rows if row["id"] == str(seed.period_id))


def test_occupancies_api_recalculates(client, seed) -> None:
    period = _period(client, seed)
    before = client.get(
        f"/api/v1/households/{seed.household_id}/periods/{seed.period_id}/bills"
    ).json()["data"]["items"]
    electricity_before = next(row for row in before if row["category"] == "electricity")
    assert [r["amount_cents"] for r in electricity_before["allocations"]] == [
        6638,
        11063,
        11064,
    ]

    response = client.put(
        f"/api/v1/households/{seed.household_id}/periods/{seed.period_id}/occupancies",
        json={
            "expected_version": period["version"],
            "items": [
                {"person_id": str(seed.people["lin"]), "days": 30},
                {"person_id": str(seed.people["zhe"]), "days": 30},
                {"person_id": str(seed.people["zhou"]), "days": 30},
            ],
        },
    )
    assert response.status_code == 200, response.text
    after = client.get(
        f"/api/v1/households/{seed.household_id}/periods/{seed.period_id}/bills"
    ).json()["data"]["items"]
    electricity_after = next(row for row in after if row["category"] == "electricity")
    assert [r["amount_cents"] for r in electricity_after["allocations"]] == [
        9588,
        9588,
        9589,
    ]


def test_member_cannot_change_occupancies(member_client, seed) -> None:
    period = _period(member_client, seed)
    response = member_client.put(
        f"/api/v1/households/{seed.household_id}/periods/{seed.period_id}/occupancies",
        json={
            "expected_version": period["version"],
            "items": [{"person_id": str(seed.people["lin"]), "days": 30}],
        },
    )
    assert response.status_code == 403


def test_bill_patch_and_void_api(client, seed) -> None:
    bills = client.get(
        f"/api/v1/households/{seed.household_id}/periods/{seed.period_id}/bills"
    ).json()["data"]["items"]
    electricity = next(row for row in bills if row["category"] == "electricity")
    updated = client.patch(
        f"/api/v1/households/{seed.household_id}/bills/{electricity['id']}",
        json={"expected_version": electricity["version"], "amount_cents": 30000},
    )
    assert updated.status_code == 200, updated.text
    changed = updated.json()["data"]
    assert changed["amount_cents"] == 30000
    assert [r["amount_cents"] for r in changed["allocations"]] == [6923, 11538, 11539]

    voided = client.post(
        f"/api/v1/households/{seed.household_id}/bills/{electricity['id']}/void",
        json={"expected_version": changed["version"], "reason": "重复录入"},
        headers={"Idempotency-Key": str(uuid4())},
    )
    assert voided.status_code == 200, voided.text
    assert voided.json()["data"]["status"] == "voided"
    assert voided.json()["data"]["allocations"] == []


def test_stale_patch_returns_conflict(client, seed) -> None:
    bills = client.get(
        f"/api/v1/households/{seed.household_id}/periods/{seed.period_id}/bills"
    ).json()["data"]["items"]
    electricity = next(row for row in bills if row["category"] == "electricity")
    response = client.patch(
        f"/api/v1/households/{seed.household_id}/bills/{electricity['id']}",
        json={"expected_version": electricity["version"] + 10, "amount_cents": 100},
    )
    assert response.status_code == 409
    assert response.json()["error"]["code"] == "VERSION_CONFLICT"
