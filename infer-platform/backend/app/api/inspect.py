"""推理路由 —— 对齐平台B契约 §3.4（D2 阶段 stub，字段齐备）。"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Body, Depends, File, Form, UploadFile

from ..deps import get_request_id
from ..envelope import ok

router = APIRouter()


@router.post("/inspect/image")
def inspect_image(
    file: UploadFile = File(...),
    station_code: str = Form(...),
    seq: int = Form(0),
    request_id: str = Depends(get_request_id),
) -> dict[str, Any]:
    # stub：空跑返回字段齐备的响应（工位/模板校验在真实实现补上）
    return ok({
        "inspection_id": 0,
        "station_code": station_code,
        "seq": seq,
        "template_version": 0,
        "verdict": "auto_pass",
        "verdict_reasons": [],
        "boxes": [],
        "tiling_meta": {"tile_size": 0, "overlap": 0, "tiles": 0, "ms": 0},
        "latency_ms": 0,
        "pushed": False,
    }, request_id)


@router.post("/inspect/batch")
def inspect_batch(payload: dict[str, Any] = Body(...), request_id: str = Depends(get_request_id)) -> dict[str, Any]:
    object_keys = payload.get("object_keys", [])
    return ok({"job_id": "", "total": len(object_keys), "ok": 0, "failed": 0}, request_id)

