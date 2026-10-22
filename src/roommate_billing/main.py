"""FastAPI 应用入口。"""

from __future__ import annotations

import os
from pathlib import Path
from uuid import UUID, uuid4

from fastapi import FastAPI, Request
from fastapi.responses import FileResponse, Response
from fastapi.staticfiles import StaticFiles

from .api.errors import install_error_handlers
from .api.v1 import (
    actions,
    agent,
    audit,
    auth,
    bills,
    health,
    households,
    payments,
    periods,
    rules,
    settlements,
)

API_VERSION = "0.1.0-rc.1"
WEB_DIR = Path(os.environ.get("WEB_DIR", str(Path(__file__).resolve().parents[2] / "web")))
CSP = (
    "default-src 'self'; "
    "script-src 'self'; "
    "style-src 'self'; "
    "img-src 'self' data:; "
    "font-src 'self'; "
    "connect-src 'self'; "
    "object-src 'none'; "
    "base-uri 'none'; "
    "form-action 'self'; "
    "frame-ancestors 'none'"
)
DOC_PATHS = {"/docs", "/redoc", "/openapi.json", "/docs/oauth2-redirect"}


def create_app() -> FastAPI:
    app = FastAPI(
        title="roommate-billing-agent",
        version=API_VERSION,
        description="合租账单分摊与结算 API",
    )
    install_error_handlers(app)

    @app.middleware("http")
    async def request_id_middleware(request: Request, call_next):
        raw = request.headers.get("X-Request-ID")
        request_id: UUID
        if raw:
            try:
                request_id = UUID(raw)
            except ValueError:
                request_id = uuid4()
        else:
            request_id = uuid4()
        request.state.request_id = request_id
        response = await call_next(request)
        response.headers["X-Request-ID"] = str(request_id)
        if request.url.path not in DOC_PATHS:
            response.headers.setdefault("Content-Security-Policy", CSP)
            response.headers.setdefault("X-Content-Type-Options", "nosniff")
            response.headers.setdefault("X-Frame-Options", "DENY")
            response.headers.setdefault("Referrer-Policy", "no-referrer")
            response.headers.setdefault(
                "Permissions-Policy", "camera=(), microphone=(), geolocation=()"
            )
            response.headers.setdefault("Cross-Origin-Opener-Policy", "same-origin")
        if request.url.path == "/":
            response.headers["Cache-Control"] = "no-store"
        return response

    @app.get("/api/v1/meta")
    def meta() -> dict[str, str]:
        return {"version": API_VERSION, "api_version": "v1"}

    app.include_router(health.router)
    app.include_router(auth.router)
    app.include_router(households.router)
    app.include_router(audit.router)
    app.include_router(agent.router)
    app.include_router(actions.router)
    app.include_router(periods.router)
    app.include_router(bills.router)
    app.include_router(payments.router)
    app.include_router(rules.router)
    app.include_router(settlements.router)

    if (WEB_DIR / "assets").is_dir():
        app.mount("/assets", StaticFiles(directory=WEB_DIR / "assets"), name="assets")

    @app.get("/", include_in_schema=False)
    def index() -> FileResponse:
        return FileResponse(WEB_DIR / "index.html", media_type="text/html; charset=utf-8")

    @app.get("/favicon.ico", include_in_schema=False)
    def favicon() -> Response:
        return Response(status_code=204)

    return app


app = create_app()
