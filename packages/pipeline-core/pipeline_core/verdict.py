"""
三档判定 —— 对齐 P0 骨架设计 §4.2 与平台B契约 §4.2。

判定语义（宁错不漏，不确定一律不自动放行）：
- auto_pass：无框，或全框 score >= auto_min 且风险等级低/中
- recheck：存在 recheck_min <= score < auto_min，或存在高风险框
- manual：存在 score < recheck_min，或未知 code / 模型异常

verdict_reasons 为短 token：mid_score / low_score / high_risk / unknown_code。
"""

from pipeline_core.types import DetectBox, InspectConfig, ObjectSpec


def decide_verdict(
    boxes: list[DetectBox],
    cfg: InspectConfig,
) -> tuple[str, list[str]]:
    """根据检测框与检测配置判定结果。"""
    reasons: list[str] = []

    if not boxes:
        return ("auto_pass", [])

    spec_map: dict[str, ObjectSpec] = {obj.code: obj for obj in cfg.objects}

    has_manual = False
    has_recheck = False

    for box in boxes:
        spec = spec_map.get(box.object_code)
        if spec is None:
            # 未知类别 → 人工介入
            has_manual = True
            reasons.append("unknown_code")
            continue

        score = box.score

        if score < spec.recheck_min:
            has_manual = True
            reasons.append("low_score")
        elif score < spec.auto_min:
            has_recheck = True
            reasons.append("mid_score")
        elif spec.risk_level >= 3:
            # 高风险框即使高分也待复审
            has_recheck = True
            reasons.append("high_risk")

    reasons = list(dict.fromkeys(reasons))  # 去重、保序

    if has_manual:
        return ("manual", reasons)
    if has_recheck:
        return ("recheck", reasons)
    return ("auto_pass", reasons)