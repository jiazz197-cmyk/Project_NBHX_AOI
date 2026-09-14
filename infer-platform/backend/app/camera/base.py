"""相机抽象基类与工厂。

对齐 docs/contracts/平台B_接口与数据契约.md §3.3/§5：
  adapter ∈ {directory, gige}；source 为目录或设备地址。
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any


class Camera(ABC):
    @abstractmethod
    def capture(self) -> bytes:
        """软触发取一帧（原始字节）。"""

    @abstractmethod
    def snapshot(self) -> bytes:
        """最近一帧快照（原始字节）。"""


def build_camera(camera_config: Any) -> Camera | None:
    """按 camera_config 构建相机实例；无配置/未知 adapter 返回 None。"""
    if not isinstance(camera_config, dict):
        return None
    adapter = camera_config.get("adapter", "directory")
    if adapter == "directory":
        from .directory import DirectoryCamera
        return DirectoryCamera(camera_config.get("source", ""))
    if adapter == "gige":
        from .gige import GigeCamera
        return GigeCamera(camera_config.get("config"))
    return None

