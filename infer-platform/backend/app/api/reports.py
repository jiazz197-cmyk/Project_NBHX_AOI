"""日报路由 —— 对齐平台B契约 §3.7（D2 阶段 stub）。"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends

from ..deps import get_request_id
from ..envelope import CODE_NOT_FOUND, BizError, ok

router = APIRouter()


@router.get("/reports/daily")
def list_daily_reports(request_id: str = Depends(get_request_id)) -> dict[str, Any]:
    return ok({"total": 0, "items": []}, request_id)


@router.get("/reports/daily/{day}")
def get_daily_report(day: str, request_id: str = Depends(get_request_id)) -> dict[str, Any]:
    raise BizError(404, CODE_NOT_FOUND, "资源不存在")


@router.post("/reports/daily/{day}/generate")
def generate_daily_report(day: str, request_id: str = Depends(get_request_id)) -> dict[str, Any]:
    return ok({"day": day, "status": "generated"}, request_id)


@router.get("/reports/daily/{day}/export")
def export_daily_report(day: str, format: str = "html", request_id: str = Depends(get_request_id)) -> dict[str, Any]:
    raise BizError(404, CODE_NOT_FOUND, "资源不存在")

