"""账单 API 集成测试。"""

from __future__ import annotations

from uuid import uuid4


def test_current_ledger_and_create_bill(client, seed) -> None:
    response = client.get(f"/api/v1/households/{seed.household_id}/ledger/current")
    assert response.status_code == 200
    data = response.json()["data"]
    assert data["bills_total_cents"] == 49305
    assert data["allocated_total_cents"] == 49305

    key = str(uuid4())
    body = {
        "category": "other",
        "name": "清洁用品",
        "amount_cents": 1000,
    }
    created = client.post(
        f"/api/v1/households/{seed.household_id}/periods/{seed.period_id}/bills",
        json=body,
        headers={"Idempotency-Key": key},
    )
    assert created.status_code == 201, created.text
    bill = created.json()["data"]
    assert bill["amount_cents"] == 1000
    assert sum(row["amount_cents"] for row in bill["allocations"]) == 1000

    replay = client.post(
        f"/api/v1/households/{seed.household_id}/periods/{seed.period_id}/bills",
        json=body,
        headers={"Idempotency-Key": key},
    )
    assert replay.status_code == 201
    assert replay.json()["data"]["id"] == bill["id"]


def test_duplicate_idempotency_key_with_different_body_conflicts(client, seed) -> None:
    key = str(uuid4())
    url = f"/api/v1/households/{seed.household_id}/periods/{seed.period_id}/bills"
    first = client.post(
        url,
        json={"category": "other", "name": "A", "amount_cents": 100},
        headers={"Idempotency-Key": key},
    )
    assert first.status_code == 201
    second = client.post(
        url,
        json={"category": "other", "name": "B", "amount_cents": 200},
        headers={"Idempotency-Key": key},
    )
    assert second.status_code == 409
    assert second.json()["error"]["code"] == "IDEMPOTENCY_KEY_REUSED"


def test_bill_create_requires_idempotency_key(client, seed) -> None:
    response = client.post(
        f"/api/v1/households/{seed.household_id}/periods/{seed.period_id}/bills",
        json={"category": "other", "name": "无 key", "amount_cents": 100},
    )
    assert response.status_code == 409
    assert response.json()["error"]["code"] == "IDEMPOTENCY_KEY_REQUIRED"


def test_member_cannot_create_bill(member_client, seed) -> None:
    response = member_client.post(
        f"/api/v1/households/{seed.household_id}/periods/{seed.period_id}/bills",
        json={"category": "other", "name": "越权", "amount_cents": 100},
        headers={"Idempotency-Key": str(uuid4())},
    )
    assert response.status_code == 403
    assert response.json()["error"]["code"] == "FORBIDDEN"


def test_cross_household_is_hidden(client, seed) -> None:
    response = client.get(f"/api/v1/households/{uuid4()}/periods")
    assert response.status_code == 404
    assert response.json()["error"]["code"] == "NOT_FOUND"


def test_invalid_negative_amount_does_not_write(client, seed) -> None:
    response = client.post(
        f"/api/v1/households/{seed.household_id}/periods/{seed.period_id}/bills",
        json={"category": "other", "name": "负数", "amount_cents": -1},
        headers={"Idempotency-Key": str(uuid4())},
    )
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "VALIDATION_ERROR"
