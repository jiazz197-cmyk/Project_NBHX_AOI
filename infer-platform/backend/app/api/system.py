"""系统路由 —— 对齐平台B契约 §3.1（D2 阶段 stub）。"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends

from ..deps import get_request_id
from ..envelope import CODE_NOT_FOUND, BizError, ok

router = APIRouter()


@router.get("/system/info")
def system_info(request_id: str = Depends(get_request_id)) -> dict[str, Any]:
    return ok({
        "versions": {
            "platform": "0.1.0",
            "skillname": "0.1.0",
            "pipeline_core": "0.1.0",
            "schema": 1,
        },
        "config": {},
        "paths": {},
        "dependencies": {},
    }, request_id)


@router.get("/system/outbox")
def system_outbox(request_id: str = Depends(get_request_id)) -> dict[str, Any]:
    return ok({"pending": 0, "pushing": 0, "dead": 0, "items": []}, request_id)


@router.post("/system/outbox/retry-all")
def outbox_retry_all(request_id: str = Depends(get_request_id)) -> dict[str, Any]:
    return ok({"retried": 0}, request_id)


@router.post("/system/outbox/{outbox_id}/retry")
def outbox_retry(outbox_id: int, request_id: str = Depends(get_request_id)) -> dict[str, Any]:
    raise BizError(404, CODE_NOT_FOUND, "资源不存在")


@router.get("/system/audit")
def system_audit(request_id: str = Depends(get_request_id)) -> dict[str, Any]:
    return ok({"total": 0, "items": []}, request_id)

