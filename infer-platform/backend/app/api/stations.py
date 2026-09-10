"""工位 / 相机 / 工位模板路由 —— 对齐平台B契约 §3.3（D2 阶段 stub）。"""

from __future__ import annotations

import json
from typing import Any

from fastapi import APIRouter, Body, Depends

from ..deps import get_request_id
from ..envelope import CODE_BAD_PAYLOAD, CODE_NOT_FOUND, CODE_STATION_NOT_REGISTERED, CODE_VALIDATION_FAILED, BizError, ok

router = APIRouter()


@router.get("/stations")
def list_stations(request_id: str = Depends(get_request_id)) -> dict[str, Any]:
    return ok([], request_id)


@router.post("/stations")
def create_station(payload: dict[str, Any] = Body(...), request_id: str = Depends(get_request_id)) -> dict[str, Any]:
    code = payload.get("code")
    if not isinstance(code, str) or not code:
        raise BizError(400, CODE_BAD_PAYLOAD, "参数不可读")
    return ok({
        "code": code,
        "name": payload.get("name", ""),
        "enabled": False,
        "channel_id": payload.get("channel_id"),
    }, request_id)


@router.get("/stations/{code}")
def get_station(code: str, request_id: str = Depends(get_request_id)) -> dict[str, Any]:
    raise BizError(404, CODE_NOT_FOUND, "资源不存在")


@router.put("/stations/{code}")
def update_station(code: str, payload: dict[str, Any] = Body(...), request_id: str = Depends(get_request_id)) -> dict[str, Any]:
    return ok({"code": code, "name": payload.get("name", ""), "channel_id": payload.get("channel_id")}, request_id)


@router.delete("/stations/{code}")
def delete_station(code: str, request_id: str = Depends(get_request_id)) -> dict[str, Any]:
    return ok({"code": code}, request_id)


@router.put("/stations/{code}/camera")
def set_camera(code: str, payload: dict[str, Any] = Body(...), request_id: str = Depends(get_request_id)) -> dict[str, Any]:
    return ok({"code": code}, request_id)


@router.post("/stations/{code}/enable")
def enable_station(code: str, request_id: str = Depends(get_request_id)) -> dict[str, Any]:
    return ok({"code": code, "enabled": True}, request_id)


@router.post("/stations/{code}/disable")
def disable_station(code: str, request_id: str = Depends(get_request_id)) -> dict[str, Any]:
    return ok({"code": code, "enabled": False}, request_id)


@router.post("/stations/{code}/capture")
def capture_station(code: str, request_id: str = Depends(get_request_id)) -> dict[str, Any]:
    raise BizError(404, CODE_STATION_NOT_REGISTERED, "工位未注册未启用")


@router.get("/stations/{code}/snapshot")
def snapshot_station(code: str, request_id: str = Depends(get_request_id)) -> dict[str, Any]:
    raise BizError(404, CODE_STATION_NOT_REGISTERED, "工位未注册未启用")


@router.get("/stations/{code}/template")
def get_template(code: str, request_id: str = Depends(get_request_id)) -> dict[str, Any]:
    # 未配置 → 返回 null（suggest 建议值由后续实现补充）
    return ok(None, request_id)


def _validate_template(payload: dict[str, Any]) -> None:
    """按 pipeline-core.load_config 做结构校验；失败抛 42200。"""
    try:
        from pipeline_core.config import load_config
        load_config(json.dumps(payload))
    except BizError:
        raise
    except Exception as exc:  # noqa: BLE001
        raise BizError(422, CODE_VALIDATION_FAILED, "业务校验失败", {"fields": {"template": str(exc)}}) from exc


@router.put("/stations/{code}/template")
def put_template(code: str, payload: dict[str, Any] = Body(...), request_id: str = Depends(get_request_id)) -> dict[str, Any]:
    _validate_template(payload)
    return ok({"code": code, "template_version": int(payload.get("template_version", 0)) + 1}, request_id)


@router.post("/stations/{code}/template/validate")
def validate_template(code: str, payload: dict[str, Any] = Body(...), request_id: str = Depends(get_request_id)) -> dict[str, Any]:
    _validate_template(payload)
    return ok({"valid": True}, request_id)

