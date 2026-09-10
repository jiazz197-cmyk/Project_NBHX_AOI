"""模型库路由 —— 对齐平台B契约 §3.2（D2 阶段 stub，字段齐备）。"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Body, Depends, File, UploadFile

from ..deps import get_request_id
from ..envelope import CODE_BAD_PAYLOAD, CODE_NOT_FOUND, BizError, ok

router = APIRouter()


@router.get("/models")
def list_models(request_id: str = Depends(get_request_id)) -> dict[str, Any]:
    return ok([], request_id)


@router.get("/models/{model_ref}")
def get_model(model_ref: str, request_id: str = Depends(get_request_id)) -> dict[str, Any]:
    raise BizError(404, CODE_NOT_FOUND, "资源不存在")


@router.post("/models/pull")
def pull_model(payload: dict[str, Any] = Body(...), request_id: str = Depends(get_request_id)) -> dict[str, Any]:
    image = payload.get("image")
    if not isinstance(image, str) or not image:
        raise BizError(400, CODE_BAD_PAYLOAD, "参数不可读")
    # D2 用假 manifest 走通流程：仅返回 pulling
    return ok({"status": "pulling"}, request_id)


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
    return ok({"model_ref": model_ref}, request_id)

