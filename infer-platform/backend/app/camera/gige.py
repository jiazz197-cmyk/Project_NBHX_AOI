"""GigE 相机实现（产线实际硬件）。

D3 空跑不接硬件；本类仅占位，capture/snapshot 抛 NotImplementedError。
对齐 docs/contracts/平台B_接口与数据契约.md §5。
"""

from __future__ import annotations

from typing import Any

from .base import Camera


class GigeCamera(Camera):
    def __init__(self, config: dict[str, Any] | None = None):
        self._config = config or {}

    def capture(self) -> bytes:
        raise NotImplementedError("GigE 相机 D3 后实现")

    def snapshot(self) -> bytes:
        raise NotImplementedError("GigE 相机 D3 后实现")

