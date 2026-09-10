"""
数据类型定义 —— 对齐 P0 骨架设计 §4.2 签名

所有结构体均为 dataclass，框架无关，不进 ORM。
"""

from dataclasses import dataclass, field
from typing import Optional


@dataclass(frozen=True)
class DetectBox:
    """单个检测框"""
    xyxy: tuple[float, float, float, float]  # 左上右下坐标
    class_id: int                             # 模型输出类别索引
    object_code: str                          # 缺陷 code（如 object_fault_type_01）
    score: float                              # 置信度
    model_ref: str = ""                       # 模型引用（多模型时溯源）


@dataclass
class DetectResult:
    """单次推理完整结果"""
    boxes: list[DetectBox] = field(default_factory=list)
    tiling_meta: dict = field(default_factory=dict)  # {tile_size, overlap, tiles, ms}
    verdict: str = "manual"                           # auto_pass / recheck / manual
    verdict_reasons: list[str] = field(default_factory=list)


@dataclass
class ObjectSpec:
    """检测对象规格（来自工位模板或预标配置）"""
    code: str                        # 缺陷 code
    model_ref: str                   # 绑定的模型
    class_map: dict[int, str]        # 模型类别索引 → 缺陷 code 映射
    recheck_min: float               # 复审阈值下限
    auto_min: float                  # 自动放行阈值下限
    risk_level: int = 1              # 风险等级：3=高 2=中 1=低
    critical: bool = False           # 是否关键缺陷（漏检不可接受，对应旧平台 criticalNgClassIds）


@dataclass
class InspectConfig:
    """检测配置（由工位模板或预标配置解析而来）"""
    objects: list[ObjectSpec] = field(default_factory=list)
    tile_size: int = 1280
    overlap: float = 0.2


@dataclass
class Tile:
    """切片信息"""
    image: "np.ndarray"              # 切片图像（numpy array）
    offset_x: int                    # 在原图中的 x 偏移
    offset_y: int                    # 在原图中的 y 偏移
    tile_w: int                      # 切片宽度
    tile_h: int                      # 切片高度


# 模型原始输出：每个框为 [x1, y1, x2, y2, conf, class_id]
RawBox = tuple[float, float, float, float, float, int]