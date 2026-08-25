from __future__ import annotations

import logging
from typing import Any
from uuid import uuid4

from fastapi import Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

logger = logging.getLogger("jobflow.errors")


def _request_id(request: Request) -> str:
    return getattr(request.state, "request_id", None) or uuid4().hex


def _body(
    request: Request,
    code: str,
    message: str,
    details: Any = None,
) -> dict[str, Any]:
    error: dict[str, Any] = {
        "code": code,
        "message": message,
        "request_id": _request_id(request),
    }
    if details is not None:
        error["details"] = details
    return {"error": error}


async def http_exception_handler(
    request: Request,
    exception: StarletteHTTPException,
) -> JSONResponse:
    detail = exception.detail
    if isinstance(detail, dict) and isinstance(detail.get("code"), str):
        code = detail["code"]
        message = str(detail.get("message") or "请求失败")
        details = {key: value for key, value in detail.items() if key not in {"code", "message"}}
    else:
        code = "http_error"
        message = detail if isinstance(detail, str) else "请求失败"
        details = None if isinstance(detail, str) else detail
    headers = dict(exception.headers or {})
    headers["X-Request-ID"] = _request_id(request)
    return JSONResponse(
        status_code=exception.status_code,
        content=_body(request, code, message, details or None),
        headers=headers,
    )


async def validation_exception_handler(
    request: Request,
    exception: RequestValidationError,
) -> JSONResponse:
    details = [
        {
            "location": list(error["loc"]),
            "message": error["msg"],
            "type": error["type"],
        }
        for error in exception.errors()
    ]
    return JSONResponse(
        status_code=422,
        content=_body(request, "validation_error", "请求参数校验失败", details),
        headers={"X-Request-ID": _request_id(request)},
    )


async def unhandled_exception_handler(
    request: Request,
    exception: Exception,
) -> JSONResponse:
    logger.error(
        "unhandled_exception",
        exc_info=(type(exception), exception, exception.__traceback__),
        extra={"request_id": _request_id(request)},
    )
    return JSONResponse(
        status_code=500,
        content=_body(request, "internal_error", "服务器内部错误"),
        headers={"X-Request-ID": _request_id(request)},
    )


def register_exception_handlers(application: Any) -> None:
    application.add_exception_handler(StarletteHTTPException, http_exception_handler)
    application.add_exception_handler(RequestValidationError, validation_exception_handler)
    application.add_exception_handler(Exception, unhandled_exception_handler)
