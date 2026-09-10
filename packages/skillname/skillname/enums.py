"""任务类型与状态枚举（AOI 双平台共享词汇表）。

权威定义：``docs/P0骨架设计_双平台.md`` §4.1、``docs/contracts/跨平台契约_A-B.md`` §2.3。
本模块**零三方依赖**，可被 A/B 两侧任意导入。

裁定（T1.2）：MVP 唯一 ``task_type = SkillName.OBJECT_DETECTION``；**禁止** import
``ml_models.SkillNames``（上游仅 TextClassification/NER，见 ``label_studio/ml_models/models.py``）。
"""

from enum import Enum

__all__ = [
    'SkillName',
    'SKILL_TO_LS_CONTROL',
    'ls_control_for',
    'ModelLifecycle',
    'DatasetSubset',
    'Verdict',
]


class _StrEnum(str, Enum):
    """Python 3.10 兼容的字符串枚举基类：``str(x)`` 返回枚举值本身。"""

    def __str__(self) -> str:  # pragma: no cover - trivial
        return str(self.value)

    def __format__(self, format_spec: str) -> str:  # pragma: no cover - trivial
        return format(str(self.value), format_spec)


class SkillName(_StrEnum):
    """AOI 任务类型（skillname）。

    MVP 唯一：``OBJECT_DETECTION`` → LS 控件 ``RectangleLabels``。
    ``IMAGE_CLASSIFICATION`` / ``IMAGE_SEGMENTATION`` 为预留枚举，不得在 MVP 使用。
    """

    OBJECT_DETECTION = 'ObjectDetection'
    IMAGE_CLASSIFICATION = 'ImageClassification'  # 预留
    IMAGE_SEGMENTATION = 'ImageSegmentation'  # 预留


#: skillname → Label Studio 控件类型（与 LS 1.x 实测一致，D2 复用验证日确认）
SKILL_TO_LS_CONTROL = {
    SkillName.OBJECT_DETECTION: 'RectangleLabels',
}


def ls_control_for(skill: SkillName | str) -> str:
    """返回 skillname 对应的 LS 控件类型；未知/预留 skill 抛 ``ValueError``。"""
    try:
        skill = SkillName(skill)
    except ValueError as exc:
        raise ValueError(f'unknown skillname: {skill!r}') from exc
    try:
        return SKILL_TO_LS_CONTROL[skill]
    except KeyError as exc:
        raise ValueError(f'skillname has no LS control mapping (reserved): {skill.value!r}') from exc


class ModelLifecycle(_StrEnum):
    """模型生命周期（``aoi_training.model.lifecycle``）。"""

    CANDIDATE = 'candidate'
    APPROVED = 'approved'
    PUBLISHED = 'published'
    RETIRED = 'retired'


class DatasetSubset(_StrEnum):
    """数据集子集（``aoi_datasets.dataset_item.subset``）。"""

    TRAIN = 'train'
    VAL = 'val'
    TEST = 'test'


class Verdict(_StrEnum):
    """初检判定（语义在 ``pipeline-core``）。"""

    AUTO_PASS = 'auto_pass'
    RECHECK = 'recheck'
    MANUAL = 'manual'
