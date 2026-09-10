"""
检测配置解析 —— 对齐 P0 骨架设计 §4.2

load_config: 将 YAML 文本解析为 InspectConfig
工位模板 JSON 与预标配置 YAML 都解析成同一结构
"""

from pipeline_core.types import InspectConfig, ObjectSpec


def load_config(yaml_text: str) -> InspectConfig:
    """
    解析检测配置 YAML/JSON 文本。

    支持两种格式：
    1. 工位模板 JSON（来自 b_station.template_json）
    2. 检测配置 YAML（来自预标配置）

    Args:
        yaml_text: YAML 或 JSON 格式的配置文本

    Returns:
        InspectConfig 实例

    Raises:
        ValueError: 配置格式不合法
    """
    # 尝试 JSON 解析（工位模板格式）
    import json
    try:
        data = json.loads(yaml_text)
    except json.JSONDecodeError:
        # 尝试 YAML 解析
        try:
            import yaml
            data = yaml.safe_load(yaml_text)
        except ImportError:
            raise ImportError(
                "pyyaml is required for YAML config parsing. "
                "Install with: pip install pipeline-core[yaml]"
            )
        except yaml.YAMLError as e:
            raise ValueError(f"Invalid YAML config: {e}")

    if data is None:
        raise ValueError("Empty config")

    return _parse_config_dict(data)


def _parse_config_dict(data: dict) -> InspectConfig:
    """从字典解析 InspectConfig"""
    objects = []
    for obj_data in data.get("objects", []):
        objects.append(ObjectSpec(
            code=obj_data["code"],
            model_ref=obj_data.get("model_ref", ""),
            class_map=_parse_class_map(obj_data.get("class_map", {})),
            recheck_min=float(obj_data.get("thresholds", {}).get("recheck_min", 0.5)),
            auto_min=float(obj_data.get("thresholds", {}).get("auto_min", 0.9)),
            risk_level=int(obj_data.get("risk_level", 1)),
        ))

    if not objects:
        raise ValueError("Config must have at least one object in 'objects' list")

    return InspectConfig(
        objects=objects,
        tile_size=int(data.get("tile_size", 1280)),
        overlap=float(data.get("overlap", 0.2)),
    )


def _parse_class_map(data: dict) -> dict[int, str]:
    """将 JSON 的字符串 key 转为 int key"""
    return {int(k): v for k, v in data.items()}