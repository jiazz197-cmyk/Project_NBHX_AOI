"""检测记录路由 —— 对齐平台B契约 §3.5（D2 阶段 stub）。"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends

from ..deps import get_request_id
from ..envelope import CODE_NOT_FOUND, BizError, ok

router = APIRouter()


@router.get("/inspections")
def list_inspections(request_id: str = Depends(get_request_id)) -> dict[str, Any]:
    return ok({"total": 0, "items": []}, request_id)


@router.get("/inspections/{inspection_id}")
def get_inspection(inspection_id: int, request_id: str = Depends(get_request_id)) -> dict[str, Any]:
    raise BizError(404, CODE_NOT_FOUND, "资源不存在")


@router.get("/inspections/{inspection_id}/image")
def inspection_image(inspection_id: int, request_id: str = Depends(get_request_id)) -> dict[str, Any]:
    raise BizError(404, CODE_NOT_FOUND, "资源不存在")


@router.get("/inspections/{inspection_id}/thumb")
def inspection_thumb(inspection_id: int, request_id: str = Depends(get_request_id)) -> dict[str, Any]:
    raise BizError(404, CODE_NOT_FOUND, "资源不存在")


@router.get("/bad-images")
def list_bad_images(request_id: str = Depends(get_request_id)) -> dict[str, Any]:
    return ok({"total": 0, "items": []}, request_id)

