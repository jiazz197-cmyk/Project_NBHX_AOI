"""
推理运行时抽象 —— 对齐 P0 骨架设计 §4.2

RuntimeModel 是抽象基类，调用方（A/B）各自实现 OnnxRuntimeModel 适配器。
不进公共包：onnxruntime 依赖由调用方注入。
"""

from abc import ABC, abstractmethod
import numpy as np
from pipeline_core.types import RawBox


class RuntimeModel(ABC):
    """
    推理模型抽象基类。

    调用方需实现 infer 方法，返回模型原始输出框列表。
    每个切片返回一个 RawBox 列表。
    """

    @abstractmethod
    def infer(self, tiles: list[np.ndarray]) -> list[list[RawBox]]:
        """
        对多个切片执行推理。

        Args:
            tiles: 切片图像列表，每个为 numpy array (H, W, C)

        Returns:
            每个切片的检测框列表，RawBox = (x1, y1, x2, y2, conf, class_id)
        """
        ...