"""推理运行时适配器：OnnxRuntimeModel。

对齐 docs/P0骨架设计_双平台.md §4.3：调用方各自实现 RuntimeModel。
D3 空跑用 pipeline_core.StubRuntimeModel；本模块提供真实 ONNX 适配器（真实权重就绪后启用）。
"""

from __future__ import annotations

import numpy as np
from pipeline_core.runtime import RuntimeModel
from pipeline_core.types import RawBox


class OnnxRuntimeModel(RuntimeModel):
    """ONNX Runtime 适配器（FP32/FP16、CUDA/CPU）。

    provider 由 ONNX_PROVIDER 决定；输出格式按 model.yaml 的 onnx.output.format
    约定为 yolo_v8_xywh_conf_cls（[1, 6, N]：cx, cy, w, h, conf, class_id）。
    """

    def __init__(self, model_ref: str, model_path: str, provider: str = "cpu"):
        import onnxruntime as ort

        self._model_ref = model_ref
        if provider == "cuda":
            providers = ["CUDAExecutionProvider", "CPUExecutionProvider"]
        else:
            providers = ["CPUExecutionProvider"]
        self._session = ort.InferenceSession(model_path, providers=providers)
        self._input_name = self._session.get_inputs()[0].name

    def infer(self, tiles: list[np.ndarray]) -> list[list[RawBox]]:
        results: list[list[RawBox]] = []
        for tile in tiles:
            inp = tile.astype("float32").transpose(2, 0, 1)[None] / 255.0
            out = self._session.run(None, {self._input_name: inp})[0]  # (1, 6, N)
            boxes: list[RawBox] = []
            preds = out[0]
            for i in range(preds.shape[1]):
                cx, cy, w, h, conf, cls_id = preds[:, i]
                boxes.append((
                    float(cx - w / 2), float(cy - h / 2),
                    float(cx + w / 2), float(cy + h / 2),
                    float(conf), int(cls_id),
                ))
            results.append(boxes)
        return results

