"""``model_ref``（模型注册版本号）与镜像 tag 规范。

格式：``{seq}-{framework}@ds{dataset_version}``，如 ``3-yolo@ds1``。
镜像 tag：``skillname.image_tag_from_model_ref`` → ``3-yolo-ds1``；非 fp32 追加 ``-{precision}``。
"""

from __future__ import annotations

import re
from dataclasses import dataclass

__all__ = [
    'MODEL_REF_PATTERN',
    'MODEL_REF_RE',
    'MODEL_PRECISIONS',
    'ModelRef',
    'parse_model_ref',
    'format_model_ref',
    'image_tag_from_model_ref',
]

#: 严格格式：``^([0-9]+)-([a-z0-9._-]+)@ds([0-9]+)$``（**ASCII**，镜像 tag 有字符集限制）
MODEL_REF_PATTERN = r'^([0-9]+)-([a-z0-9._-]+)@ds([0-9]+)$'
MODEL_REF_RE = re.compile(MODEL_REF_PATTERN, re.ASCII)

#: 允许的精度后缀（跨平台契约 §2.2/§2.3）
MODEL_PRECISIONS = ('fp32', 'fp16', 'int8')


@dataclass(frozen=True)
class ModelRef:
    """``model_ref`` 的结构化表示（frozen dataclass）。"""

    seq: int
    framework: str
    dataset_version: str

    def __post_init__(self) -> None:
        if isinstance(self.seq, bool) or not isinstance(self.seq, int) or self.seq < 0:
            raise ValueError(f'ModelRef.seq must be a non-negative int, got {self.seq!r}')
        if not isinstance(self.framework, str) or not self.framework:
            raise ValueError(f'ModelRef.framework must be a non-empty str, got {self.framework!r}')
        if not re.fullmatch(r'[a-z0-9._-]+', self.framework):
            raise ValueError(f'ModelRef.framework has invalid characters: {self.framework!r}')
        if not isinstance(self.dataset_version, str) or not re.fullmatch(r'[0-9]+', self.dataset_version, re.ASCII):
            raise ValueError(f'ModelRef.dataset_version must be ASCII digits, got {self.dataset_version!r}')

    def __str__(self) -> str:
        return format_model_ref(self)


def parse_model_ref(value: str | ModelRef) -> ModelRef:
    """解析 ``model_ref`` 字符串；非法输入抛 ``ValueError``。"""
    if isinstance(value, ModelRef):
        return value
    if not isinstance(value, str):
        raise ValueError(f'model_ref must be str or ModelRef, got {type(value).__name__}')
    match = MODEL_REF_RE.fullmatch(value)
    if match is None:
        raise ValueError(f'invalid model_ref: {value!r} (expected {MODEL_REF_PATTERN})')
    seq, framework, dataset_version = match.groups()
    return ModelRef(seq=int(seq), framework=framework, dataset_version=dataset_version)


def format_model_ref(ref: ModelRef | str) -> str:
    """``ModelRef``/字符串 → 规范 ``model_ref`` 字符串。"""
    if isinstance(ref, str):
        ref = parse_model_ref(ref)
    if not isinstance(ref, ModelRef):
        raise ValueError(f'model_ref must be ModelRef or str, got {type(ref).__name__}')
    return f'{ref.seq}-{ref.framework}@ds{ref.dataset_version}'


def image_tag_from_model_ref(ref: ModelRef | str, precision: str | None = None) -> str:
    """``model_ref`` → 镜像 tag。

    ``3-yolo@ds1`` → ``3-yolo-ds1``；``precision`` 为空或 ``fp32`` 时不加后缀，
    非 fp32（fp16/int8）追加 ``-{precision}``。
    """
    parsed = parse_model_ref(ref)
    tag = f'{parsed.seq}-{parsed.framework}-ds{parsed.dataset_version}'
    if precision is None:
        return tag
    if not isinstance(precision, str) or precision not in MODEL_PRECISIONS:
        raise ValueError(f'precision must be one of {MODEL_PRECISIONS}, got {precision!r}')
    if precision == 'fp32':
        return tag
    return f'{tag}-{precision}'
