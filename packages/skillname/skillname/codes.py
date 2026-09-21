"""缺陷对象 code（``<object>_<fault_type>_NN``）与调色板约定。

契约：``docs/contracts/平台A_接口与数据契约.md`` §2.1；
``color`` 为预留字段，供 label config 与 ``model.yaml`` 展示使用。

code 形态（D5 收尾第二轮放宽）
------------------------------
``^[a-z][a-z0-9_]{0,27}_(?:0[1-9]|[1-9][0-9])$``

- 前缀是**两段可变英文词**：``<object>_<fault_type>``（如 ``panel_scratch``、``glass_dent``），
  不再是写死的字面量 ``object_fault_type``——原写法只是模板占位符被当成了字面值。
- 后缀固定两位 ASCII 数字 01~99（``00`` 非法），是 code 自身的**编号**，**不是类别索引**：
  类别索引（``classes.txt`` / ``model.yaml.classes[].index`` / 调色板）一律由缺陷字典的
  显式 ``index`` 或列表顺序决定，与 code 后缀无关（历史实现即如此，见 ``label_config.py``）。
- 前缀 ≤ 28 字符 ⇒ code 总长 ≤ 31，落在 ``aoi_datasets.defect_class.code VARCHAR(32)`` 内。
- 放宽是**超集**：既有 ``object_fault_type_11`` 仍然合法，存量数据/快照/标注无需迁移。
"""

import re

__all__ = [
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
]

#: ``<object>_<fault_type>_NN``：前缀两段可变英文词（小写字母/数字/下划线），后缀 01~99（``00`` 非法）
FAULT_CODE_PATTERN = r'^[a-z][a-z0-9_]{0,27}_(?:0[1-9]|[1-9][0-9])$'
FAULT_CODE_RE = re.compile(FAULT_CODE_PATTERN, re.ASCII)

FAULT_CODE_MIN_INDEX = 1
FAULT_CODE_MAX_INDEX = 99

#: 前缀上限（28）与 code 总长上限（31）——对齐 ``defect_class.code VARCHAR(32)``
FAULT_CODE_PREFIX_MAX_LENGTH = 28
FAULT_CODE_MAX_LENGTH = FAULT_CODE_PREFIX_MAX_LENGTH + 1 + 2  # 31，留 1 字符余量

#: 历史默认前缀（T2.2 起的字面量写法；``format_fault_code`` 不传前缀时沿用）
FAULT_CODE_DEFAULT_PREFIX = 'object_fault_type'

#: 固定 8 色调色板（与前端展示 / label config 取色一致）
FAULT_CODE_PALETTE = (
    '#FF4D4F',
    '#FA8C16',
    '#FADB14',
    '#52C41A',
    '#13C2C2',
    '#1677FF',
    '#722ED1',
    '#EB2F96',
)


def is_valid_fault_code(code: object) -> bool:
    """``code`` 是否匹配 ``^[a-z][a-z0-9_]{0,27}_(0[1-9]|[1-9][0-9])$``（ASCII，后缀 01~99）。"""
    return isinstance(code, str) and FAULT_CODE_RE.fullmatch(code) is not None


def _check_prefix(prefix: object) -> str:
    if not isinstance(prefix, str) or not prefix:
        raise TypeError(f'fault code prefix must be a non-empty str, got {type(prefix).__name__}')
    if not re.fullmatch(r'[a-z][a-z0-9_]*', prefix, re.ASCII) or prefix.endswith('_'):
        raise ValueError(f'invalid fault code prefix: {prefix!r} (expected [a-z][a-z0-9_]*)')
    if len(prefix) > FAULT_CODE_PREFIX_MAX_LENGTH:
        raise ValueError(
            f'fault code prefix too long ({len(prefix)} > {FAULT_CODE_PREFIX_MAX_LENGTH}): {prefix!r}'
        )
    return prefix


def format_fault_code(index: int, prefix: str = FAULT_CODE_DEFAULT_PREFIX) -> str:
    """把编号（1~99）格式化为 ``{prefix}_XX``；``prefix`` 缺省沿用 ``object_fault_type``。

    ``prefix`` 即产品语义里的 ``<object>_<fault_type>``（如 ``panel_scratch``）。
    """
    if isinstance(index, bool) or not isinstance(index, int):
        raise TypeError(f'fault code index must be int, got {type(index).__name__}')
    if not FAULT_CODE_MIN_INDEX <= index <= FAULT_CODE_MAX_INDEX:
        raise ValueError(f'fault code index out of range [{FAULT_CODE_MIN_INDEX}, {FAULT_CODE_MAX_INDEX}]: {index}')
    return f'{_check_prefix(prefix)}_{index:02d}'


def fault_code_index(code: str) -> int:
    """``<object>_<fault_type>_XX`` → code 自身编号（int，1~99）；非法 code 抛 ``ValueError``。

    注意：这是 code 里的**编号**，不是类别索引——类别索引由缺陷字典顺序决定。
    """
    if not is_valid_fault_code(code):
        raise ValueError(f'invalid fault code: {code!r} (expected {FAULT_CODE_PATTERN})')
    return int(code[-2:])


def color_for_index(index: int) -> str:
    """按索引返回固定调色板颜色（0-based，循环使用 8 色）。"""
    if isinstance(index, bool) or not isinstance(index, int):
        raise TypeError(f'color index must be int, got {type(index).__name__}')
    if index < 0:
        raise ValueError(f'color index must be >= 0, got {index}')
    return FAULT_CODE_PALETTE[index % len(FAULT_CODE_PALETTE)]
