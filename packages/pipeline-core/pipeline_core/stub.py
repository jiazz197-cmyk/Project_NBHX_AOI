"""
StubRuntimeModel —— 确定性假框模型，供 P0 测试与前端开发使用

对齐 P0 骨架设计 §4.2
"""

import numpy as np
from pipeline_core.runtime import RuntimeModel
from pipeline_core.types import RawBox


class StubRuntimeModel(RuntimeModel):
    """
    假推理模型，返回确定性假框。

    用于：
    - 前端开发时无真实模型
    - 契约测试中验证 pipeline 链路
    - D3 空跑验收

    每个切片固定返回一个假框（左上角 100x100 区域，置信度 0.85，类别 0）
    """

    def __init__(self, model_ref: str = "stub@ds0"):
        self._model_ref = model_ref

    def infer(self, tiles: list[np.ndarray]) -> list[list[RawBox]]:
        """
        返回确定性假框，每个切片一个。

        Args:
            tiles: 切片图像列表

        Returns:
            每个切片一个假框: (10, 10, 110, 110, 0.85, 0)
        """
        return [
            [(10.0, 10.0, 110.0, 110.0, 0.85, 0)]
            for _ in tiles
        ]