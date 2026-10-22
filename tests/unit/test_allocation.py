"""整数分摊引擎测试。"""

from __future__ import annotations

import pytest

from roommate_billing.domain.allocation import split_cents, split_equal
from roommate_billing.domain.errors import (
    ConservationError,
    EmptyWeightsError,
    InvalidFallbackError,
    InvalidOwnerError,
    InvalidTotalError,
    InvalidWeightError,
)
from roommate_billing.domain.money import MAX_BILL_CENTS


def amounts(result):
    return result.amounts


def test_electricity_by_days() -> None:
    result = split_cents(28765, [18, 30, 30], owner_index=2)
    assert amounts(result) == (6638, 11063, 11064)
    assert result.total_cents == 28765
    assert sum(amounts(result)) == 28765
    assert result.owner_index == 2
    assert result.total_weight == 78
    assert result.fallback_used is False


def test_water_by_days() -> None:
    result = split_cents(9640, [18, 30, 30], owner_index=2)
    assert amounts(result) == (2224, 3707, 3709)
    assert sum(amounts(result)) == 9640


def test_equal_household_internet() -> None:
    result = split_cents(8900, [1, 1, 1], owner_index=2)
    assert amounts(result) == (2966, 2966, 2968)
    assert result.lines[2].remainder_cents == 2
    assert result.lines[2].is_remainder_owner is True
    assert result.lines[0].is_remainder_owner is False
    assert result.lines[1].is_remainder_owner is False


def test_equal_household_trash() -> None:
    result = split_cents(2000, [1, 1, 1], owner_index=2)
    assert amounts(result) == (666, 666, 668)


def test_remainder_only_goes_to_owner() -> None:
    result = split_cents(100, [1, 1, 1], owner_index=1)
    assert amounts(result) == (33, 34, 33)
    assert [line.remainder_cents for line in result.lines] == [0, 1, 0]
    assert result.lines[1].is_remainder_owner is True
    assert sum(line.remainder_cents for line in result.lines) == 1


def test_no_remainder_means_no_owner_flag() -> None:
    result = split_cents(300, [1, 1, 1], owner_index=2)
    assert amounts(result) == (100, 100, 100)
    assert all(line.remainder_cents == 0 for line in result.lines)
    assert all(line.is_remainder_owner is False for line in result.lines)


def test_zero_total() -> None:
    result = split_cents(0, [18, 30, 30], owner_index=2)
    assert amounts(result) == (0, 0, 0)
    assert result.remainder_total_cents == 0
    assert result.fallback_used is False


def test_zero_total_with_zero_weights_uses_equal_fallback() -> None:
    result = split_cents(0, [0, 0, 0], owner_index=2)
    assert amounts(result) == (0, 0, 0)
    assert result.fallback_used is True
    assert result.total_weight == 3


def test_all_zero_weights_use_equal_fallback() -> None:
    result = split_cents(2000, [0, 0, 0], owner_index=2)
    assert amounts(result) == (666, 666, 668)
    assert result.fallback_used is True
    assert [line.weight for line in result.lines] == [1, 1, 1]
    assert result.total_weight == 3


def test_zero_weight_for_one_person() -> None:
    result = split_cents(1000, [0, 1, 1], owner_index=2)
    assert amounts(result) == (0, 500, 500)
    assert result.fallback_used is False


def test_single_person_gets_full_amount() -> None:
    result = split_cents(12345, [7], owner_index=0)
    assert amounts(result) == (12345,)
    assert result.lines[0].remainder_cents == 0
    assert result.total_weight == 7


def test_single_person_zero_weight_falls_back_to_one() -> None:
    result = split_cents(12345, [0], owner_index=0)
    assert amounts(result) == (12345,)
    assert result.fallback_used is True


def test_negative_amount_keeps_sign_and_conservation() -> None:
    result = split_cents(-8900, [1, 1, 1], owner_index=2)
    assert amounts(result) == (-2966, -2966, -2968)
    assert sum(amounts(result)) == -8900
    assert result.lines[2].remainder_cents == -2
    assert result.lines[2].is_remainder_owner is True
    assert result.lines[0].remainder_cents == 0
    assert result.lines[0].base_cents == -2966


