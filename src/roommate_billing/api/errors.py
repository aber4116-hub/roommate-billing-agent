"""统一 API 错误响应。"""

from __future__ import annotations

import logging
from uuid import UUID, uuid4

from fastapi import FastAPI, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from sqlalchemy.exc import IntegrityError

from ..domain.errors import ConservationError, DomainError
from ..services.errors import ServiceError

logger = logging.getLogger(__name__)


def _request_id(request: Request) -> str:
    value = getattr(request.state, "request_id", None)
    if isinstance(value, UUID):
        return str(value)
    header = request.headers.get("X-Request-ID")
    if header:
        try:
            return str(UUID(header))
        except ValueError:
            pass
    return str(uuid4())


def _response(
    request: Request,
    *,
    status_code: int,
    code: str,
    message: str,
    details: list[dict] | None = None,
) -> JSONResponse:
    return JSONResponse(
        status_code=status_code,
        content={
            "error": {
                "code": code,
                "message": message,
                "details": details or [],
                "request_id": _request_id(request),
            }
        },
        headers={"X-Request-ID": _request_id(request)},
    )


def install_error_handlers(app: FastAPI) -> None:
    @app.exception_handler(ServiceError)
    async def service_error_handler(request: Request, exc: ServiceError) -> JSONResponse:
        return _response(
            request,
            status_code=exc.status_code,
            code=exc.code,
            message=exc.message,
        )

    @app.exception_handler(ConservationError)
    async def conservation_error_handler(request: Request, exc: ConservationError) -> JSONResponse:
        logger.exception("conservation invariant failed", exc_info=exc)
        return _response(
            request,
            status_code=500,
            code="CONSERVATION_ERROR",
            message="账务一致性校验失败，操作已回滚",
        )

    @app.exception_handler(DomainError)
    async def domain_error_handler(request: Request, exc: DomainError) -> JSONResponse:
        return _response(
            request,
            status_code=422,
            code=exc.code,
            message=str(exc),
        )

    @app.exception_handler(RequestValidationError)
    async def validation_error_handler(
        request: Request, exc: RequestValidationError
    ) -> JSONResponse:
        details = []
        for error in exc.errors():
            details.append(
                {
                    "path": ".".join(str(part) for part in error.get("loc", [])),
                    "message": error.get("msg", "invalid"),
                    "type": error.get("type", "value_error"),
                }
            )
        return _response(
            request,
            status_code=422,
            code="VALIDATION_ERROR",
            message="请求参数校验失败",
            details=details,
        )

    @app.exception_handler(IntegrityError)
    async def integrity_error_handler(request: Request, exc: IntegrityError) -> JSONResponse:
        logger.warning("database integrity error: %s", exc.__class__.__name__)
        return _response(
            request,
            status_code=409,
            code="CONFLICT",
            message="数据冲突，请刷新后重试",
        )

    @app.exception_handler(HTTPException)
    async def http_error_handler(request: Request, exc: HTTPException) -> JSONResponse:
        message = exc.detail if isinstance(exc.detail, str) else "请求失败"
        return _response(
            request,
            status_code=exc.status_code,
            code="HTTP_ERROR",
            message=message,
        )

    @app.exception_handler(Exception)
    async def unhandled_error_handler(request: Request, exc: Exception) -> JSONResponse:
        logger.exception("unhandled error", exc_info=exc)
        return _response(
            request,
            status_code=500,
            code="INTERNAL_ERROR",
            message="服务器内部错误",
        )
