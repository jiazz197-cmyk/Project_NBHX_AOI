"""日报路由 —— 对齐平台B契约 §3.7（D3：接真实日报生成与查询）。"""

from __future__ import annotations

import json
from typing import Any

from fastapi import APIRouter, Depends
from fastapi.responses import FileResponse

from ..deps import get_request_id
from ..envelope import CODE_NOT_FOUND, BizError, ok
from ..report import daily
from ..store import models as store_models

router = APIRouter()


@router.get("/reports/daily")
def list_daily_reports(request_id: str = Depends(get_request_id)) -> dict[str, Any]:
    items = [
        {**json.loads(r["stats_json"] or "{}"), "html_path": r["html_path"], "csv_path": r["csv_path"]}
        for r in store_models.list_reports()
    ]
    return ok({"total": len(items), "items": items}, request_id)


@router.get("/reports/daily/{day}")
def get_daily_report(day: str, request_id: str = Depends(get_request_id)) -> dict[str, Any]:
    row = store_models.get_report(day)
    if row is None:
        raise BizError(404, CODE_NOT_FOUND, "资源不存在")
    return ok({
        "day": row["day"],
        "html_path": row["html_path"],
        "csv_path": row["csv_path"],
        "stats_json": row["stats_json"],
        "generated_at": row["generated_at"],
    }, request_id)


@router.post("/reports/daily/{day}/generate")
def generate_daily_report(day: str, request_id: str = Depends(get_request_id)) -> dict[str, Any]:
    result = daily.generate_daily(day)
    return ok(result, request_id)


@router.get("/reports/daily/{day}/export")
def export_daily_report(day: str, format: str = "html", request_id: str = Depends(get_request_id)) -> Any:
    row = store_models.get_report(day)
    if row is None:
        raise BizError(404, CODE_NOT_FOUND, "资源不存在")
    path = row["html_path"] if format == "html" else row["csv_path"]
    return FileResponse(path, filename=f"{day}.{format}")

