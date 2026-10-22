"""领域错误类型。

这些错误不依赖 Web 框架；后续 API 层会把它们映射为稳定的 HTTP 错误码。
"""


class DomainError(ValueError):
    """所有业务/领域错误的基类。"""

    code = "DOMAIN_ERROR"


class MoneyError(DomainError):
    """金额解析或格式化错误。"""

    code = "MONEY_ERROR"


class InvalidAmountError(MoneyError):
    """金额格式非法。"""

    code = "INVALID_AMOUNT"


class AmountOutOfRangeError(MoneyError):
    """金额超出允许范围。"""

    code = "AMOUNT_OUT_OF_RANGE"


class AllocationError(DomainError):
    """分摊计算错误。"""

    code = "ALLOCATION_ERROR"


class InvalidTotalError(AllocationError):
    """账单总额不是合法整数分。"""

    code = "INVALID_TOTAL"


class EmptyWeightsError(AllocationError):
    """没有分摊对象。"""

    code = "EMPTY_WEIGHTS"


class InvalidWeightError(AllocationError):
    """权重非法（负数、非整数、布尔值等）。"""

    code = "INVALID_WEIGHT"


class InvalidOwnerError(AllocationError):
    """零头归属人下标非法。"""

    code = "INVALID_OWNER"


class InvalidFallbackError(AllocationError):
    """备用分摊规则未知。"""

    code = "INVALID_FALLBACK"


class ConservationError(AllocationError):
    """内部守恒校验失败；出现即表示算法或实现有 bug。"""

    code = "CONSERVATION_ERROR"
