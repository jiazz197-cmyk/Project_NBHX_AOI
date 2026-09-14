"""系统路由 —— 对齐平台B契约 §3.1（D3：outbox 接真实实现）。"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends

from ..deps import get_request_id
from ..envelope import CODE_NOT_FOUND, BizError, ok
from ..outbox import queue

router = APIRouter()

_OUTBOX_ITEM_FIELDS = (
    "id", "kind", "ref_id", "idempotency_key", "attempts",
    "next_retry_at", "status", "last_error", "created_at", "pushed_at",
)


@router.get("/system/info")
def system_info(request_id: str = Depends(get_request_id)) -> dict[str, Any]:
    import pipeline_core
    import skillname

    return ok({
        "versions": {
            "platform": "0.1.0",
            "skillname": skillname.__version__,
            "pipeline_core": pipeline_core.__version__,
            "schema": 1,
        },
        "config": {},
        "paths": {},
        "dependencies": {},
    }, request_id)


@router.get("/system/outbox")
def system_outbox(request_id: str = Depends(get_request_id)) -> dict[str, Any]:
    c = queue.counts()
    items = [{k: it.get(k) for k in _OUTBOX_ITEM_FIELDS} for it in queue.list_items()]
    return ok({"pending": c["pending"], "pushing": c["pushing"], "dead": c["dead"], "items": items}, request_id)


@router.post("/system/outbox/retry-all")
def outbox_retry_all(request_id: str = Depends(get_request_id)) -> dict[str, Any]:
    retried = queue.retry_all()
    result = queue.process_due()
    return ok({"retried": retried, "processed": result["processed"], "pushed": result["pushed"]}, request_id)


@router.post("/system/outbox/{outbox_id}/retry")
def outbox_retry(outbox_id: int, request_id: str = Depends(get_request_id)) -> dict[str, Any]:
    if queue.get_item(outbox_id) is None:
        raise BizError(404, CODE_NOT_FOUND, "资源不存在")
    queue.retry_one(outbox_id)
    result = queue.push_one(outbox_id)
    return ok({"retried": True, "pushed": result["pushed"]}, request_id)


@router.get("/system/audit")
def system_audit(request_id: str = Depends(get_request_id)) -> dict[str, Any]:
    return ok({"total": 0, "items": []}, request_id)

