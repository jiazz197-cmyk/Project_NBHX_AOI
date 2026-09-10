"""模型库路由 —— 对齐平台B契约 §3.2（D3：拉取链路接真实实现）。"""

from __future__ import annotations

import json
from typing import Any

from fastapi import APIRouter, Body, Depends, File, UploadFile

from ..deps import get_request_id
from ..envelope import CODE_BAD_PAYLOAD, CODE_NOT_FOUND, BizError, ok
from ..registry import pull as registry_pull
from ..store import models as store_models

router = APIRouter()


@router.get("/models")
def list_models(request_id: str = Depends(get_request_id)) -> dict[str, Any]:
    items = [store_models.to_list_item(r) for r in store_models.list_models()]
    return ok(items, request_id)


@router.get("/models/{model_ref}")
def get_model(model_ref: str, request_id: str = Depends(get_request_id)) -> dict[str, Any]:
    row = store_models.get_model(model_ref)
    if row is None:
        raise BizError(404, CODE_NOT_FOUND, "资源不存在")
    return ok({
        "model_ref": row["model_ref"],
        "skillname": row["skillname"],
        "precision": row["precision"],
        "sha256": row["sha256"],
        "source_image": row["source_image"],
        "image_digest": row["image_digest"],
        "status": row["status"],
        "classes": json.loads(row["class_names"]),
        "received_at": row["received_at"],
        "config_json": row["config_json"],
        "stored_path": row["stored_path"],
        "opset": row["opset"],
        "input_name": row["input_name"],
        "output_name": row["output_name"],
        "input_shape": row["input_shape"],
    }, request_id)


@router.post("/models/pull")
def pull_model(payload: dict[str, Any] = Body(...), request_id: str = Depends(get_request_id)) -> dict[str, Any]:
    image = payload.get("image")
    if not isinstance(image, str) or not image:
        raise BizError(400, CODE_BAD_PAYLOAD, "参数不可读")
    digest = payload.get("digest")
    result = registry_pull.pull_model(image, digest)
    return ok(result, request_id)


@router.post("/models/import")
def import_model(file: UploadFile = File(...), request_id: str = Depends(get_request_id)) -> dict[str, Any]:
    # multipart tar → 解包校验（stub）
    return ok({"status": "importing"}, request_id)


@router.post("/models/{model_ref}/preload")
def preload_model(model_ref: str, request_id: str = Depends(get_request_id)) -> dict[str, Any]:
    return ok({"model_ref": model_ref, "status": "ready"}, request_id)


@router.post("/models/{model_ref}/unload")
def unload_model(model_ref: str, request_id: str = Depends(get_request_id)) -> dict[str, Any]:
    return ok({"model_ref": model_ref}, request_id)


@router.delete("/models/{model_ref}")
def delete_model(model_ref: str, request_id: str = Depends(get_request_id)) -> dict[str, Any]:
    if store_models.get_model(model_ref) is None:
        raise BizError(404, CODE_NOT_FOUND, "资源不存在")
    store_models.delete_model(model_ref)
    return ok({"model_ref": model_ref}, request_id)

