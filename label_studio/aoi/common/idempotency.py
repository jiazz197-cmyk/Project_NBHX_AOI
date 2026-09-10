"""幂等键约定（契约 §2.5）。

写操作建议带 ``Idempotency-Key``；D1–D2 stub 接受缺失，仅记录/透传。
"""

from __future__ import annotations

from typing import Any

from aoi.common.errors import CODE_UNPROCESSABLE, AoiError

__all__ = ['IDEMPOTENCY_HEADER', 'get_idempotency_key', 'require_idempotency_key']

IDEMPOTENCY_HEADER = 'Idempotency-Key'


def get_idempotency_key(request: Any) -> str | None:
    """读取 ``Idempotency-Key`` 头；不存在返回 ``None``。"""
    value = request.headers.get(IDEMPOTENCY_HEADER)
    if value is None:
        return None
    value = value.strip()
    return value or None


def require_idempotency_key(request: Any) -> str:
    """写操作强制幂等键（D4 起按需启用）。"""
    value = get_idempotency_key(request)
    if value is None:
        raise AoiError(
            CODE_UNPROCESSABLE,
            'Idempotency-Key is required',
            fields={IDEMPOTENCY_HEADER: 'required'},
        )
    return value
