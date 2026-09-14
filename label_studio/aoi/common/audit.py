"""审计写入（aoi_audit.audit_log，契约 §3.5）。

D4 起角色/授权变更等关键操作必须留下审计：写入失败**不阻断业务**，但必须 `warning` 可见
（`request_id` 截断到列宽 64，避免超长头把审计写入整条吞掉）。
"""

from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger(__name__)

__all__ = ['write_audit']

#: ``AuditLog.request_id`` 列宽
_REQUEST_ID_MAX_LENGTH = 64


def write_audit(
    *,
    actor_id: int | None,
    action: str,
    object_type: str = '',
    object_id: str = '',
    detail: Any = None,
    request_id: str | None = None,
) -> None:
    """写一条审计记录；任何失败只记日志，不影响主流程。"""
    try:
        from aoi.audit.models import AuditLog

        AuditLog.objects.create(
            actor_id=actor_id,
            action=action,
            object_type=object_type,
            object_id=str(object_id) if object_id is not None else '',
            detail=detail or {},
            request_id=request_id[:_REQUEST_ID_MAX_LENGTH] if request_id else request_id,
        )
    except Exception:  # pragma: no cover - 表未就绪/DB 异常时降级
        logger.warning('write_audit failed action=%s request_id=%s', action, request_id, exc_info=True)
