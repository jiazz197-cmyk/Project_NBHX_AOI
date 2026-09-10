"""工位 / 相机 / 工位模板路由 —— 对齐平台B契约 §3.3（D3：CRUD 与模板校验接真实实现）。"""

from __future__ import annotations

import json
from typing import Any

import yaml
from fastapi import APIRouter, Body, Depends
from fastapi.responses import Response

from ..camera.base import build_camera
from ..deps import get_request_id
from ..envelope import (
    CODE_BAD_PAYLOAD,
    CODE_CONFLICT,
    CODE_NOT_FOUND,
    CODE_STATION_NOT_REGISTERED,
    CODE_VALIDATION_FAILED,
    BizError,
    ok,
)
from ..store import models as store_models
from .inspect import run_inspection

router = APIRouter()


def _station_to_dict(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "code": row["code"],
        "name": row["name"],
        "enabled": bool(row["enabled"]),
        "channel_id": row["channel_id"],
        "status": row["status"],
        "last_capture_at": row["last_capture_at"],
        "last_error": row["last_error"],
        "template_version": row["template_version"],
    }


@router.get("/stations")
def list_stations(request_id: str = Depends(get_request_id)) -> dict[str, Any]:
    return ok([_station_to_dict(r) for r in store_models.list_stations()], request_id)


@router.post("/stations")
def create_station(payload: dict[str, Any] = Body(...), request_id: str = Depends(get_request_id)) -> dict[str, Any]:
    code = payload.get("code")
    if not isinstance(code, str) or not code:
        raise BizError(400, CODE_BAD_PAYLOAD, "参数不可读")
    if store_models.get_station(code) is not None:
        raise BizError(409, CODE_CONFLICT, "工位已存在")
    store_models.create_station({
        "code": code,
        "name": payload.get("name", ""),
        "enabled": bool(payload.get("enabled", False)),
        "channel_id": payload.get("channel_id"),
    })
    row = store_models.get_station(code)
    return ok(_station_to_dict(row), request_id)


@router.get("/stations/{code}")
def get_station(code: str, request_id: str = Depends(get_request_id)) -> dict[str, Any]:
    row = store_models.get_station(code)
    if row is None:
        raise BizError(404, CODE_NOT_FOUND, "资源不存在")
    return ok(_station_to_dict(row), request_id)


@router.put("/stations/{code}")
def update_station(code: str, payload: dict[str, Any] = Body(...), request_id: str = Depends(get_request_id)) -> dict[str, Any]:
    if store_models.get_station(code) is None:
        raise BizError(404, CODE_NOT_FOUND, "资源不存在")
    store_models.update_station(code, {"name": payload.get("name"), "channel_id": payload.get("channel_id")})
    row = store_models.get_station(code)
    return ok(_station_to_dict(row), request_id)


@router.delete("/stations/{code}")
def delete_station(code: str, request_id: str = Depends(get_request_id)) -> dict[str, Any]:
    if store_models.get_station(code) is None:
        raise BizError(404, CODE_NOT_FOUND, "资源不存在")
    store_models.delete_station(code)
    return ok({"code": code}, request_id)


@router.put("/stations/{code}/camera")
def set_camera(code: str, payload: dict[str, Any] = Body(...), request_id: str = Depends(get_request_id)) -> dict[str, Any]:
    if store_models.get_station(code) is None:
        raise BizError(404, CODE_NOT_FOUND, "资源不存在")
    store_models.set_station_camera(code, payload)
    return ok({"code": code}, request_id)


@router.post("/stations/{code}/enable")
def enable_station(code: str, request_id: str = Depends(get_request_id)) -> dict[str, Any]:
    if store_models.get_station(code) is None:
        raise BizError(404, CODE_NOT_FOUND, "资源不存在")
    store_models.set_station_enabled(code, True)
    return ok({"code": code, "enabled": True}, request_id)


@router.post("/stations/{code}/disable")
def disable_station(code: str, request_id: str = Depends(get_request_id)) -> dict[str, Any]:
    if store_models.get_station(code) is None:
        raise BizError(404, CODE_NOT_FOUND, "资源不存在")
    store_models.set_station_enabled(code, False)
    return ok({"code": code, "enabled": False}, request_id)


@router.post("/stations/{code}/capture")
def capture_station(code: str, request_id: str = Depends(get_request_id)) -> dict[str, Any]:
    """软触发一次采集 + 推理（目录相机取图 → run_inspection）。"""
    row = store_models.get_station(code)
    if row is None or not row["enabled"]:
        raise BizError(404, CODE_STATION_NOT_REGISTERED, "工位未注册未启用")
    camera = build_camera(json.loads(row["camera_config"]) if row.get("camera_config") else None)
    if camera is None:
        raise BizError(404, CODE_STATION_NOT_REGISTERED, "工位未配置相机")
    try:
        image_bytes = camera.capture()
    except Exception as exc:  # noqa: BLE001
        raise BizError(404, CODE_STATION_NOT_REGISTERED, "采集失败") from exc
    seq = store_models.next_seq(code)
    data = run_inspection(image_bytes, code, seq, "")
    return ok(data, request_id)


