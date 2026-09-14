"""目录相机实现（读取本地图片目录）。

用于开发/回放/离线验证，不依赖真实硬件。
对齐 docs/contracts/平台B_接口与数据契约.md §5。
"""

from __future__ import annotations

from pathlib import Path

from .base import Camera

_IMAGE_SUFFIXES = (".jpg", ".jpeg", ".png")


class DirectoryCamera(Camera):
    """按文件名排序循环取图；capture 前进一位，snapshot 取当前帧。"""

    def __init__(self, source: str):
        self._source = Path(source)
        self._index = 0

    def _files(self) -> list[Path]:
        if not self._source.is_dir():
            return []
        return sorted(p for p in self._source.iterdir() if p.suffix.lower() in _IMAGE_SUFFIXES)

    def capture(self) -> bytes:
        files = self._files()
        if not files:
            raise RuntimeError(f"目录无图片：{self._source}")
        path = files[self._index % len(files)]
        self._index += 1
        return path.read_bytes()

    def snapshot(self) -> bytes:
        files = self._files()
        if not files:
            raise RuntimeError(f"目录无图片：{self._source}")
        return files[max(self._index - 1, 0) % len(files)].read_bytes()

