"""分摊守恒属性测试。"""

from __future__ import annotations

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from roommate_billing.domain.allocation import split_cents
from roommate_billing.domain.money import MAX_BILL_CENTS


@st.composite
def allocation_inputs(draw) -> tuple[int, list[int], int]:
    count = draw(st.integers(min_value=1, max_value=20))
    weights = draw(st.lists(st.integers(min_value=0, max_value=31), min_size=count, max_size=count))
    owner = draw(st.integers(min_value=0, max_value=count - 1))
    total = draw(st.integers(min_value=0, max_value=MAX_BILL_CENTS))
    return total, weights, owner


@given(allocation_inputs())
@settings(max_examples=5000, deadline=None)
def test_conservation_and_remainder_policy(
    inputs: tuple[int, list[int], int],
) -> None:
    total, weights, owner = inputs
    result = split_cents(total, weights, owner_index=owner)

    assert len(result.lines) == len(weights)
    assert sum(result.amounts) == total
    assert all(isinstance(value, int) for value in result.amounts)
    assert all(line.amount_cents == line.base_cents + line.remainder_cents for line in result.lines)
    assert all(line.remainder_cents >= 0 for line in result.lines)

    # 所有零头只归 owner；且金额小于人数（不可能多出一整分给两个人）。
    for line in result.lines:
        if line.index != owner:
            assert line.remainder_cents == 0
            assert line.is_remainder_owner is False
    owner_line = result.lines[owner]
    assert owner_line.remainder_cents == total - sum(line.base_cents for line in result.lines)
    assert owner_line.is_remainder_owner == (owner_line.remainder_cents > 0)
    assert owner_line.remainder_cents < len(weights)

    # 权重全零时必须使用显式等权 fallback。
    if sum(weights) == 0:
        assert result.fallback_used is True
        assert result.total_weight == len(weights)
        assert [line.weight for line in result.lines] == [1] * len(weights)
    else:
        assert result.fallback_used is False
        assert result.total_weight == sum(weights)

    # 同输入必须完全确定。
    assert split_cents(total, weights, owner_index=owner) == result


@st.composite
def signed_allocation_inputs(draw) -> tuple[int, list[int], int]:
    count = draw(st.integers(min_value=1, max_value=10))
    weights = draw(st.lists(st.integers(min_value=0, max_value=10), min_size=count, max_size=count))
    owner = draw(st.integers(min_value=0, max_value=count - 1))
    total = draw(st.integers(min_value=-MAX_BILL_CENTS, max_value=MAX_BILL_CENTS))
    return total, weights, owner


@given(signed_allocation_inputs())
@settings(max_examples=1000, deadline=None)
def test_signed_conservation(inputs: tuple[int, list[int], int]) -> None:
    total, weights, owner = inputs
    result = split_cents(total, weights, owner_index=owner)

    assert sum(result.amounts) == total
    assert result.remainder_total_cents == total - sum(line.base_cents for line in result.lines)
    assert all(line.amount_cents == line.base_cents + line.remainder_cents for line in result.lines)
    assert all(line.remainder_cents == 0 for line in result.lines if line.index != owner)
    if total < 0:
        assert all(line.remainder_cents <= 0 for line in result.lines)
        assert result.lines[owner].remainder_cents <= 0
    elif total > 0:
        assert all(line.remainder_cents >= 0 for line in result.lines)
        assert result.lines[owner].remainder_cents >= 0
    else:
        assert all(line.remainder_cents == 0 for line in result.lines)


def test_hypothesis_smoke() -> None:
    # 显式固定样例，确保属性测试环境失效时仍有一个最小回归点。
    result = split_cents(8900, [1, 1, 1], owner_index=2)
    assert result.amounts == (2966, 2966, 2968)


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__]))
