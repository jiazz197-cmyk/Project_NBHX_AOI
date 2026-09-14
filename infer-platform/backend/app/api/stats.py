"""统计路由 —— 对齐平台B契约 §3.6/§6（D2 阶段 stub，字段齐备）。"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends

from ..deps import get_request_id
from ..envelope import ok

router = APIRouter()


@router.get("/stats/summary")
def stats_summary(request_id: str = Depends(get_request_id)) -> dict[str, Any]:
    return ok({
        "total": 0,
        "auto_pass": 0,
        "recheck": 0,
        "manual": 0,
        "bad_count": 0,
        "pass_rate": 0.0,
        "defect_topn": [],
        "avg_latency_ms": 0,
        "p95_latency_ms": 0,
        "stations_online": 0,
        "stations_total": 0,
    }, request_id)


@router.get("/stats/trend")
def stats_trend(request_id: str = Depends(get_request_id)) -> dict[str, Any]:
    return ok([], request_id)


@router.get("/stats/errors")
def stats_errors(request_id: str = Depends(get_request_id)) -> dict[str, Any]:
    return ok({
        "bad_by_code": {},
        "suspicious_by_code": {},
        "suspicious_by_verdict": {},
        "top_stations": [],
        "pushed_status": {"pushed": 0, "pending": 0, "dead": 0},
    }, request_id)

