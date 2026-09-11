"""推理路由 —— 对齐平台B契约 §3.4 / §4.1（D3：接真实推理链路）。

执行顺序（§4.1）：解码（坏图→40010+登记）→ 取模板（无→42200）→ run → 落库
→ verdict != auto_pass 写 outbox（suspicious）→ 响应。
"""

from __future__ import annotations

import hashlib
from datetime import datetime, timezone
from io import BytesIO
from typing import Any

import numpy as np
from fastapi import APIRouter, Body, Depends, File, Form, UploadFile
from PIL import Image
from pipeline_core.config import load_config

from ..config import get_settings
from ..deps import get_request_id
from ..envelope import (
    CODE_BAD_PAYLOAD,
    CODE_STATION_NOT_REGISTERED,
    CODE_VALIDATION_FAILED,
    BizError,
    ok,
)
from ..inference import engine
from ..outbox import queue
from ..store import models as store_models

router = APIRouter()


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _box_to_dict(box: Any) -> dict[str, Any]:
    return {
        "object_code": box.object_code,
        "score": box.score,
        "model_ref": box.model_ref,
        "xyxy": list(box.xyxy),
    }


def register_bad_image(
    station_code: str,
    seq: int,
    captured_at: str,
    error_code: str,
    station_name: str | None = None,
    template_version: int | None = None,
) -> int:
    """登记坏图 + 异步入队 kind=bad 无图回传 A；返回 b_bad_image.id。

    error_code ∈ {capture_failed, decode_failed, timeout, model_error, disk_error}。
    坏图无图可落：image_path 保持 NULL，推送时不带 file（跨平台契约 §3.1）。
    """
    settings = get_settings()
    now = _now()
    bad_image_id = store_models.insert_bad_image({
        "station_code": station_code, "seq": seq,
        "captured_at": captured_at or now, "error_code": error_code,
    })
    meta = {
        "kind": "bad",
        "instance_code": settings.INSTANCE_CODE,
        "station_code": station_code,
        "station_name": station_name,
        "seq": seq,
        "captured_at": captured_at or now,
        "received_at": now,
        "template_version": template_version,
        "model_refs": [],
        "verdict": None,
        "verdict_reasons": [],
        "boxes": [],
        "tiling_meta": {},
        "latency_ms": None,
        "image": None,
        "error_code": error_code,
        "versions": {"platform": "0.1.0", "skillname": "0.1.0", "pipeline_core": "0.1.0"},
    }
    queue.enqueue("bad", bad_image_id, station_code, seq, meta)
    return bad_image_id


def run_inspection(image_bytes: bytes, station_code: str, seq: int, captured_at: str) -> dict[str, Any]:
    """核心推理链路（inspect/image 与 capture 共用），返回响应 data。"""
    settings = get_settings()

    # 1. 解码（坏图 → 40010 + 登记 b_bad_image + 异步入队回传 A）
    try:
        img = Image.open(BytesIO(image_bytes)).convert("RGB")
        arr = np.array(img)
        md5 = hashlib.md5(image_bytes).hexdigest()
        width, height = img.size
    except Exception as exc:  # noqa: BLE001
        register_bad_image(station_code, seq, captured_at, "decode_failed")
        raise BizError(400, CODE_BAD_PAYLOAD, "坏图") from exc

    # 2. 工位（未注册/未启用 → 40402）
    station = store_models.get_station(station_code)
    if station is None or not station["enabled"]:
        raise BizError(404, CODE_STATION_NOT_REGISTERED, "工位未注册未启用")

    # 3. 工位模板（未配置 → 42200）
    if not station.get("template_json"):
        raise BizError(422, CODE_VALIDATION_FAILED, "工位未配置模板", {"fields": {"template": "未配置"}})
    cfg = load_config(station["template_json"])

    # 4. 推理（模型未就绪 → 50300，由 engine 抛出）
    result = engine.run_inference(arr, cfg)

    # 5. 落库
    now = _now()
    model_refs = sorted({obj.model_ref for obj in cfg.objects})
    boxes = [_box_to_dict(b) for b in result.boxes]
    latency_ms = int(result.tiling_meta.get("ms", 0))
    pushed_status = "pending" if result.verdict != "auto_pass" else "n/a"
    inspection_id = store_models.insert_inspection({
        "station_code": station_code, "seq": seq,
        "captured_at": captured_at or now, "received_at": now,
        "template_version": station.get("template_version"),
        "model_refs": model_refs,
        "verdict": result.verdict,
        "verdict_reasons": result.verdict_reasons,
        "boxes": boxes,
        "tiling_meta": result.tiling_meta,
        "latency_ms": latency_ms,
        "image_md5": md5,
        "pushed_status": pushed_status,
    })

    # 6. verdict != auto_pass → 写 outbox（suspicious）异步回传 A
    pushed = False
    if result.verdict != "auto_pass":
        meta = {
            "kind": "suspicious",
            "instance_code": settings.INSTANCE_CODE,
            "station_code": station_code,
            "station_name": station.get("name"),
            "seq": seq,
            "captured_at": captured_at or now,
            "received_at": now,
            "template_version": station.get("template_version"),
            "model_refs": model_refs,
            "verdict": result.verdict,
            "verdict_reasons": result.verdict_reasons,
            "boxes": boxes,
            "tiling_meta": result.tiling_meta,
            "latency_ms": latency_ms,
            "image": {"md5": md5, "ext": "jpg", "width": width, "height": height, "size_bytes": len(image_bytes)},
            "error_code": None,
            "versions": {"platform": "0.1.0", "skillname": "0.1.0", "pipeline_core": "0.1.0"},
        }
        queue.enqueue("suspicious", inspection_id, station_code, seq, meta)
        pushed = True

    return {
        "inspection_id": inspection_id,
        "station_code": station_code,
        "seq": seq,
        "template_version": station.get("template_version"),
        "verdict": result.verdict,
        "verdict_reasons": result.verdict_reasons,
        "boxes": boxes,
        "tiling_meta": result.tiling_meta,
        "latency_ms": latency_ms,
        "pushed": pushed,
    }


@router.post("/inspect/image")
def inspect_image(
    file: UploadFile = File(...),
    station_code: str = Form(...),
    seq: int = Form(0),
    captured_at: str = Form(""),
    request_id: str = Depends(get_request_id),
) -> dict[str, Any]:
    image_bytes = file.file.read()
    return ok(run_inspection(image_bytes, station_code, seq, captured_at), request_id)


@router.post("/inspect/batch")
def inspect_batch(payload: dict[str, Any] = Body(...), request_id: str = Depends(get_request_id)) -> dict[str, Any]:
    object_keys = payload.get("object_keys", [])
    return ok({"job_id": "", "total": len(object_keys), "ok": 0, "failed": 0}, request_id)

