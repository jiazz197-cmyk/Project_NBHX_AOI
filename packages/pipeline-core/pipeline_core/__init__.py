"""
pipeline-core —— AOI 推理内核（框架无关）

两个平台 A/B 共用：
- A 侧预标推理（Celery GPU worker）
- B 侧在线推理（产线工控机）

不依赖 onnxruntime —— 调用方各自提供 RuntimeModel 适配器。
"""

from pipeline_core.types import (
    DetectBox,
    DetectResult,
    ObjectSpec,
    InspectConfig,
    Tile,
    RawBox,
)
from pipeline_core.runtime import RuntimeModel
from pipeline_core.tiling import slice_image, box_to_global
from pipeline_core.merge import merge_across_tiles
from pipeline_core.verdict import decide_verdict
from pipeline_core.config import load_config
from pipeline_core.pipeline import run
from pipeline_core.stub import StubRuntimeModel

__all__ = [
    "DetectBox",
    "DetectResult",
    "ObjectSpec",
    "InspectConfig",
    "Tile",
    "RawBox",
    "RuntimeModel",
    "slice_image",
    "box_to_global",
    "merge_across_tiles",
    "decide_verdict",
    "load_config",
    "run",
    "StubRuntimeModel",
]