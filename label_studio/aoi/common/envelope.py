"""统一响应信封（契约 §2.3 / 跨平台契约 §1.3）。

成功：``{"code":0,"message":"ok","request_id":"req-...","data":{...}}``
失败：HTTP 状态码 + 同信封；字段级错误放 ``data.detail.fields``。
"""

from __future__ import annotations

from typing import Any

__all__ = ['OK_CODE', 'OK_MESSAGE', 'make_envelope', 'ok', 'fail']


OK_CODE = 0
OK_MESSAGE = 'ok'


def make_envelope(
    code: int,
    message: str,
    request_id: str | None = None,
    data: Any = None,
) -> dict[str, Any]:
    return {
        'code': code,
        'message': message,
        'request_id': request_id,
        'data': {} if data is None else data,
    }


def ok(data: Any = None, message: str = OK_MESSAGE, request_id: str | None = None) -> dict[str, Any]:
    """成功信封。"""
    return make_envelope(OK_CODE, message, request_id=request_id, data=data)


def fail(
    code: int,
    message: str,
    request_id: str | None = None,
    *,
    fields: dict[str, Any] | None = None,
    detail: Any = None,
) -> dict[str, Any]:
    """失败信封；``fields`` 优先，其次 ``detail``，都没有则 ``data={}``。"""
    if fields is not None:
        data: Any = {'detail': {'fields': fields}}
    elif detail is not None:
        data = {'detail': detail}
    else:
        data = {}
    return make_envelope(code, message, request_id=request_id, data=data)
