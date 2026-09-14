"""
检测配置解析 —— 对齐 P0 骨架设计 §4.2 / 平台B契约 §3.3。

load_config: 将 YAML/JSON 文本解析为 InspectConfig，并做结构校验：
  - objects 非空、code 唯一且通过 skillname.is_valid_fault_code
  - class_map 的 value 全等于 code
  - 0 < recheck_min < auto_min < 1
  - tile_size > 0、0 <= overlap < 1

工位模板 JSON（b_station.template_json）与预标配置 YAML 都解析成同一结构。
"""

from __future__ import annotations

from typing import Any

from pipeline_core.types import InspectConfig, ObjectSpec


def load_config(yaml_text: str) -> InspectConfig:
    """解析检测配置（JSON 优先，否则 YAML）为 InspectConfig。"""
    data = _load_document(yaml_text)
    if not isinstance(data, dict):
        raise ValueError("config must be a mapping")

    objects_data = data.get("objects")
    if not isinstance(objects_data, list) or not objects_data:
        raise ValueError("config.objects must be a non-empty list")

    top_model_ref = data.get("model_ref", "")

    objects: list[ObjectSpec] = []
    seen_codes: set[str] = set()
    seen_class_ids: dict[str, set[int]] = {}
    for obj in objects_data:
        if not isinstance(obj, dict):
            raise ValueError("config.objects[] must be a mapping")

        code = obj.get("code")
        if not isinstance(code, str):
            raise ValueError("object code must be str")
        from skillname import is_valid_fault_code
        if not is_valid_fault_code(code):
            raise ValueError(f"invalid object code: {code!r}")
        if code in seen_codes:
            raise ValueError(f"duplicate object code: {code}")
        seen_codes.add(code)

        class_map = obj.get("class_map")
        if not isinstance(class_map, dict) or not class_map:
            raise ValueError(f"object {code}: class_map must be a non-empty mapping")
        parsed_map = {int(k): v for k, v in class_map.items()}
        for v in parsed_map.values():
            if v != code:
                raise ValueError(f"object {code}: class_map value {v!r} != code")

        thresholds = obj.get("thresholds")
        if not isinstance(thresholds, dict):
            raise ValueError(f"object {code}: thresholds is required")
        recheck_min = _require_float(thresholds.get("recheck_min"), f"object {code} thresholds.recheck_min")
        auto_min = _require_float(thresholds.get("auto_min"), f"object {code} thresholds.auto_min")
        if not (0 < recheck_min < auto_min < 1):
            raise ValueError(f"object {code}: require 0 < recheck_min < auto_min < 1")

        risk_level = obj.get("risk_level")
        if not isinstance(risk_level, int) or not (1 <= risk_level <= 3):
            raise ValueError(f"object {code}: risk_level must be int in [1, 3]")

        model_ref = obj.get("model_ref") or top_model_ref
        if not isinstance(model_ref, str) or not model_ref:
            raise ValueError(f"object {code}: model_ref is required")

        # 同一 model_ref 下，class_map 的类别索引不得跨 object 重复（否则静默覆盖映射）
        ids = seen_class_ids.setdefault(model_ref, set())
        for cls_id in parsed_map:
            if cls_id in ids:
                raise ValueError(f"model {model_ref}: duplicate class_map index {cls_id} across objects")
            ids.add(cls_id)

        objects.append(ObjectSpec(
            code=code,
            model_ref=model_ref,
            class_map=parsed_map,
            recheck_min=recheck_min,
            auto_min=auto_min,
            risk_level=risk_level,
        ))

    tile_size = data.get("tile_size", 1280)
    if not isinstance(tile_size, int) or tile_size <= 0:
        raise ValueError("tile_size must be a positive int")
    overlap = data.get("overlap", 0.2)
    if not isinstance(overlap, (int, float)) or not (0 <= overlap < 1):
        raise ValueError("overlap must satisfy 0 <= overlap < 1")

    return InspectConfig(objects=objects, tile_size=int(tile_size), overlap=float(overlap))


def _load_document(text: str) -> Any:
    """JSON 优先；否则按 YAML 解析（需 pyyaml）。"""
    import json
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass
    try:
        import yaml
    except ImportError as exc:
        raise ImportError(
            "pyyaml is required for YAML config parsing. "
            "Install with: pip install pipeline-core[yaml]"
        ) from exc
    data = yaml.safe_load(text)
    if data is None:
        raise ValueError("empty config")
    return data


def _require_float(value: Any, name: str) -> float:
    if value is None:
        raise ValueError(f"{name} is required")
    try:
        return float(value)
    except (TypeError, ValueError):
        raise ValueError(f"{name} must be numeric")