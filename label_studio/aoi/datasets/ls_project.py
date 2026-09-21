"""AOI 标注项目模板（契约 §4.1）。

把「AOI 的 LS 项目长什么样」固化为常量 + 纯函数：D4 只交付模板与单测，真实创建在
D6「标注项目创建」接入（届时 `dataset.ls_project_id` 改由服务端生成）。

- 取值直接引用上游 `projects.models.Project` 上的常量（`SEQUENCE` / `SkipQueue`），不硬编码副本；
- 模板字段**全部显式钉死**，不依赖上游默认值漂移；
- **不含任何 review 设置**：LS OSS 无 Review 流（契约 §10.1）。
"""

from __future__ import annotations

from typing import Any, Iterable

from aoi.datasets.label_config import render_label_config
from projects.models import Project

__all__ = ['AOI_PROJECT_DEFAULTS', 'project_title', 'project_description', 'build_project_kwargs']

#: 标注指引（契约 §4.1；文案可替换，不改结构）
EXPERT_INSTRUCTION = (
    '<b>标注规范</b><br/>'
    '1. 按缺陷字典选择标签，框选缺陷的最小外接矩形，边界紧贴缺陷边缘；<br/>'
    '2. 同一缺陷只标注一次；相邻但独立的缺陷分别标注；<br/>'
    '3. 无缺陷的 OK 图必须提交<b>空标注</b>（不画任何框），用于训练负样本；<br/>'
    '4. 拿不准的按最接近类别标注，交由复审环节判定；<br/>'
    '5. 提交前确认图片无旋转、无缩放异常。'
)

#: 与 LS ``Project`` 字段同名的模板常量（label_config/title/description 由函数生成）
AOI_PROJECT_DEFAULTS: dict[str, Any] = {
    'color': '#FFFFFF',  # 不使用品牌色
    'maximum_annotations': 1,  # 一人一图；质量靠三桶复审而非重叠一致性
    'show_overlap_first': False,
    'sampling': Project.SEQUENCE,
    'skip_queue': Project.SkipQueue.REQUEUE_FOR_OTHERS,
    'show_skip_button': True,
    'expert_instruction': EXPERT_INSTRUCTION,
    'show_instruction': True,
    'show_collab_predictions': True,  # 预标结果需可见
    'evaluate_predictions_automatically': False,  # 是否接受预测由人工决定
    'reveal_preannotations_interactively': True,
    'enable_empty_annotation': True,  # OK 图必须能提交空标注（YOLO 负样本）
    'show_annotation_history': False,
    'show_ground_truth_first': False,
    'min_annotations_to_start_training': 0,
}


def project_title(dataset_name: str) -> str:
    """项目标题＝数据集名（命名规范）。"""
    return dataset_name


def project_description(dataset_name: str, version: str, dict_version: str | None) -> str:
    """项目描述携带数据集/版本/字典版本，便于在 LS 原生页面追溯来源。"""
    return f'AOI 数据集 {dataset_name} · 版本 {version} · 缺陷字典 {dict_version or "-"}'


def build_project_kwargs(
    *,
    dataset_name: str,
    version: str,
    dict_version: str | None,
    defects: Iterable[Any] | None,
) -> dict[str, Any]:
    """生成创建 LS 项目所需的完整字段（D6 直接 `Project.objects.create(**kwargs)`）。"""
    return {
        **AOI_PROJECT_DEFAULTS,
        'title': project_title(dataset_name),
        'description': project_description(dataset_name, version, dict_version),
        'label_config': render_label_config(defects),
    }
