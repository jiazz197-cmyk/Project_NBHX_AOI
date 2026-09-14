"""aoi 统一错误码与异常（契约 §2.3）。

HTTP → code 映射：
400→40010 / 401→40100 / 403→40300 / 404→40401 / 409→40900 / 422→42200 / 429→42900 / 500→50000 / 503→50300
"""

from __future__ import annotations

from typing import Any

__all__ = [
    'CODE_BAD_REQUEST',
    'CODE_UNAUTHORIZED',
    'CODE_FORBIDDEN',
    'CODE_NOT_FOUND',
    'CODE_CONFLICT',
    'CODE_UNPROCESSABLE',
    'CODE_TOO_MANY_REQUESTS',
    'CODE_INTERNAL',
    'CODE_UNAVAILABLE',
    'HTTP_STATUS_BY_CODE',
    'CODE_BY_HTTP_STATUS',
    'DEFAULT_MESSAGE_BY_CODE',
    'AoiError',
    'error_response',
]

CODE_BAD_REQUEST = 40010
CODE_UNAUTHORIZED = 40100
CODE_FORBIDDEN = 40300
CODE_NOT_FOUND = 40401
CODE_CONFLICT = 40900
CODE_UNPROCESSABLE = 42200
CODE_TOO_MANY_REQUESTS = 42900
CODE_INTERNAL = 50000
CODE_UNAVAILABLE = 50300

HTTP_STATUS_BY_CODE = {
    CODE_BAD_REQUEST: 400,
    CODE_UNAUTHORIZED: 401,
    CODE_FORBIDDEN: 403,
    CODE_NOT_FOUND: 404,
    CODE_CONFLICT: 409,
    CODE_UNPROCESSABLE: 422,
    CODE_TOO_MANY_REQUESTS: 429,
    CODE_INTERNAL: 500,
    CODE_UNAVAILABLE: 503,
}

#: 反向映射：DRF/DRF 之外的异常按 HTTP 状态归一到契约错误码（P1 修复：429/503 不再落到 40010）。
#: 405/415 等契约未单列的状态归为 ``40010``（请求本身有问题）。
CODE_BY_HTTP_STATUS = {status: code for code, status in HTTP_STATUS_BY_CODE.items()}
CODE_BY_HTTP_STATUS.update({405: CODE_BAD_REQUEST, 415: CODE_BAD_REQUEST})

DEFAULT_MESSAGE_BY_CODE = {
    CODE_BAD_REQUEST: 'bad request',
    CODE_UNAUTHORIZED: 'unauthorized',
    CODE_FORBIDDEN: 'forbidden',
    CODE_NOT_FOUND: 'not found',
    CODE_CONFLICT: 'conflict',
    CODE_UNPROCESSABLE: 'validation failed',
    CODE_TOO_MANY_REQUESTS: 'too many requests',
    CODE_INTERNAL: 'internal error',
    CODE_UNAVAILABLE: 'dependency unavailable',
}


class AoiError(Exception):
    """aoi 业务异常：由 ``AoiAPIView.handle_exception`` 统一转为信封响应。"""

    def __init__(
        self,
        code: int = CODE_BAD_REQUEST,
        message: str | None = None,
        *,
        http_status: int | None = None,
        fields: dict[str, Any] | None = None,
        detail: Any = None,
    ) -> None:
        self.code = code
        self.message = message or DEFAULT_MESSAGE_BY_CODE.get(code, 'error')
        self.http_status = http_status or HTTP_STATUS_BY_CODE.get(code, 400)
        self.fields = fields
        self.detail = detail
        super().__init__(self.message)

    def as_response_data(self, request_id: str) -> dict[str, Any]:
        from aoi.common.envelope import fail

        return fail(
            self.code,
            self.message,
            request_id=request_id,
            fields=self.fields,
            detail=self.detail,
        )


def error_response(code: int, message: str | None = None, *, fields=None, detail=None, request_id=None):
    """便捷构造 ``AoiError``（给 service 层使用）。"""
    return AoiError(code, message, fields=fields, detail=detail)
