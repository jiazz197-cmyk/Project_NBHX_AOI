"""``skillname``：AOI 双平台共享词汇表（零三方依赖）。

全量 re-export，消费方统一 ``from skillname import ...``。
"""

from .codes import (
    FAULT_CODE_DEFAULT_PREFIX,
    FAULT_CODE_MAX_INDEX,
    FAULT_CODE_MAX_LENGTH,
    FAULT_CODE_MIN_INDEX,
    FAULT_CODE_PALETTE,
    FAULT_CODE_PATTERN,
    FAULT_CODE_PREFIX_MAX_LENGTH,
    FAULT_CODE_RE,
    color_for_index,
    fault_code_index,
    format_fault_code,
    is_valid_fault_code,
)
from .enums import (
    SKILL_TO_LS_CONTROL,
    DatasetSubset,
    ModelLifecycle,
    SkillName,
    Verdict,
    ls_control_for,
)
from .model_ref import (
    MODEL_PRECISIONS,
    MODEL_REF_PATTERN,
    MODEL_REF_RE,
    ModelRef,
    format_model_ref,
    image_tag_from_model_ref,
    parse_model_ref,
)

__version__ = '0.1.0'

__all__ = [
    '__version__',
    # enums
    'SkillName',
    'SKILL_TO_LS_CONTROL',
    'ls_control_for',
    'ModelLifecycle',
    'DatasetSubset',
    'Verdict',
    # codes
    'FAULT_CODE_PATTERN',
    'FAULT_CODE_RE',
    'FAULT_CODE_MIN_INDEX',
    'FAULT_CODE_MAX_INDEX',
    'FAULT_CODE_MAX_LENGTH',
    'FAULT_CODE_PREFIX_MAX_LENGTH',
    'FAULT_CODE_DEFAULT_PREFIX',
    'FAULT_CODE_PALETTE',
    'is_valid_fault_code',
    'format_fault_code',
    'fault_code_index',
    'color_for_index',
    # model_ref
    'MODEL_REF_PATTERN',
    'MODEL_REF_RE',
    'MODEL_PRECISIONS',
    'ModelRef',
    'parse_model_ref',
    'format_model_ref',
    'image_tag_from_model_ref',
]
