"""
切片与坐标转换 —— 对齐 P0 骨架设计 §4.2

- slice_image: 将大图按 tile_size 切分为多个切片，带 overlap
- box_to_global: 将切片内坐标转为原图全局坐标
"""

import numpy as np
from pipeline_core.types import Tile, DetectBox


def slice_image(
    image: np.ndarray,
    tile_size: int = 1280,
    overlap: float = 0.2,
) -> list[Tile]:
    """
    将图像切分为多个重叠切片。

    Args:
        image: 输入图像 (H, W, C) numpy array
        tile_size: 切片边长（像素）
        overlap: 重叠比例（0~1）

    Returns:
        Tile 列表，每个包含切片图像和位置信息
    """
    h, w = image.shape[:2]
    stride = int(tile_size * (1 - overlap))
    tiles: list[Tile] = []

    y = 0
    while y < h:
        x = 0
        while x < w:
            # 计算实际切片边界（处理边缘）
            x_end = min(x + tile_size, w)
            y_end = min(y + tile_size, h)
            x_start = max(0, x_end - tile_size)
            y_start = max(0, y_end - tile_size)

            tile_img = image[y_start:y_end, x_start:x_end]

            tiles.append(Tile(
                image=tile_img,
                offset_x=x_start,
                offset_y=y_start,
                tile_w=x_end - x_start,
                tile_h=y_end - y_start,
            ))

            x += stride
        y += stride

    return tiles


def box_to_global(box: DetectBox, offset_x: int, offset_y: int) -> DetectBox:
    """
    将切片内检测框坐标转为原图全局坐标。

    Args:
        box: 切片内的检测框
        offset_x: 切片在原图中的 x 偏移
        offset_y: 切片在原图中的 y 偏移

    Returns:
        全局坐标的 DetectBox（新实例，原实例不变）
    """
    x1, y1, x2, y2 = box.xyxy
    return DetectBox(
        xyxy=(x1 + offset_x, y1 + offset_y, x2 + offset_x, y2 + offset_y),
        class_id=box.class_id,
        object_code=box.object_code,
        score=box.score,
        model_ref=box.model_ref,
    )