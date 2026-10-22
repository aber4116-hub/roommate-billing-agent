"""服务层错误：由 API 映射为稳定的 HTTP 错误。"""

from __future__ import annotations


class ServiceError(Exception):
    status_code = 400
    code = "SERVICE_ERROR"

    def __init__(self, message: str, *, code: str | None = None) -> None:
        super().__init__(message)
        self.message = message
        if code:
            self.code = code


class NotFoundError(ServiceError):
    status_code = 404
    code = "NOT_FOUND"


class UnauthorizedError(ServiceError):
    status_code = 401
    code = "AUTH_REQUIRED"


class InvalidCredentialsError(ServiceError):
    status_code = 401
    code = "INVALID_CREDENTIALS"


class AccountLockedError(ServiceError):
    status_code = 423
    code = "ACCOUNT_LOCKED"


class AgentUnavailable(ServiceError):
    status_code = 503
    code = "AGENT_UNAVAILABLE"


class AgentProviderError(ServiceError):
    status_code = 502
    code = "AGENT_PROVIDER_ERROR"


class ConflictError(ServiceError):
    status_code = 409
    code = "CONFLICT"


class ForbiddenError(ServiceError):
    status_code = 403
    code = "FORBIDDEN"


class ValidationError(ServiceError):
    status_code = 422
    code = "VALIDATION_ERROR"
