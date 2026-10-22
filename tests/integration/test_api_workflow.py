"""多用户、结算、规则 API 工作流测试。"""

from __future__ import annotations

from uuid import uuid4


def _period(client, seed) -> dict:
    response = client.get(f"/api/v1/households/{seed.household_id}/periods")
    assert response.status_code == 200
    return next(
        item for item in response.json()["data"]["items"] if item["id"] == str(seed.period_id)
    )


def test_member_can_record_own_payment_only(member_client, seed) -> None:
    own = member_client.post(
        f"/api/v1/households/{seed.household_id}/periods/{seed.period_id}/payments",
        json={
            "person_id": str(seed.people["lin"]),
            "amount_cents": 1000,
            "paid_on": "2026-10-06",
            "method": "wechat",
        },
        headers={"Idempotency-Key": str(uuid4())},
    )
    assert own.status_code == 201, own.text

    other = member_client.post(
        f"/api/v1/households/{seed.household_id}/periods/{seed.period_id}/payments",
        json={
            "person_id": str(seed.people["zhe"]),
            "amount_cents": 1000,
            "paid_on": "2026-10-06",
        },
        headers={"Idempotency-Key": str(uuid4())},
    )
    assert other.status_code == 403


def test_settlement_api_flow_and_idempotency(client, seed) -> None:
    current = _period(client, seed)
    locked = client.post(
        f"/api/v1/households/{seed.household_id}/periods/{seed.period_id}/lock",
        json={"expected_version": current["version"]},
    )
    assert locked.status_code == 200, locked.text
    assert locked.json()["data"]["status"] == "locked"

    preview = client.get(
        f"/api/v1/households/{seed.household_id}/periods/{seed.period_id}/settlement-preview"
    )
    assert preview.status_code == 200
    pdata = preview.json()["data"]
    assert pdata["bills_total_cents"] == 49305
    key = str(uuid4())
    body = {
        "expected_period_version": pdata["period_version"],
        "preview_hash": pdata["preview_hash"],
    }
    created = client.post(
        f"/api/v1/households/{seed.household_id}/periods/{seed.period_id}/settlements",
        json=body,
        headers={"Idempotency-Key": key},
    )
    assert created.status_code == 201, created.text
    settlement = created.json()["data"]
    assert settlement["revision"] == 1
    assert len(settlement["lines"]) == 3

    replay = client.post(
        f"/api/v1/households/{seed.household_id}/periods/{seed.period_id}/settlements",
        json=body,
        headers={"Idempotency-Key": key},
    )
    assert replay.status_code == 201
    assert replay.json()["data"]["id"] == settlement["id"]

    detail = client.get(f"/api/v1/households/{seed.household_id}/settlements/{settlement['id']}")
    assert detail.status_code == 200
    assert len(detail.json()["data"]["lines"]) == 3

    explain = client.get(
        f"/api/v1/households/{seed.household_id}/settlements/{settlement['id']}/explain",
        params={"person_id": str(seed.people["lin"])},
    )
    assert explain.status_code == 200
    assert explain.json()["data"]["allocated_cents"] == 12494

    export = client.get(
        f"/api/v1/households/{seed.household_id}/settlements/{settlement['id']}/export"
    )
    assert export.status_code == 200
    assert "text/csv" in export.headers["content-type"]
    assert "2026-10" in export.text

    blocked_payment = client.post(
        f"/api/v1/households/{seed.household_id}/periods/{seed.period_id}/payments",
        json={
            "person_id": str(seed.people["lin"]),
            "amount_cents": 100,
            "paid_on": "2026-10-07",
        },
        headers={"Idempotency-Key": str(uuid4())},
    )
    assert blocked_payment.status_code == 409
    assert blocked_payment.json()["error"]["code"] == "PERIOD_SETTLED"


def test_reopen_and_second_settlement(client, seed) -> None:
    current = _period(client, seed)
    client.post(
        f"/api/v1/households/{seed.household_id}/periods/{seed.period_id}/lock",
        json={"expected_version": current["version"]},
    )
    preview = client.get(
        f"/api/v1/households/{seed.household_id}/periods/{seed.period_id}/settlement-preview"
    ).json()["data"]
    first = client.post(
        f"/api/v1/households/{seed.household_id}/periods/{seed.period_id}/settlements",
        json={
            "expected_period_version": preview["period_version"],
            "preview_hash": preview["preview_hash"],
        },
        headers={"Idempotency-Key": str(uuid4())},
    ).json()["data"]

    settled_period = _period(client, seed)
    reopened = client.post(
        f"/api/v1/households/{seed.household_id}/periods/{seed.period_id}/reopen",
        json={
            "expected_version": settled_period["version"],
            "reason": "补录",
        },
    )
    assert reopened.status_code == 200, reopened.text
    assert reopened.json()["data"]["status"] == "open"

    payment = client.post(
        f"/api/v1/households/{seed.household_id}/periods/{seed.period_id}/payments",
        json={
            "person_id": str(seed.people["lin"]),
            "amount_cents": 100,
            "paid_on": "2026-10-08",
        },
        headers={"Idempotency-Key": str(uuid4())},
    )
    assert payment.status_code == 201

    current = _period(client, seed)
    client.post(
        f"/api/v1/households/{seed.household_id}/periods/{seed.period_id}/lock",
        json={"expected_version": current["version"]},
    )
    preview2 = client.get(
        f"/api/v1/households/{seed.household_id}/periods/{seed.period_id}/settlement-preview"
    ).json()["data"]
    second = client.post(
        f"/api/v1/households/{seed.household_id}/periods/{seed.period_id}/settlements",
        json={
            "expected_period_version": preview2["period_version"],
            "preview_hash": preview2["preview_hash"],
        },
        headers={"Idempotency-Key": str(uuid4())},
    )
    assert second.status_code == 201, second.text
    assert second.json()["data"]["revision"] == 2
    history = client.get(
        f"/api/v1/households/{seed.household_id}/periods/{seed.period_id}/settlements"
    ).json()["data"]["items"]
    assert [row["revision"] for row in history] == [2, 1]
    assert history[1]["status"] == "superseded"
    assert first["revision"] == 1
