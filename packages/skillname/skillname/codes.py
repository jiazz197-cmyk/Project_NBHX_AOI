"""缺陷对象 code（``object_fault_type_XX``）与调色板约定。

契约：``docs/contracts/平台A_接口与数据契约.md`` §2.1；
``color`` 为预留字段，供 label config 与 ``model.yaml`` 展示使用。
"""

import re

__all__ = [
    'FAULT_CODE_PATTERN',
    'FAULT_CODE_RE',
    'FAULT_CODE_MIN_INDEX',
    'FAULT_CODE_MAX_INDEX',
    'FAULT_CODE_PALETTE',
    'is_valid_fault_code',
    'format_fault_code',
    'fault_code_index',
    'color_for_index',
]

#: ``object_fault_type_XX``，XX 为两位 **ASCII** 十进制数字（01~99；``00`` 非法）
FAULT_CODE_PATTERN = r'^object_fault_type_(?:0[1-9]|[1-9][0-9])$'
FAULT_CODE_RE = re.compile(FAULT_CODE_PATTERN, re.ASCII)

FAULT_CODE_MIN_INDEX = 1
FAULT_CODE_MAX_INDEX = 99

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
    """``code`` 是否严格匹配 ``^object_fault_type_(0[1-9]|[1-9][0-9])$``（ASCII，01~99）。"""
    return isinstance(code, str) and FAULT_CODE_RE.fullmatch(code) is not None


def format_fault_code(index: int) -> str:
    """把索引（1~99）格式化为 ``object_fault_type_XX``。"""
    if isinstance(index, bool) or not isinstance(index, int):
        raise TypeError(f'fault code index must be int, got {type(index).__name__}')
    if not FAULT_CODE_MIN_INDEX <= index <= FAULT_CODE_MAX_INDEX:
        raise ValueError(f'fault code index out of range [{FAULT_CODE_MIN_INDEX}, {FAULT_CODE_MAX_INDEX}]: {index}')
    return f'object_fault_type_{index:02d}'


def fault_code_index(code: str) -> int:
    """``object_fault_type_XX`` → 索引（int）；非法 code 抛 ``ValueError``。"""
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
