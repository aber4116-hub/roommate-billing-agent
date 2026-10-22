"""规则版本 API 测试。"""

from __future__ import annotations

from uuid import uuid4


def _items() -> list[dict[str, str]]:
    return [
        {"category": "electricity", "split_method": "days", "fallback_method": "equal_household"},
        {
            "category": "water",
            "split_method": "equal_household",
            "fallback_method": "equal_household",
        },
        {
            "category": "internet",
            "split_method": "equal_household",
            "fallback_method": "equal_household",
        },
        {
            "category": "trash",
            "split_method": "equal_household",
            "fallback_method": "equal_household",
        },
        {
            "category": "other",
            "split_method": "equal_household",
            "fallback_method": "equal_household",
        },
    ]


def test_rule_draft_preview_activate(client, seed) -> None:
    created = client.post(
        f"/api/v1/households/{seed.household_id}/rule-versions",
        json={
            "owner_person_id": str(seed.people["zhou"]),
            "items": _items(),
            "note": "水费改按户",
        },
        headers={"Idempotency-Key": str(uuid4())},
    )
    assert created.status_code == 201, created.text
    draft = created.json()["data"]
    assert draft["status"] == "draft"

    previewed = client.post(
        f"/api/v1/households/{seed.household_id}/rule-versions/{draft['id']}/preview"
    )
    assert previewed.status_code == 200, previewed.text
    pdata = previewed.json()["data"]
    assert pdata["preview_hash"]
    assert pdata["preview"]["periods"][0]["period_key"] == "2026-10"

    activated = client.post(
        f"/api/v1/households/{seed.household_id}/rule-versions/{draft['id']}/activate",
        json={
            "expected_active_version_no": 1,
            "expected_preview_hash": pdata["preview_hash"],
            "expected_row_version": draft["row_version"],
        },
        headers={"Idempotency-Key": str(uuid4())},
    )
    assert activated.status_code == 200, activated.text
    assert activated.json()["data"]["status"] == "active"

    bills = client.get(
        f"/api/v1/households/{seed.household_id}/periods/{seed.period_id}/bills"
    ).json()["data"]["items"]
    water = next(row for row in bills if row["category"] == "water")
    assert [row["amount_cents"] for row in water["allocations"]] == [3213, 3213, 3214]


def test_member_cannot_create_rule(member_client, seed) -> None:
    response = member_client.post(
        f"/api/v1/households/{seed.household_id}/rule-versions",
        json={
            "owner_person_id": str(seed.people["zhou"]),
            "items": _items(),
            "note": "越权",
        },
        headers={"Idempotency-Key": str(uuid4())},
    )
    assert response.status_code == 403
