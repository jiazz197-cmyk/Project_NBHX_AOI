"""``model.yaml`` 生成与 A 侧校验（契约 §7 / 跨平台契约 §2.3；T2.4）。

- ``build_model_yaml``：从 ``aoi_training.model`` + 字典 + 训练/ONNX 元数据生成能力描述 dict；
- ``dump_model_yaml``：``yaml.safe_dump(sort_keys=False, allow_unicode=True)``；
- ``validate_model_yaml``：实现跨平台契约 §2.3 校验 1–8 的 **A 侧子集**（sha256 只校验形状，
  实际文件校验在发布构建时执行）。
"""

from __future__ import annotations

import os
import re
from datetime import datetime, timezone
from typing import Any, Iterable, Mapping

import yaml
from skillname import (
    SkillName,
    color_for_index,
    is_valid_fault_code,
    parse_model_ref,
)

__all__ = ['build_model_yaml', 'dump_model_yaml', 'validate_model_yaml', 'model_ref_from_model']

SCHEMA_VERSION = 1
REQUIRED_TOP_LEVEL = ('schema_version', 'model_ref', 'skillname', 'framework', 'precision', 'gate_status')
REQUIRED_ONNX = ('file', 'sha256', 'size_bytes', 'opset', 'input', 'output')
REQUIRED_ONNX_INPUT = ('name', 'shape', 'dtype', 'layout')
REQUIRED_ONNX_OUTPUT = ('name', 'shape', 'format')
REQUIRED_CLASS_FIELDS = ('index', 'code', 'name_cn', 'risk_level', 'recommended')
_SHA256_RE = re.compile(r'^[0-9a-f]{64}$')

#: 风险档 → 推荐阈值（跨平台契约 §2.3 示例；发布前可人工微调）
RECOMMENDED_BY_RISK = {
    3: {'recheck_min': 0.60, 'auto_min': 0.90},
    2: {'recheck_min': 0.55, 'auto_min': 0.88},
    1: {'recheck_min': 0.50, 'auto_min': 0.85},
}

DEFAULT_POSTPROCESS = {
    'conf_threshold': 0.25,
    'iou_threshold': 0.50,
    'max_detections': 300,
    'agnostic_nms': False,
    'multi_label': False,
    'box_format': 'xyxy',
    'class_agnostic': False,
}


def _get(obj: Any, key: str, default: Any = None) -> Any:
    if obj is None:
        return default
    if isinstance(obj, Mapping):
        return obj.get(key, default)
    return getattr(obj, key, default)


def _utcnow() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace('+00:00', 'Z')


def model_ref_from_model(model: Any) -> str:
    """``aoi_training.model.version`` 即 ``model_ref``。"""
    return str(_get(model, 'version') or '')


def _normalize_defect_classes(defect_classes: Iterable[Any] | None) -> dict[str, dict[str, Any]]:
    by_code: dict[str, dict[str, Any]] = {}
    for position, item in enumerate(defect_classes or []):
        code = _get(item, 'code')
        if not code:
            continue
        by_code[str(code)] = {
            'code': str(code),
            'name_cn': _get(item, 'name_cn'),
            'name_en': _get(item, 'name_en'),
            'risk_level': _get(item, 'risk_level', 1),
            'color': _get(item, 'color'),
            'aliases': _get(item, 'aliases') or [],
            'enabled': _get(item, 'enabled', True),
            'min_box_size': _get(item, 'min_box_size'),
            'max_boxes_per_image': _get(item, 'max_boxes_per_image'),
            'recommended': _get(item, 'recommended'),
            '_input_position': position,
        }
    return by_code


