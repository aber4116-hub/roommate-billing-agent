"""付款 API 幂等与权限测试。"""

from __future__ import annotations

from uuid import uuid4


def test_payment_api_idempotency_and_adjustment(client, seed) -> None:
    # 注意：client 与 member_client 会覆盖同一个 app，因此分开测试更安全；
    # 这里使用 owner client 验证幂等，adjustment 也由 owner 执行。
    payload = {
        "person_id": str(seed.people["lin"]),
        "amount_cents": 1000,
        "paid_on": "2026-10-06",
        "method": "wechat",
    }
    key = str(uuid4())
    first = client.post(
        f"/api/v1/households/{seed.household_id}/periods/{seed.period_id}/payments",
        json=payload,
        headers={"Idempotency-Key": key},
    )
    assert first.status_code == 201, first.text
    payment = first.json()["data"]
    replay = client.post(
        f"/api/v1/households/{seed.household_id}/periods/{seed.period_id}/payments",
        json=payload,
        headers={"Idempotency-Key": key},
    )
    assert replay.status_code == 201
    assert replay.json()["data"]["id"] == payment["id"]

    adjusted = client.post(
        f"/api/v1/households/{seed.household_id}/payments/{payment['id']}/adjustments",
        json={"amount_cents": -100, "reason": "少记"},
        headers={"Idempotency-Key": str(uuid4())},
    )
    assert adjusted.status_code == 201, adjusted.text
    assert adjusted.json()["data"]["kind"] == "adjustment"

    listed = client.get(f"/api/v1/households/{seed.household_id}/periods/{seed.period_id}/payments")
    assert listed.status_code == 200
    assert len(listed.json()["data"]["items"]) == 2