def test_negative_amount_owner_can_be_zero_index() -> None:
    result = split_cents(-100, [1, 1, 1], owner_index=0)
    assert amounts(result) == (-34, -33, -33)
    assert sum(amounts(result)) == -100


def test_negative_amount_zero_total() -> None:
    result = split_cents(0, [1, 1, 1], owner_index=2)
    assert amounts(result) == (0, 0, 0)
    assert result.remainder_total_cents == 0


def test_large_amount_conserves() -> None:
    result = split_cents(MAX_BILL_CENTS, [1, 1, 1], owner_index=2)
    assert sum(amounts(result)) == MAX_BILL_CENTS
    assert len(result.lines) == 3


def test_amount_above_limit_rejected() -> None:
    with pytest.raises(InvalidTotalError):
        split_cents(MAX_BILL_CENTS + 1, [1, 1, 1], owner_index=2)


def test_invalid_total_type() -> None:
    for value in (1.0, "100", True, None):
        with pytest.raises(InvalidTotalError):
            split_cents(value, [1, 1, 1], owner_index=2)  # type: ignore[arg-type]


def test_invalid_max_limit() -> None:
    for value in (0, -1, True, 1.0):
        with pytest.raises(InvalidTotalError):
            split_cents(100, [1], owner_index=0, max_abs_cents=value)  # type: ignore[arg-type]


def test_empty_weights_rejected() -> None:
    with pytest.raises(EmptyWeightsError):
        split_cents(100, [], owner_index=0)


def test_invalid_weights_rejected() -> None:
    for weights in ([1, -1], [1, 1.5], [1, True], ["1", 2], "11"):
        with pytest.raises(InvalidWeightError):
            split_cents(100, weights, owner_index=0)  # type: ignore[arg-type]


def test_invalid_owner_rejected() -> None:
    for owner in (-1, 3, 99, True, 1.0, "1"):
        with pytest.raises(InvalidOwnerError):
            split_cents(100, [1, 1, 1], owner_index=owner)  # type: ignore[arg-type]


def test_invalid_fallback_rejected() -> None:
    with pytest.raises(InvalidFallbackError):
        split_cents(100, [1, 1, 1], owner_index=2, fallback="spread")  # type: ignore[arg-type]


def test_one_cent_goes_to_owner() -> None:
    result = split_cents(1, [1, 1, 1], owner_index=2)
    assert amounts(result) == (0, 0, 1)


def test_two_cents_go_to_owner() -> None:
    result = split_cents(2, [1, 1, 1], owner_index=1)
    assert amounts(result) == (0, 2, 0)


def test_split_equal_helper() -> None:
    result = split_equal(8900, 3, owner_index=2)
    assert amounts(result) == (2966, 2966, 2968)
    assert result.fallback_used is False


def test_split_equal_rejects_bad_count() -> None:
    for count in (0, -1, True, 1.0):
        with pytest.raises((EmptyWeightsError, InvalidWeightError)):
            split_equal(100, count, owner_index=0)  # type: ignore[arg-type]


def test_deterministic_repeat() -> None:
    first = split_cents(28765, [18, 30, 30], owner_index=2)
    second = split_cents(28765, [18, 30, 30], owner_index=2)
    assert first == second
    assert amounts(first) == amounts(second)


def test_multi_bill_person_totals() -> None:
    bills = [
        split_cents(28765, [18, 30, 30], owner_index=2),
        split_cents(9640, [18, 30, 30], owner_index=2),
        split_cents(8900, [1, 1, 1], owner_index=2),
        split_cents(2000, [1, 1, 1], owner_index=2),
    ]
    person_totals = [sum(result.amounts[index] for result in bills) for index in range(3)]
    assert person_totals == [12494, 18402, 18409]
    assert sum(person_totals) == 49305
    assert sum(result.total_cents for result in bills) == 49305


def test_result_assert_conserved() -> None:
    result = split_cents(28765, [18, 30, 30], owner_index=2)
    result.assert_conserved()

    broken = result.__class__(
        total_cents=result.total_cents + 1,
        owner_index=result.owner_index,
        total_weight=result.total_weight,
        fallback_used=result.fallback_used,
        lines=result.lines,
    )
    with pytest.raises(ConservationError):
        broken.assert_conserved()