@router.get("/stations/{code}/snapshot")
def snapshot_station(code: str, request_id: str = Depends(get_request_id)) -> Response:
    """最近一帧快照（原始字节）。"""
    row = store_models.get_station(code)
    if row is None:
        raise BizError(404, CODE_NOT_FOUND, "资源不存在")
    camera = build_camera(json.loads(row["camera_config"]) if row.get("camera_config") else None)
    if camera is None:
        raise BizError(404, CODE_STATION_NOT_REGISTERED, "工位未配置相机")
    try:
        image_bytes = camera.snapshot()
    except Exception as exc:  # noqa: BLE001
        raise BizError(404, CODE_STATION_NOT_REGISTERED, "采集失败") from exc
    return Response(content=image_bytes, media_type="image/jpeg")


def _build_suggest() -> dict[str, Any] | None:
    """未配置模板时的建议默认值（取自首个 ready 模型的推荐阈值，契约 §3.3）。"""
    models = [m for m in store_models.list_models() if m["status"] in ("ready", "active")]
    if not models:
        return None
    row = models[0]
    try:
        config = yaml.safe_load(row["config_json"])
    except Exception:  # noqa: BLE001
        return None
    if not isinstance(config, dict):
        return None
    classes = config.get("classes") or []
    objects = []
    for i, cls in enumerate(classes):
        rec = cls.get("recommended") or {}
        objects.append({
            "code": cls.get("code"),
            "class_map": {str(cls.get("index", i)): cls.get("code")},
            "thresholds": {
                "recheck_min": rec.get("recheck_min", 0.5),
                "auto_min": rec.get("auto_min", 0.9),
            },
            "risk_level": cls.get("risk_level", 1),
        })
    tiling = config.get("tiling") or {}
    return {
        "model_ref": row["model_ref"],
        "skillname": row["skillname"],
        "tile_size": tiling.get("recommended_tile_size", 1280),
        "overlap": tiling.get("overlap", 0.2),
        "objects": objects,
    }


@router.get("/stations/{code}/template")
def get_template(code: str, request_id: str = Depends(get_request_id)) -> dict[str, Any]:
    row = store_models.get_station(code)
    if row is None:
        raise BizError(404, CODE_NOT_FOUND, "资源不存在")
    if not row.get("template_json"):
        return ok({"template": None, "suggest": _build_suggest()}, request_id)
    return ok({"template": json.loads(row["template_json"]), "suggest": None}, request_id)


def _validate_template(payload: dict[str, Any]) -> None:
    """按 §3.3 校验规则：load_config 结构校验 + model_ref 就绪 + code ∈ class_names。"""
    from pipeline_core.config import load_config

    try:
        load_config(json.dumps(payload))
    except BizError:
        raise
    except Exception as exc:  # noqa: BLE001
        raise BizError(422, CODE_VALIDATION_FAILED, "业务校验失败", {"fields": {"template": str(exc)}}) from exc

    # 规则 1：model_ref ∈ b_model 且 ready
    model_ref = payload.get("model_ref")
    row = store_models.get_model(model_ref) if isinstance(model_ref, str) else None
    if row is None or row["status"] not in ("ready", "active"):
        raise BizError(422, CODE_VALIDATION_FAILED, "业务校验失败", {"fields": {"model_ref": "模型不存在或未就绪"}})

    # 规则 3：code ∈ class_names；class_map key ∈ 类别索引
    class_names = json.loads(row["class_names"])
    num_classes = len(class_names)
    for i, obj in enumerate(payload.get("objects", [])):
        code = obj.get("code")
        if code not in class_names:
            raise BizError(422, CODE_VALIDATION_FAILED, "业务校验失败",
                           {"fields": {f"objects[{i}].code": f"{code!r} 不在模型 class_names"}})
        for k in obj.get("class_map", {}):
            try:
                idx = int(k)
            except (TypeError, ValueError):
                idx = -1
            if idx < 0 or idx >= num_classes:
                raise BizError(422, CODE_VALIDATION_FAILED, "业务校验失败",
                               {"fields": {f"objects[{i}].class_map": f"key {k!r} 超出类别索引 0..{num_classes - 1}"}})


@router.put("/stations/{code}/template")
def put_template(code: str, payload: dict[str, Any] = Body(...), request_id: str = Depends(get_request_id)) -> dict[str, Any]:
    if store_models.get_station(code) is None:
        raise BizError(404, CODE_NOT_FOUND, "资源不存在")
    _validate_template(payload)
    version = int(payload.get("template_version", 0)) + 1
    store_models.set_station_template(code, json.dumps(payload, ensure_ascii=False), version)
    return ok({"code": code, "template_version": version}, request_id)


@router.post("/stations/{code}/template/validate")
def validate_template(code: str, payload: dict[str, Any] = Body(...), request_id: str = Depends(get_request_id)) -> dict[str, Any]:
    _validate_template(payload)
    return ok({"valid": True}, request_id)

