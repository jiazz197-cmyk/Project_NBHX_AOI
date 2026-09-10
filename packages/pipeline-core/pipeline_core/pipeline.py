"""
推理主流程 —— 对齐 P0 骨架设计 §4.2 与平台B契约 §4.1

run(): 切片 → 推理 → 合并 → 判定 的完整链路
"""

import time
from typing import Mapping
import numpy as np
from pipeline_core.types import DetectResult, InspectConfig, DetectBox
from pipeline_core.runtime import RuntimeModel
from pipeline_core.tiling import slice_image, box_to_global
from pipeline_core.merge import merge_across_tiles
from pipeline_core.verdict import decide_verdict


def run(
    image: np.ndarray,
    cfg: InspectConfig,
    models: Mapping[str, RuntimeModel],
) -> DetectResult:
    """
    执行完整推理链路。

    流程：
    1. 切片: slice_image(image, cfg.tile_size, cfg.overlap)
    2. 按 model_ref 分组对象，分别推理
    3. 坐标转换: box_to_global
    4. 跨切片 NMS 合并: merge_across_tiles
    5. 三档判定: decide_verdict

    Args:
        image: 输入图像 (H, W, C) numpy array
        cfg: 检测配置
        models: model_ref → RuntimeModel 映射

    Returns:
        DetectResult 包含检测框、判定结果、切片元信息
    """
    t0 = time.time()

    # 1. 切片
    tiles = slice_image(image, cfg.tile_size, cfg.overlap)

    # 2. 按 model_ref 分组对象
    model_groups: dict[str, list] = {}
    for obj in cfg.objects:
        model_groups.setdefault(obj.model_ref, []).append(obj)

    all_boxes: list[DetectBox] = []

    # 3. 对每个模型分别推理
    for model_ref, objects in model_groups.items():
        model = models.get(model_ref)
        if model is None:
            continue

        # 收集该模型负责的 class_id 集合
        class_ids: set[int] = set()
        code_map: dict[int, str] = {}
        for obj in objects:
            for cls_id, code in obj.class_map.items():
                class_ids.add(cls_id)
                code_map[cls_id] = code

        # 推理
        raw_results = model.infer([t.image for t in tiles])

        # 4. 坐标转换 + 过滤
        for tile, raw_boxes in zip(tiles, raw_results):
            for raw_box in raw_boxes:
                x1, y1, x2, y2, conf, cls_id = raw_box
                # 只保留该模型负责的类别
                if cls_id not in class_ids:
                    continue
                code = code_map.get(cls_id, f"unknown_{cls_id}")
                box = DetectBox(
                    xyxy=(float(x1), float(y1), float(x2), float(y2)),
                    class_id=int(cls_id),
                    object_code=code,
                    score=float(conf),
                    model_ref=model_ref,
                )
                global_box = box_to_global(box, tile.offset_x, tile.offset_y)
                all_boxes.append(global_box)

    # 5. NMS 合并
    merged_boxes = merge_across_tiles(all_boxes)

    # 6. 三档判定
    verdict, reasons = decide_verdict(merged_boxes, cfg.objects)

    elapsed_ms = int((time.time() - t0) * 1000)

    return DetectResult(
        boxes=merged_boxes,
        tiling_meta={
            "tile_size": cfg.tile_size,
            "overlap": cfg.overlap,
            "tiles": len(tiles),
            "ms": elapsed_ms,
        },
        verdict=verdict,
        verdict_reasons=reasons,
    )