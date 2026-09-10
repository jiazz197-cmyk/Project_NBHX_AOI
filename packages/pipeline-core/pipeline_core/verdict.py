"""
三档判定 —— 对齐 P0 骨架设计 §4.2 与平台B契约 §4.2

判定语义（宁错不漏）：
- auto_pass: 无框，或全框 score ≥ auto_min 且非关键缺陷
- recheck: 存在 recheck_min ≤ score < auto_min，或存在高风险/关键缺陷
- manual: 存在 score < recheck_min，或模型异常/超时

关键缺陷（critical=True）：无论分数多高都必须复审，不容漏检。
对齐旧平台 criticalNgClassIds 概念。
"""

from pipeline_core.types import DetectBox, ObjectSpec


def decide_verdict(
    boxes: list[DetectBox],
    cfg_objects: list[ObjectSpec],
) -> tuple[str, list[str]]:
    """
    根据检测框和配置判定结果。

    Args:
        boxes: 一张图的全部检测框
        cfg_objects: 检测配置中的对象规格列表

    Returns:
        (verdict, reasons) 判定结果与原因列表
    """
    reasons: list[str] = []

    if not boxes:
        return ("auto_pass", ["no_detection"])

    # 构建 code → ObjectSpec 映射
    spec_map: dict[str, ObjectSpec] = {obj.code: obj for obj in cfg_objects}

    has_manual = False
    has_recheck = False

    for box in boxes:
        spec = spec_map.get(box.object_code)
        if spec is None:
            # 未知类别 → 人工介入
            has_manual = True
            reasons.append(f"unknown_code:{box.object_code}")
            continue

        score = box.score

        # 关键缺陷：无论分数多高，必须复审（宁错不漏）
        if spec.critical:
            has_recheck = True
            reasons.append(f"critical:{box.object_code}:{score:.2f}")
            continue

        if score < spec.recheck_min:
            # 低于复审阈值 → 人工介入
            has_manual = True
            reasons.append(f"low_score:{box.object_code}:{score:.2f}")
        elif score < spec.auto_min:
            # 在复审区间 → 待复审
            has_recheck = True
            reasons.append(f"mid_score:{box.object_code}:{score:.2f}")
        elif spec.risk_level >= 3:
            # 高风险框即使高分也待复审
            has_recheck = True
            reasons.append(f"high_risk:{box.object_code}")

    if has_manual:
        return ("manual", reasons)
    if has_recheck:
        return ("recheck", reasons)
    return ("auto_pass", reasons)