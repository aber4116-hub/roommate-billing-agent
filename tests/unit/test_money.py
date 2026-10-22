"""金额解析/格式化测试。"""

from __future__ import annotations

import pytest

from roommate_billing.domain.errors import AmountOutOfRangeError, InvalidAmountError, MoneyError
from roommate_billing.domain.money import (
    MAX_BILL_CENTS,
    format_cents,
    format_cents_plain,
    parse_yuan_to_cents,
    validate_cents,
)


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("0", 0),
        ("0.00", 0),
        ("0.01", 1),
        ("0.1", 10),
        ("1", 100),
        ("89.00", 8900),
        ("96.40", 9640),
        ("287.65", 28765),
        ("1000000000.00", MAX_BILL_CENTS),
        (" 287.65 ", 28765),
    ],
)
def test_parse_valid_yuan(text: str, expected: int) -> None:
    assert parse_yuan_to_cents(text) == expected


@pytest.mark.parametrize(
    "text",
    [
        "",
        " ",
        ".5",
        "1.",
        "1.005",
        "1.234",
        "1e3",
        "1,000.00",
        "+1.00",
        "01.00",
        "1 000",
        "abc",
        "NaN",
        "Infinity",
        "--1.00",
        "١٢.٣٤",
    ],
)
def test_parse_invalid_yuan(text: str) -> None:
    with pytest.raises(InvalidAmountError):
        parse_yuan_to_cents(text)


def test_parse_rejects_non_string() -> None:
    with pytest.raises(InvalidAmountError):
        parse_yuan_to_cents(28765)  # type: ignore[arg-type]


def test_parse_negative_requires_explicit_permission() -> None:
    with pytest.raises(InvalidAmountError):
        parse_yuan_to_cents("-10.00")
    assert parse_yuan_to_cents("-10.00", allow_negative=True) == -1000
    assert parse_yuan_to_cents("-0.01", allow_negative=True) == -1
    assert parse_yuan_to_cents("-0.00", allow_negative=True) == 0


def test_parse_rejects_over_limit() -> None:
    with pytest.raises(AmountOutOfRangeError):
        parse_yuan_to_cents("1000000000.01")
    with pytest.raises(AmountOutOfRangeError):
        parse_yuan_to_cents("-1000000000.01", allow_negative=True)


def test_parse_rejects_invalid_max_limit() -> None:
    with pytest.raises(MoneyError):
        parse_yuan_to_cents("1.00", max_abs_cents=0)
    with pytest.raises(MoneyError):
        parse_yuan_to_cents("1.00", max_abs_cents=True)  # type: ignore[arg-type]


@pytest.mark.parametrize(
    ("cents", "expected"),
    [
        (0, "¥0.00"),
        (1, "¥0.01"),
        (100, "¥1.00"),
        (123456, "¥1,234.56"),
        (-1, "-¥0.01"),
        (-123456, "-¥1,234.56"),
        (MAX_BILL_CENTS, "¥1,000,000,000.00"),
    ],
)
def test_format_cents(cents: int, expected: str) -> None:
    assert format_cents(cents) == expected


def test_format_cents_without_grouping() -> None:
    assert format_cents(123456, grouping=False) == "¥1234.56"
    assert format_cents(-123456, grouping=False) == "-¥1234.56"


@pytest.mark.parametrize(
    ("cents", "expected"),
    [
        (0, "0.00"),
        (1, "0.01"),
        (100, "1.00"),
        (123456, "1234.56"),
        (-1, "-0.01"),
        (-123456, "-1234.56"),
    ],
)
def test_format_cents_plain(cents: int, expected: str) -> None:
    assert format_cents_plain(cents) == expected


def test_format_rejects_non_integer() -> None:
    for value in (1.0, "1.00", True, None):
        with pytest.raises(InvalidAmountError):
            format_cents(value)  # type: ignore[arg-type]


def test_validate_cents() -> None:
    assert validate_cents(0) == 0
    assert validate_cents(MAX_BILL_CENTS) == MAX_BILL_CENTS
    assert validate_cents(-1, allow_negative=True) == -1
    with pytest.raises(InvalidAmountError):
        validate_cents(-1)
    with pytest.raises(InvalidAmountError):
        validate_cents(1.0)  # type: ignore[arg-type]
    with pytest.raises(InvalidAmountError):
        validate_cents(True)  # type: ignore[arg-type]
    with pytest.raises(AmountOutOfRangeError):
        validate_cents(MAX_BILL_CENTS + 1)
