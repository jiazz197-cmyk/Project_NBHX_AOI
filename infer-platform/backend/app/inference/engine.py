"""推理引擎：切片 → 推理 → NMS 合并 → 三档判定。

计算逻辑复用共享包 pipeline-core（editable 安装）。
D3 用 StubRuntimeModel 装配跑通；OnnxRuntimeModel 在真实权重就绪后切换。
对齐 docs/contracts/平台B_接口与数据契约.md §4.1。
"""

from __future__ import annotations

from typing import Mapping

import numpy as np
from pipeline_core import run
from pipeline_core.runtime import RuntimeModel
from pipeline_core.stub import StubRuntimeModel
from pipeline_core.types import DetectResult, InspectConfig

from ..envelope import CODE_NOT_READY, BizError
from ..store import models as store_models


def build_models(model_refs: list[str]) -> Mapping[str, RuntimeModel]:
    """按 model_ref 构建运行时模型映射。

    D3 用 StubRuntimeModel（假 onnx 权重不可真加载）；真实权重就绪后换 OnnxRuntimeModel。
    """
    models: dict[str, RuntimeModel] = {}
    for ref in model_refs:
        row = store_models.get_model(ref)
        if row is None or row["status"] not in ("ready", "active"):
            raise BizError(503, CODE_NOT_READY, "模型未就绪")
        models[ref] = StubRuntimeModel(ref)
    return models


def run_inference(image: np.ndarray, cfg: InspectConfig) -> DetectResult:
    """执行完整推理链路（切片 → 推理 → 合并 → 判定）。"""
    model_refs = sorted({obj.model_ref for obj in cfg.objects})
    models = build_models(model_refs)
    return run(image, cfg, models)

