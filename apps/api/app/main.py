"""FastAPI application factory and middleware."""

from __future__ import annotations

import uuid
from collections.abc import Awaitable, Callable
from typing import Any

from fastapi import FastAPI, Request, Response
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from .routers.activities import router as activities_router
from .routers.auth import router as auth_router
from .routers.curriculum import router as curriculum_router
from .routers.diagnostics import router as diagnostics_router
from .routers.health import router as health_router
from .routers.plans import router as plans_router
from .routers.profile import router as profile_router
from .routers.reviews import router as reviews_router
from .settings import settings

API_V1_PREFIX = "/api/v1"
REQUEST_ID_HEADER = "X-Request-ID"


def create_app() -> FastAPI:
    app = FastAPI(
        title="FluentForge API",
        version="0.1.0",
        description="Adaptive English-learning API",
    )

    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.allowed_origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
        expose_headers=[REQUEST_ID_HEADER],
    )

    @app.middleware("http")
    async def add_request_id(
        request: Request, call_next: Callable[[Request], Awaitable[Response]]
    ) -> Response:
        request_id = request.headers.get(REQUEST_ID_HEADER) or uuid.uuid4().hex
        request.state.request_id = request_id
        response = await call_next(request)
        response.headers[REQUEST_ID_HEADER] = request_id
        return response

    @app.exception_handler(StarletteHTTPException)
    async def http_exception_handler(request: Request, exc: StarletteHTTPException) -> JSONResponse:
        """Normalise every error to ``{code, message, details, request_id}``."""
        detail = exc.detail
        body: dict[str, Any]
        if isinstance(detail, dict) and "code" in detail:
            body = dict(detail)
        else:
            body = {
                "code": _fallback_code(exc.status_code),
                "message": str(detail),
                "details": {},
            }
        body["request_id"] = getattr(request.state, "request_id", None)
        return JSONResponse(status_code=exc.status_code, content=body, headers=exc.headers)

    @app.exception_handler(RequestValidationError)
    async def validation_exception_handler(
        request: Request, exc: RequestValidationError
    ) -> JSONResponse:
        return JSONResponse(
            status_code=422,
            content={
                "code": "validation_error",
                "message": "The request body did not match the expected shape.",
                # Field locations only; raw input is omitted so submitted
                # learner content and credentials never enter error logs.
                "details": {"fields": [list(error["loc"]) for error in exc.errors()]},
                "request_id": getattr(request.state, "request_id", None),
            },
        )

    app.include_router(health_router)
    app.include_router(auth_router, prefix=API_V1_PREFIX)
    app.include_router(profile_router, prefix=API_V1_PREFIX)
    app.include_router(curriculum_router, prefix=API_V1_PREFIX)
    app.include_router(diagnostics_router, prefix=API_V1_PREFIX)
    app.include_router(plans_router, prefix=API_V1_PREFIX)
    app.include_router(reviews_router, prefix=API_V1_PREFIX)
    app.include_router(activities_router, prefix=API_V1_PREFIX)

    return app


def _fallback_code(status_code: int) -> str:
    return {
        401: "not_authenticated",
        403: "forbidden",
        404: "not_found",
        405: "method_not_allowed",
        409: "conflict",
        429: "rate_limited",
    }.get(status_code, "http_error")


app = create_app()