def _build_classes(model: Any, defect_classes: Iterable[Any] | None) -> list[dict[str, Any]]:
    by_code = _normalize_defect_classes(defect_classes)
    class_names = _get(model, 'class_names') or []
    if not class_names:
        class_names = [entry['code'] for entry in sorted(by_code.values(), key=lambda entry: entry['_input_position'])]

    classes: list[dict[str, Any]] = []
    for index, code in enumerate(class_names):
        code = str(code)
        meta = by_code.get(code, {})
        risk_level = meta.get('risk_level', 1)
        recommended = meta.get('recommended') or RECOMMENDED_BY_RISK.get(int(risk_level), RECOMMENDED_BY_RISK[1])
        classes.append(
            {
                'index': index,
                'code': code,
                'name_cn': meta.get('name_cn') or code,
                'name_en': meta.get('name_en'),
                'risk_level': risk_level,
                'color': meta.get('color') or color_for_index(index),
                'aliases': meta.get('aliases') or [],
                'enabled': meta.get('enabled', True),
                'min_box_size': meta.get('min_box_size'),
                'max_boxes_per_image': meta.get('max_boxes_per_image'),
                'recommended': dict(recommended),
            }
        )
    return classes


def build_model_yaml(
    model: Any,
    *,
    defect_classes: Iterable[Any] | None = None,
    base_model: Any = None,
    train_job: Any = None,
    onnx_meta: Any = None,
    source: Any = None,
) -> dict[str, Any]:
    """生成 ``model.yaml`` dict（字段位齐全，预留字段 ``null``/``{}``）。

    ``source`` 可携带 ``created_at``/``git_commit``/``dict_version``/``license``/``description``/
    ``tags``/``published_at``/``benchmark`` 等覆盖值（``created_at`` 不写入输出 source 块）。
    """
    source_meta: dict[str, Any] = dict(source or {}) if isinstance(source, Mapping) else {}
    classes = _build_classes(model, defect_classes)
    precision = str(_get(model, 'precision', 'fp32') or 'fp32')
    onnx_meta = onnx_meta or {}
    onnx_input = dict(_get(onnx_meta, 'input', {}) or {})
    onnx_output = dict(_get(onnx_meta, 'output', {}) or {})
    preset = _get(train_job, 'preset', {}) or {}
    params = dict(_get(preset, 'params', {}) or {})
    tiling_params = dict(params.get('tiling', {}) or {})

    num_classes = len(classes)
    input_shape = _get(onnx_meta, 'input_shape') or _get(model, 'input_shape') or [1, 3, 1280, 1280]
    output_shape = _get(onnx_meta, 'output_shape') or [1, 4 + num_classes, 8400]

    onnx = {
        'file': str(_get(onnx_meta, 'file', 'model.onnx') or 'model.onnx'),
        'sha256': str(_get(onnx_meta, 'sha256', '') or ''),
        'size_bytes': int(_get(onnx_meta, 'size_bytes', 0) or 0),
        'opset': int(_get(onnx_meta, 'opset', 17) or 17),
        'ir_version': _get(onnx_meta, 'ir_version'),
        'producer': _get(onnx_meta, 'producer'),
        'dynamic_batch': bool(_get(onnx_meta, 'dynamic_batch', True)),
        'max_batch_size': _get(onnx_meta, 'max_batch_size'),
        'input': {
            'name': str(onnx_input.get('name') or 'images'),
            'shape': list(onnx_input.get('shape') or input_shape),
            'dtype': str(onnx_input.get('dtype') or 'float32'),
            'layout': str(onnx_input.get('layout') or 'NCHW'),
            'color_order': str(onnx_input.get('color_order') or 'RGB'),
            'normalize': onnx_input.get('normalize')
            or {'scale': 0.00392156862745098, 'mean': [0, 0, 0], 'std': [1, 1, 1]},
            'resize': onnx_input.get('resize') or {'mode': 'letterbox', 'interpolation': 'bilinear', 'pad_value': 114},
        },
        'output': {
            'name': str(onnx_output.get('name') or 'output0'),
            'shape': list(onnx_output.get('shape') or output_shape),
            'format': str(onnx_output.get('format') or 'yolo_v8_xywh_conf_cls'),
            'num_classes': int(onnx_output.get('num_classes', num_classes) or num_classes),
            'num_anchors': onnx_output.get('num_anchors'),
        },
        'runtime': {
            'providers': (onnx_meta.get('runtime') or {}).get('providers') or ['cuda', 'cpu'],
            'fp16': bool((onnx_meta.get('runtime') or {}).get('fp16', precision == 'fp16')),
            'threads': int((onnx_meta.get('runtime') or {}).get('threads', 4)),
        },
    }

    metrics = dict(_get(model, 'eval_metrics') or {})
    training = {
        'epochs': params.get('epochs'),
        'imgsz': params.get('imgsz'),
        'batch': params.get('batch'),
        'lr0': params.get('lr0'),
        'patience': params.get('patience'),
        'seed': params.get('seed'),
        'augment': params.get('augment') or {},
        'split': params.get('split') or {},
    }

    return {
        'schema_version': SCHEMA_VERSION,
        'model_ref': model_ref_from_model(model),
        'skillname': str(_get(model, 'task_type') or SkillName.OBJECT_DETECTION.value),
        'framework': str(_get(model, 'framework') or _get(base_model, 'framework') or 'yolo'),
        'framework_version': _get(base_model, 'framework_version') or _get(onnx_meta, 'framework_version'),
        'dataset_version': _get(model, 'dataset_version'),
        'dict_version': source_meta.get('dict_version')
        or (_get(model, 'config_snapshot', {}) or {}).get('dict_version'),
        'base_model': _get(model, 'base_model') or _get(base_model, 'name'),
        'precision': precision,
        'created_at': source_meta.get('created_at') or _utcnow(),
        'published_at': source_meta.get('published_at'),
        'description': source_meta.get('description'),
        'tags': source_meta.get('tags') or [],
        'license': source_meta.get('license') or 'Apache-2.0',
        'gate_status': str(_get(model, 'gate_status', 'pending') or 'pending'),
        'lifecycle': _get(model, 'lifecycle', 'candidate'),
        'source': {
            'platform': 'aoi-train',
            'train_job_id': _get(train_job, 'id') or source_meta.get('train_job_id'),
            'created_by': _get(train_job, 'created_by') or _get(model, 'created_by') or source_meta.get('created_by'),
            'git_commit': source_meta.get('git_commit') or os.environ.get('GIT_COMMIT') or '',
        },
        'onnx': onnx,
        'classes': classes,
        'postprocess': dict(DEFAULT_POSTPROCESS),
        'tiling': {
            'enabled': bool(tiling_params.get('enabled', True)),
            'recommended_tile_size': int(tiling_params.get('size') or params.get('imgsz') or 1280),
            'overlap': float(tiling_params.get('overlap', 0.2)),
            'min_tile_size': 640,
            'edge_handling': 'pad',
            'batch_tiles': 4,
            'max_tiles': 64,
        },
        'thresholds': {
            'default': {'recheck_min': 0.50, 'auto_min': 0.90},
            'high_risk_force_recheck': True,
            'low_score_force_manual': 0.10,
        },
        'metrics': metrics,
        'benchmark': source_meta.get('benchmark'),
        'training': training,
        'requires': {
            'skillname': '>=0.1.0',
            'pipeline_core': '>=0.1.0',
            'schema_version': '>=1',
            'onnxruntime': '>=1.18',
            'cuda': None,
            'vram_gb': 4,
        },
        # 二期预留：字段位先占住，MVP 一律 null/{}
        'signature': None,
        'sbom_ref': None,
        'golden_summary': None,
        'calibration': None,
        'quantization': None,
        'extensions': {},
    }


