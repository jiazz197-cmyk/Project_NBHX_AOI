"""统一响应信封 + 错误码（逐字对齐平台B契约 §1.2）。

成功信封：{"code":0,"message":"ok","request_id":"req-...","data":{...}}

错误码（§1.2）：
  HTTP 400 -> 40010 坏图/镜像层解包失败/sha256 不符/参数不可读
  HTTP 404 -> 40401 资源不存在 / 40402 工位未注册未启用
  HTTP 409 -> 40900 状态冲突（同 model_ref 不同 digest、模板版本冲突）
  HTTP 422 -> 42200 业务校验失败（data.detail.fields）
  HTTP 429 -> 42900 队列背压 / registry 限流（可重试）
  HTTP 500 -> 50000 内部错误
  HTTP 503 -> 50300 未就绪（模型加载失败/磁盘不足/无可用 GPU）
  HTTP 401 -> 40100 仅 registry 鉴权失败透传
"""

from __future__ import annotations

import uuid
from typing import Any

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

CODE_OK = 0
CODE_BAD_PAYLOAD = 40010            # 坏图/镜像层解包失败/sha256 不符/参数不可读
CODE_NOT_FOUND = 40401              # 资源不存在
CODE_STATION_NOT_REGISTERED = 40402  # 工位未注册未启用
CODE_CONFLICT = 40900               # 状态冲突
CODE_VALIDATION_FAILED = 42200      # 业务校验失败
CODE_BACKPRESSURE = 42900           # 队列背压 / registry 限流
CODE_INTERNAL_ERROR = 50000         # 内部错误
CODE_NOT_READY = 50300              # 未就绪
CODE_REGISTRY_UNAUTHORIZED = 40100  # registry 鉴权失败透传


def new_request_id() -> str:
    return "req-" + uuid.uuid4().hex[:12]


class BizError(Exception):
    """业务错误：HTTP 状态码 + 业务 code + message（+ 可选 detail）。"""

    def __init__(
        self,
        status_code: int,
        code: int,
        message: str,
        detail: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.code = code
        self.message = message
        self.detail = detail


def ok(data: Any, request_id: str) -> dict[str, Any]:
    """成功信封。"""
    return {"code": CODE_OK, "message": "ok", "request_id": request_id, "data": data}


def error_body(
    code: int,
    message: str,
    request_id: str,
    detail: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """错误信封：骨架与成功一致；detail 仅 42200 明确要求（data.detail.fields）。"""
    data = {"detail": detail} if detail is not None else None
    return {"code": code, "message": message, "request_id": request_id, "data": data}


def _request_id(request: Request) -> str:
    rid = getattr(request.state, "request_id", None)
    return rid or request.headers.get("X-Request-ID") or new_request_id()


def register_exception_handlers(app: FastAPI) -> None:
    """注册全局异常处理器，统一返回信封。"""

    @app.exception_handler(BizError)
    async def _biz_error(request: Request, exc: BizError) -> JSONResponse:
        return JSONResponse(
            status_code=exc.status_code,
            content=error_body(exc.code, exc.message, _request_id(request), exc.detail),
        )

    @app.exception_handler(RequestValidationError)
    async def _validation_error(request: Request, exc: RequestValidationError) -> JSONResponse:
        # 参数不可读 -> 40010
        return JSONResponse(
            status_code=400,
            content=error_body(CODE_BAD_PAYLOAD, "参数不可读", _request_id(request), {"fields": exc.errors()}),
        )

    @app.exception_handler(Exception)
    async def _unhandled_error(request: Request, exc: Exception) -> JSONResponse:
        return JSONResponse(
            status_code=500,
            content=error_body(CODE_INTERNAL_ERROR, "内部错误", _request_id(request)),
        )

