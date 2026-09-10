"""审计写入占位（aoi_audit.audit_log，契约 §3.5）。

D4 起随 RBAC/发布/训练/导出等关键操作补齐；D1–D2 表未就绪时静默降级（不阻断业务）。
"""

from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger(__name__)

__all__ = ['write_audit']


def write_audit(
    *,
    actor_id: int | None,
    action: str,
    object_type: str = '',
    object_id: str = '',
    detail: Any = None,
    request_id: str | None = None,
) -> None:
    """写一条审计记录；任何失败只记日志，不影响主流程（D1–D2 占位）。"""
    try:
        from aoi.audit.models import AuditLog

        AuditLog.objects.create(
            actor_id=actor_id,
            action=action,
            object_type=object_type,
            object_id=str(object_id) if object_id is not None else '',
            detail=detail or {},
            request_id=request_id,
        )
    except Exception:  # pragma: no cover - 表未就绪/DB 异常时降级
        logger.debug('write_audit skipped (table not ready?) action=%s', action, exc_info=True)
