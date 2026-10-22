"""整数分摊引擎。

业务规则（v1）：
- 电费、水费：按入住天数权重分摊；
- 宽带、垃圾：按户等权分摊；
- 所有零头（不足一分的余数）统一记到规则指定的零头归属人；
- 权重全为 0 时使用显式、可测试的备用规则：按人数等分；
- 每笔账单分摊金额之和必须等于账单原始金额。

实现只使用 Python 整数除法/取余，不使用浮点金额运算。
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from typing import Literal

from .errors import (
    ConservationError,
    EmptyWeightsError,
    InvalidFallbackError,
    InvalidOwnerError,
    InvalidTotalError,
    InvalidWeightError,
)
from .money import MAX_BILL_CENTS

FallbackMethod = Literal["equal"]


@dataclass(frozen=True, slots=True)
class AllocationLine:
    """一个人的分摊结果（金额单位为分，带符号）。"""

    index: int
    weight: int
    base_cents: int
    remainder_cents: int
    amount_cents: int
    is_remainder_owner: bool


@dataclass(frozen=True, slots=True)
class AllocationResult:
    """一笔账单的完整分摊结果。"""

    total_cents: int
    owner_index: int
    total_weight: int
    fallback_used: bool
    lines: tuple[AllocationLine, ...]

    @property
    def amounts(self) -> tuple[int, ...]:
        """按人员顺序返回金额，便于调用方写入数据库/展示。"""
        return tuple(line.amount_cents for line in self.lines)

    @property
    def remainder_total_cents(self) -> int:
        """所有零头之和（带符号），等于总额减所有 base。"""
        return sum(line.remainder_cents for line in self.lines)

    def assert_conserved(self) -> None:
        """校验逐行关系与总额守恒；失败表示实现有 bug，必须回滚事务。"""
        for line in self.lines:
            if line.amount_cents != line.base_cents + line.remainder_cents:
                raise ConservationError(
                    f"第 {line.index} 行金额不等于 base + remainder："
                    f"{line.amount_cents} != {line.base_cents} + {line.remainder_cents}"
                )
        if sum(self.amounts) != self.total_cents:
            raise ConservationError(
                f"分摊合计 {sum(self.amounts)} 不等于账单总额 {self.total_cents}"
            )
        if sum(line.base_cents for line in self.lines) + self.remainder_total_cents != (
            self.total_cents
        ):
            raise ConservationError("base 与 remainder 合计不等于账单总额")


def _validate_weights(weights: Sequence[int]) -> tuple[int, ...]:
    if isinstance(weights, (str, bytes)) or not isinstance(weights, Sequence):
        raise InvalidWeightError("weights 必须是整数序列")
    raw = tuple(weights)
    if not raw:
        raise EmptyWeightsError("至少需要一个人参与分摊")
    for value in raw:
        # bool 是 int 的子类，必须显式拒绝，避免 True/False 被当成 1/0。
        if isinstance(value, bool) or not isinstance(value, int):
            raise InvalidWeightError("权重必须是整数")
        if value < 0:
            raise InvalidWeightError("权重不能为负数")
    return raw


def split_cents(
    total_cents: int,
    weights: Sequence[int],
    *,
    owner_index: int,
    fallback: FallbackMethod = "equal",
    max_abs_cents: int = MAX_BILL_CENTS,
) -> AllocationResult:
    """按权重把一笔账单分摊到若干人。

    算法：
    1. 把总额取绝对值并记录符号；
    2. 每人先分 ``floor(金额 * 权重 / 总权重)`` 分；
    3. 剩余不足一分的部分，全部加到 ``owner_index``；
    4. 恢复符号。

    这样每笔账单的 ``sum(amounts)`` 始终等于 ``total_cents``。

    Args:
        total_cents: 账单总额，整数分；可为负（冲正/引擎测试）。
        weights: 每人权重；非负整数。全部为 0 时走 fallback。
        owner_index: 零头归属人的下标；非法下标直接报错，不静默回退。
        fallback: 备用规则；v1 只允许 ``"equal"``（按人数等分）。
        max_abs_cents: 金额上限，默认单笔账单上限。

    Raises:
        InvalidTotalError: 总额类型/范围非法。
        EmptyWeightsError: 没有任何分摊对象。
        InvalidWeightError: 权重非法。
        InvalidOwnerError: 零头归属人下标非法。
        InvalidFallbackError: 未知备用规则。
        ConservationError: 内部守恒校验失败。
    """
    # 引擎支持有符号金额（API 的普通账单会在边界拒绝负数）。
    if isinstance(total_cents, bool) or not isinstance(total_cents, int):
        raise InvalidTotalError("账单总额必须是整数分")
    if isinstance(max_abs_cents, bool) or not isinstance(max_abs_cents, int):
        raise InvalidTotalError("max_abs_cents 必须是整数分")
    if max_abs_cents <= 0:
        raise InvalidTotalError("max_abs_cents 必须大于 0")
    if abs(total_cents) > max_abs_cents:
        raise InvalidTotalError(f"账单总额超过允许上限：{max_abs_cents} 分")

    raw_weights = _validate_weights(weights)
    count = len(raw_weights)

    if isinstance(owner_index, bool) or not isinstance(owner_index, int):
        raise InvalidOwnerError("零头归属人下标必须是整数")
    if not 0 <= owner_index < count:
        raise InvalidOwnerError("零头归属人下标越界")
    if fallback != "equal":
        raise InvalidFallbackError("v1 只支持 equal 备用规则")

    # 主权重全为 0：使用显式备用规则，每人权重 1。
    # 这是业务规则的一部分，而不是“凑一个结果”；fallback_used 会记录在结果中。
    fallback_used = False
    effective_weights = raw_weights
    total_weight = sum(effective_weights)
    if total_weight == 0:
        effective_weights = (1,) * count
        total_weight = count
        fallback_used = True

    sign = -1 if total_cents < 0 else 1
    amount = abs(total_cents)

    # 先算整数 base，不产生浮点数。
    bases = [(amount * weight) // total_weight for weight in effective_weights]
    used = sum(bases)
    leftover = amount - used

    # 数学上 remainder 一定小于人数；若不满足，说明实现被破坏。
    if not 0 <= leftover < count:
        raise ConservationError(f"余数异常：{leftover}，人数：{count}")

    lines: list[AllocationLine] = []
    for index, (weight, base) in enumerate(zip(effective_weights, bases, strict=True)):
        raw_remainder = leftover if index == owner_index else 0
        lines.append(
            AllocationLine(
                index=index,
                weight=weight,
                base_cents=base * sign,
                remainder_cents=raw_remainder * sign,
                amount_cents=(base + raw_remainder) * sign,
                # 没有余数时，不把 owner 标成“实际分到零头”；
                # 归属关系由 owner_index 单独记录。
                is_remainder_owner=index == owner_index and leftover > 0,
            )
        )

    result = AllocationResult(
        total_cents=total_cents,
        owner_index=owner_index,
        total_weight=total_weight,
        fallback_used=fallback_used,
        lines=tuple(lines),
    )
    result.assert_conserved()
    return result


def split_equal(
    total_cents: int,
    people_count: int,
    *,
    owner_index: int,
    max_abs_cents: int = MAX_BILL_CENTS,
) -> AllocationResult:
    """按户等权分摊的便捷函数；本质是权重全为 1 的 split_cents。"""
    if isinstance(people_count, bool) or not isinstance(people_count, int):
        raise InvalidWeightError("人数必须是整数")
    if people_count <= 0:
        raise EmptyWeightsError("至少需要一个人参与分摊")
    return split_cents(
        total_cents,
        (1,) * people_count,
        owner_index=owner_index,
        max_abs_cents=max_abs_cents,
    )
