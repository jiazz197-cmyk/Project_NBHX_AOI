"""健康检查路由：GET /api/v1/health。

data 结构与平台B契约 §3.1 逐字一致。
"""

from __future__ import annotations

import shutil
from typing import Any

from fastapi import APIRouter, Depends, Request

from ..config import get_settings
from ..deps import get_request_id
from ..envelope import ok

router = APIRouter()


@router.get("/health")
def health(request: Request, request_id: str = Depends(get_request_id)) -> dict[str, Any]:
    settings = get_settings()
    try:
        usage = shutil.disk_usage(settings.DATA_DIR)
        disk = {
            "free_gb": round(usage.free / 1024**3, 1),
            "used_pct": round((1 - usage.free / usage.total) * 100),
        }
    except OSError:
        disk = {"free_gb": 0.0, "used_pct": 0}

    data = {
        "status": "UP",
        "gpu": {"device": 0, "mem_used_gb": 0.0, "mem_total_gb": 0.0},
        "disk": disk,
        "models": [],
        "stations": {"total": 0, "enabled": 0, "online": 0, "with_template": 0},
        "inspect": {"queue": 0, "concurrency": settings.INSPECT_CONCURRENCY},
        "outbox": {"pending": 0, "dead": 0},
    }
    return ok(data, request_id)

