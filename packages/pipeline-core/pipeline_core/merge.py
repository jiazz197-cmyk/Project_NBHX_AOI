"""
NMS 合并 —— 对齐 P0 骨架设计 §4.2

merge_across_tiles: 跨切片去重合并，使用 IoU 阈值
"""

import numpy as np
from pipeline_core.types import DetectBox


def _compute_iou(box1: DetectBox, box2: DetectBox) -> float:
    """计算两个框的 IoU"""
    x1 = max(box1.xyxy[0], box2.xyxy[0])
    y1 = max(box1.xyxy[1], box2.xyxy[1])
    x2 = min(box1.xyxy[2], box2.xyxy[2])
    y2 = min(box1.xyxy[3], box2.xyxy[3])

    inter_w = max(0, x2 - x1)
    inter_h = max(0, y2 - y1)
    inter_area = inter_w * inter_h

    area1 = (box1.xyxy[2] - box1.xyxy[0]) * (box1.xyxy[3] - box1.xyxy[1])
    area2 = (box2.xyxy[2] - box2.xyxy[0]) * (box2.xyxy[3] - box2.xyxy[1])
    union_area = area1 + area2 - inter_area

    if union_area <= 0:
        return 0.0
    return inter_area / union_area


def merge_across_tiles(
    boxes: list[DetectBox],
    iou_thr: float = 0.5,
) -> list[DetectBox]:
    """
    跨切片 NMS 合并。

    按置信度降序排列，保留高分框，抑制与其 IoU > iou_thr 的低分框。
    同类别（class_id）之间才进行 NMS。

    Args:
        boxes: 所有切片的检测框（已转为全局坐标）
        iou_thr: IoU 阈值

    Returns:
        NMS 后的检测框列表
    """
    if not boxes:
        return []

    # 按 score 降序
    sorted_boxes = sorted(boxes, key=lambda b: b.score, reverse=True)
    kept: list[DetectBox] = []

    for box in sorted_boxes:
        suppressed = False
        for kept_box in kept:
            # 只对同一缺陷类别（object_code）做 NMS：跨切片/跨模型去重；
            # 不同缺陷类别不互相抑制（多模型同 class_id 不同 code 时避免误杀）
            if box.object_code == kept_box.object_code:
                iou = _compute_iou(box, kept_box)
                if iou > iou_thr:
                    suppressed = True
                    break
        if not suppressed:
            kept.append(box)

    return kept