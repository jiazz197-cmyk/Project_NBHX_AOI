"""label config 生成（契约 §4.1；T2.2）。

把缺陷字典渲染为 LS 标注配置 XML：
``<View><Image name="image" value="$image"/><RectangleLabels name="defect" toName="image">…``
控件类型取自 ``skillname.ls_control_for(SkillName.OBJECT_DETECTION)``，**不硬编码副本**。

与 LS 原生预设模板的关系
-------------------------
- 结构完全遵循 LS 官方预设 ``annotation_templates/computer-vision/object-detection-with-bounding-boxes/config.yml``
  （``View/Image/RectangleLabels/Label``）；我们没有发明新的标注控件或协议，只动态填充字典
  的 code / color / index 顺序。
- 产出必须能通过 LS 自身解析器 ``core.label_config.validate_label_config``（契约测试
  ``test_label_config_passes_ls_native_validator`` 已断言）。
- 控件名 ``defect`` 是 AOI 域约定（与 ``aoi/prelabel`` ML backend fixture 的 ``from_name=defect``
  对齐）；LS 预设示例使用 ``name="label"``。**D2 裁定：保持 ``defect``**（见 plan §10）。

输入 ``defects`` 元素支持 dict 或对象，字段：
``code``（必填，``object_fault_type_XX``，01~99）、``index``（可选，0-based，缺省＝列表位置；
一旦显式给出则必须唯一且**连续 0..n-1**，保证与 ``classes.txt`` / ``model.yaml`` 的类别序一致）、
``color``（可选，缺省 ``skillname.color_for_index(index)``）。
"""

from __future__ import annotations

from html import escape
from typing import Any, Iterable

from aoi.common.errors import CODE_UNPROCESSABLE, AoiError
from skillname import SkillName, color_for_index, is_valid_fault_code, ls_control_for

__all__ = ['normalize_defects', 'render_label_config', 'snapshot_from_defects']

LS_CONTROL = ls_control_for(SkillName.OBJECT_DETECTION)  # "RectangleLabels"
LABEL_NAME = 'defect'
IMAGE_NAME = 'image'


def _field(value: Any, key: str, default: Any = None) -> Any:
    if isinstance(value, dict):
        return value.get(key, default)
    return getattr(value, key, default)


def normalize_defects(defects: Iterable[Any] | None) -> list[dict[str, Any]]:
    """校验并归一化缺陷列表；非法输入抛 ``AoiError(42200, fields=...)``。"""
    if defects is None:
        raise AoiError(CODE_UNPROCESSABLE, 'defects is required', fields={'defects': 'required'})
    if isinstance(defects, dict):
        defects = defects.get('defects')
    if not isinstance(defects, (list, tuple)):
        raise AoiError(CODE_UNPROCESSABLE, 'defects must be a list', fields={'defects': 'must be a list'})
    if not defects:
        raise AoiError(CODE_UNPROCESSABLE, 'defects must not be empty', fields={'defects': 'must not be empty'})

    normalized: list[dict[str, Any]] = []
    fields: dict[str, str] = {}
    seen_codes: set[str] = set()
    seen_indexes: set[int] = set()

    for position, item in enumerate(defects):
        code = _field(item, 'code')
        if not is_valid_fault_code(code):
            fields[f'defects[{position}].code'] = f'invalid fault code: {code!r}'
            continue
        if code in seen_codes:
            fields[f'defects[{position}].code'] = 'duplicated fault code'
            continue
        seen_codes.add(code)

        index = _field(item, 'index', None)
        if index is None:
            # 缺省 index = 列表位置（0-based），与 classes.txt / model.yaml 的枚举顺序一致；
            # 不用 fault_code_index(code)-1：字典不连续时（如仅 01/03）会与位置序错位。
            index = position
        if isinstance(index, bool) or not isinstance(index, int) or index < 0:
            fields[f'defects[{position}].index'] = 'index must be a non-negative int'
            continue
        if index in seen_indexes:
            fields[f'defects[{position}].index'] = 'duplicated index'
            continue
        seen_indexes.add(index)

        color = _field(item, 'color', None) or color_for_index(index)
        normalized.append(
            {
                'code': code,
                'index': index,
                'color': str(color),
                'name_cn': _field(item, 'name_cn', None),
                'risk_level': _field(item, 'risk_level', None),
            }
        )

    if fields:
        raise AoiError(CODE_UNPROCESSABLE, 'invalid defects', fields=fields)

    normalized.sort(key=lambda entry: entry['index'])
    # P1：index 必须连续 0..n-1，否则快照/classes.txt/model.yaml 的类别索引会互相错位
    expected = list(range(len(normalized)))
    if [entry['index'] for entry in normalized] != expected:
        raise AoiError(
            CODE_UNPROCESSABLE,
            'defects indexes must be contiguous from 0',
            fields={'defects': f'expected index sequence {expected}'},
        )
    return normalized


def render_label_config(defects: Iterable[Any] | None) -> str:
    """渲染 label config XML（golden fixture：``tests/contracts/fixtures/label_config_expected.xml``）。"""
    normalized = normalize_defects(defects)
    parts = [
        '<View>',
        f'<Image name="{IMAGE_NAME}" value="$image"/>',
        f'<{LS_CONTROL} name="{LABEL_NAME}" toName="{IMAGE_NAME}">',
    ]
    for entry in normalized:
        code = escape(entry['code'], quote=True)
        color = escape(entry['color'], quote=True)
        parts.append(f'<Label value="{code}" background="{color}"/>')
    parts.append(f'</{LS_CONTROL}>')
    parts.append('</View>')
    return ''.join(parts)


def snapshot_from_defects(defects: Iterable[Any] | None) -> dict[str, Any]:
    """生成 ``defect_dict_version.snapshot``：``{labels:{code:{index,color}}}``。"""
    normalized = normalize_defects(defects)
    return {'labels': {entry['code']: {'index': entry['index'], 'color': entry['color']} for entry in normalized}}