def dump_model_yaml(doc: Mapping[str, Any]) -> str:
    """按跨平台契约固定字段顺序 dump YAML（``sort_keys=False``）。"""
    return yaml.safe_dump(dict(doc), sort_keys=False, allow_unicode=True)


def validate_model_yaml(doc: Any) -> list[str]:
    """校验 ``model.yaml``（A 侧子集：跨平台契约 §2.3 规则 1–8）；返回错误字符串列表。"""
    errors: list[str] = []
    if not isinstance(doc, Mapping):
        return ['model.yaml must be a mapping']

    for key in REQUIRED_TOP_LEVEL:
        if doc.get(key) in (None, ''):
            errors.append(f'{key}: required')

    if doc.get('schema_version') != SCHEMA_VERSION:
        errors.append(f'schema_version: unsupported value {doc.get("schema_version")!r} (expected {SCHEMA_VERSION})')

    if doc.get('skillname') not in {skill.value for skill in SkillName}:
        errors.append(f'skillname: unknown value {doc.get("skillname")!r}')

    try:
        parse_model_ref(doc.get('model_ref'))
    except ValueError as exc:
        errors.append(f'model_ref: {exc}')

    if doc.get('precision') not in ('fp32', 'fp16', 'int8'):
        errors.append(f'precision: invalid value {doc.get("precision")!r}')

    onnx = doc.get('onnx')
    if not isinstance(onnx, Mapping):
        errors.append('onnx: required mapping')
        onnx = {}
    for key in REQUIRED_ONNX:
        if onnx.get(key) in (None, ''):
            errors.append(f'onnx.{key}: required')
    sha256 = onnx.get('sha256')
    if sha256 and not _SHA256_RE.fullmatch(str(sha256)):
        errors.append('onnx.sha256: must be 64 hex chars')
    onnx_input = onnx.get('input') if isinstance(onnx.get('input'), Mapping) else {}
    onnx_output = onnx.get('output') if isinstance(onnx.get('output'), Mapping) else {}
    for key in REQUIRED_ONNX_INPUT:
        if onnx_input.get(key) in (None, ''):
            errors.append(f'onnx.input.{key}: required')
    for key in REQUIRED_ONNX_OUTPUT:
        if onnx_output.get(key) in (None, ''):
            errors.append(f'onnx.output.{key}: required')

    classes = doc.get('classes')
    if not isinstance(classes, list) or not classes:
        errors.append('classes: non-empty list required')
        classes = []

    codes: list[str] = []
    indexes: list[int] = []
    for position, entry in enumerate(classes):
        if not isinstance(entry, Mapping):
            errors.append(f'classes[{position}]: must be a mapping')
            continue
        for key in REQUIRED_CLASS_FIELDS:
            if entry.get(key) in (None, ''):
                errors.append(f'classes[{position}].{key}: required')
        code = entry.get('code')
        if code is not None:
            if not is_valid_fault_code(code):
                errors.append(f'classes[{position}].code: invalid fault code {code!r}')
            else:
                codes.append(str(code))
        index = entry.get('index')
        if isinstance(index, int) and not isinstance(index, bool):
            indexes.append(index)
        else:
            errors.append(f'classes[{position}].index: must be int')
        risk_level = entry.get('risk_level')
        if risk_level not in (1, 2, 3):
            errors.append(f'classes[{position}].risk_level: must be 1/2/3, got {risk_level!r}')
        recommended = entry.get('recommended')
        if not isinstance(recommended, Mapping):
            errors.append(f'classes[{position}].recommended: must be a mapping with recheck_min/auto_min')
        else:
            recheck_min = recommended.get('recheck_min')
            auto_min = recommended.get('auto_min')
            if not (
                isinstance(recheck_min, (int, float))
                and isinstance(auto_min, (int, float))
                and 0 < recheck_min < auto_min < 1
            ):
                errors.append(
                    f'classes[{position}].recommended: expected 0 < recheck_min < auto_min < 1, '
                    f'got {recheck_min!r}/{auto_min!r}'
                )

    if len(codes) != len(set(codes)):
        errors.append('classes[].code: duplicated')
    if len(indexes) != len(set(indexes)):
        errors.append('classes[].index: duplicated')
    elif indexes and indexes != list(range(len(indexes))):
        errors.append('classes[].index: must be unique and continuous starting at 0')

    if classes:
        num_classes = onnx_output.get('num_classes')
        output_shape = onnx_output.get('shape')
        if isinstance(num_classes, int) and num_classes != len(classes):
            errors.append(f'onnx.output.num_classes: {num_classes} != len(classes) {len(classes)}')
        if isinstance(output_shape, list) and len(output_shape) == 3:
            expected = len(classes)
            # YOLOv8: [1, 4+nc, anchors]（无 objectness）；部分导出带 objectness: 5+nc
            if output_shape[1] not in (expected, 4 + expected, 5 + expected):
                errors.append(
                    f'onnx.output.shape: class dimension {output_shape[1]} inconsistent with len(classes)={expected}'
                )

    return errors
