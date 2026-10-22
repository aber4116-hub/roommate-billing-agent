"""领域层公开接口。"""

from .allocation import AllocationLine, AllocationResult, split_cents, split_equal
from .errors import (
    AllocationError,
    AmountOutOfRangeError,
    ConservationError,
    DomainError,
    EmptyWeightsError,
    InvalidAmountError,
    InvalidFallbackError,
    InvalidOwnerError,
    InvalidTotalError,
    InvalidWeightError,
    MoneyError,
)
from .money import (
    MAX_BILL_CENTS,
    format_cents,
    format_cents_plain,
    parse_yuan_to_cents,
    validate_cents,
)

__all__ = [
    "MAX_BILL_CENTS",
    "AllocationError",
    "AllocationLine",
    "AllocationResult",
    "AmountOutOfRangeError",
    "ConservationError",
    "DomainError",
    "EmptyWeightsError",
    "InvalidAmountError",
    "InvalidFallbackError",
    "InvalidOwnerError",
    "InvalidTotalError",
    "InvalidWeightError",
    "MoneyError",
    "format_cents",
    "format_cents_plain",
    "parse_yuan_to_cents",
    "split_cents",
    "split_equal",
    "validate_cents",
]
