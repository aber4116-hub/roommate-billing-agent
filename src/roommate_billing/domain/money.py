"""金额工具：严格解析人民币元字符串，内部只用整数分。

关键约束：
- 内部金额一律是整数“分”，不参与浮点运算；
- 最多两位小数；
- 默认单笔账单上限 1,000,000,000.00 元（100,000,000,000 分）；
- 普通账单默认不允许负数；引擎层可显式允许负数用于冲正/测试。
"""

from __future__ import annotations

import re

from .errors import AmountOutOfRangeError, InvalidAmountError, MoneyError

# 1,000,000,000.00 元 = 100,000,000,000 分。
# 上限用于防止超大数导致数据库/显示/导出异常，也远高于家用账单规模。
MAX_BILL_CENTS = 100_000_000_000

# 只接受：0 / 12 / 12.3 / 12.34 / -12.34。
# 不接受科学计数法、千分位逗号、前导零、".5"、"1."、空白内部字符。
_AMOUNT_RE = re.compile(r"^(?P<sign>-?)(?P<whole>0|[1-9][0-9]*)(?:\.(?P<fraction>[0-9]{1,2}))?$")


def _validate_max(max_abs_cents: int) -> None:
    if isinstance(max_abs_cents, bool) or not isinstance(max_abs_cents, int):
        raise MoneyError("max_abs_cents 必须是整数分")
    if max_abs_cents <= 0:
        raise MoneyError("max_abs_cents 必须大于 0")


def parse_yuan_to_cents(
    text: str,
    *,
    allow_negative: bool = False,
    max_abs_cents: int = MAX_BILL_CENTS,
) -> int:
    """把用户输入的人民币元字符串解析为整数分。

    Args:
        text: 例如 ``"287.65"``、``"0.01"``、``"89"``。
        allow_negative: 是否允许负金额。普通账单为 False；引擎/冲正为 True。
        max_abs_cents: 允许的绝对值上限，默认单笔账单上限。

    Raises:
        InvalidAmountError: 格式非法、空值、超过两位小数、指数形式等。
        AmountOutOfRangeError: 超过上限。
    """
    _validate_max(max_abs_cents)
    if not isinstance(text, str):
        raise InvalidAmountError("金额必须是字符串")

    raw = text.strip()
    if not raw:
        raise InvalidAmountError("金额不能为空")

    match = _AMOUNT_RE.fullmatch(raw)
    if match is None:
        raise InvalidAmountError(
            "金额格式非法：只允许最多两位小数的十进制数，不接受指数、千分位或空值"
        )

    sign = match.group("sign")
    if sign and not allow_negative:
        raise InvalidAmountError("金额不能为负数")

    whole = int(match.group("whole"))
    fraction_text = match.group("fraction") or ""
    # 补足两位，例如 "1.2" -> 20 分；"1.23" -> 23 分。
    fraction = int(fraction_text.ljust(2, "0")) if fraction_text else 0
    cents = whole * 100 + fraction

    if sign:
        cents = -cents
    if abs(cents) > max_abs_cents:
        raise AmountOutOfRangeError(f"金额超过允许上限：{max_abs_cents} 分")
    return cents


def validate_cents(
    value: int,
    *,
    allow_negative: bool = False,
    max_abs_cents: int = MAX_BILL_CENTS,
) -> int:
    """校验一个已经是整数分的金额，并返回原值。

    这个函数用于 API 边界：客户端应提交 ``*_cents`` 整数，而不是浮点元数。
    """
    _validate_max(max_abs_cents)
    if isinstance(value, bool) or not isinstance(value, int):
        raise InvalidAmountError("金额必须是整数分")
    if not allow_negative and value < 0:
        raise InvalidAmountError("金额不能为负数")
    if abs(value) > max_abs_cents:
        raise AmountOutOfRangeError(f"金额超过允许上限：{max_abs_cents} 分")
    return value


def format_cents(cents: int, *, symbol: str = "¥", grouping: bool = True) -> str:
    """把整数分格式化为展示字符串，例如 ``¥1,234.56``。"""
    value = validate_cents(cents, allow_negative=True)
    sign = "-" if value < 0 else ""
    absolute = abs(value)
    whole, fraction = divmod(absolute, 100)
    whole_text = f"{whole:,}" if grouping else str(whole)
    return f"{sign}{symbol}{whole_text}.{fraction:02d}"


def format_cents_plain(cents: int) -> str:
    """格式化为不带货币符号/千分位的十进制字符串，用于 CSV/API 文本。"""
    value = validate_cents(cents, allow_negative=True)
    sign = "-" if value < 0 else ""
    whole, fraction = divmod(abs(value), 100)
    return f"{sign}{whole}.{fraction:02d}"
