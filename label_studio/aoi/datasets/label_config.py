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
``code``（必填，``<object>_<fault_type>_NN``，如 ``panel_scratch_01``）、``index``（可选，0-based，缺省＝列表位置；
一旦显式给出则必须唯一且**连续 0..n-1**，保证与 ``classes.txt`` / ``model.yaml`` 的类别序一致）、
``color``（可选，缺省 ``skillname.color_for_index(index)``）、``name_cn``（可选，展示名）。

展示名与结果值分离（D5 收尾 #2）
--------------------------------
标注页此前只显示 code（``object_fault_type_11``），标注员看到的全是编号。现在渲染为
``<Label value="code" html="划伤" background="…"/>``：``value`` 仍是 code（结果值、导出、
``class_map``、B 侧契约全部不变），``html`` 只影响**按钮/区域上的展示文本**，由 LSF 原生
``html`` 属性消费（``tags/control/Label.jsx``）。

**不可改用 ``alias``**：LSF ``SelectedModel.selectedValues()`` 是 ``alias ? alias : value``，
设 alias 会把标注结果值写成中文名，直接破坏 code 契约（已实测确认）。
"""

from __future__ import annotations

from html import escape
from typing import Any, Iterable

from aoi.common.errors import CODE_UNPROCESSABLE, AoiError
from skillname import SkillName, color_for_index, is_valid_fault_code, ls_control_for

__all__ = ['normalize_defects', 'render_label_config', 'snapshot_from_defects', 'defects_from_snapshot']

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
    """渲染 label config XML（golden fixture：``tests/contracts/fixtures/label_config_expected.xml``）。

    ``html`` 属性＝中文展示名（缺失则退回只渲染 ``value``，兼容无 name_cn 的旧快照）。
    """
    normalized = normalize_defects(defects)
    parts = [
        '<View>',
        f'<Image name="{IMAGE_NAME}" value="$image"/>',
        f'<{LS_CONTROL} name="{LABEL_NAME}" toName="{IMAGE_NAME}">',
    ]
    for entry in normalized:
        code = escape(entry['code'], quote=True)
        color = escape(entry['color'], quote=True)
        name_cn = entry.get('name_cn')
        display = f' html="{escape(str(name_cn), quote=True)}"' if name_cn else ''
        parts.append(f'<Label value="{code}"{display} background="{color}"/>')
    parts.append(f'</{LS_CONTROL}>')
    parts.append('</View>')
    return ''.join(parts)


def snapshot_from_defects(defects: Iterable[Any] | None) -> dict[str, Any]:
    """生成 ``defect_dict_version.snapshot``：``{labels:{code:{index,color,name_cn,risk_level}}}``。

    快照必须自带 ``name_cn``：数据集建项目／发布重同步都从快照渲染 label config，
    旧快照（只有 index/color）会丢中文名（``defects_from_snapshot`` 会回退查当前字典兜底）。
    """
    normalized = normalize_defects(defects)
    return {
        'labels': {
            entry['code']: {
                'index': entry['index'],
                'color': entry['color'],
                'name_cn': entry.get('name_cn'),
                'risk_level': entry.get('risk_level'),
            }
            for entry in normalized
        }
    }


def defects_from_snapshot(
    snapshot: dict[str, Any] | None, name_lookup: dict[str, Any] | None = None
) -> list[dict[str, Any]]:
    """从字典发布快照还原 defects（按 ``index`` 排序），供模板渲染与发布历史展示。

    ``name_lookup``：``{code: {'name_cn':…, 'risk_level':…}}``（通常来自当前 ``DefectClass``），
    用于兜底旧快照缺失的展示名——**不改变 code/index**，只补展示字段。
    """
    labels = (snapshot or {}).get('labels') or {}
    lookup = name_lookup or {}
    defects: list[dict[str, Any]] = []
    for code, meta in labels.items():
        meta = meta or {}
        fallback = lookup.get(code) or {}
        if isinstance(fallback, dict):
            fallback_name = fallback.get('name_cn')
            fallback_risk = fallback.get('risk_level')
        else:  # 允许直接传模型对象
            fallback_name = getattr(fallback, 'name_cn', None)
            fallback_risk = getattr(fallback, 'risk_level', None)
        defects.append(
            {
                'code': code,
                'index': meta.get('index'),
                'color': meta.get('color'),
                'name_cn': meta.get('name_cn') or fallback_name,
                'risk_level': meta.get('risk_level') or fallback_risk,
            }
        )
    defects.sort(key=lambda item: item['index'] if item['index'] is not None else 0)
    return defects
