"""pipeline-core 契约测试 —— 对齐 P0 骨架设计 §4.2 / 平台B契约 §4.2/§4.3。

用测试把签名与"宁错不漏"语义锁死：
  - box_to_global(box, offset) 签名
  - merge_across_tiles 只按 object_code 抑制
  - decide_verdict(boxes, cfg) 语义与短 token reasons
  - load_config 结构校验（code/thresholds/class_map/tile/overlap）
  - run 缺失模型必须报错（不得静默 auto_pass）
  - StubRuntimeModel 默认 model_ref 符合 skillname 格式
"""

import numpy as np
import pytest

from pipeline_core.config import load_config
from pipeline_core.merge import merge_across_tiles
from pipeline_core.pipeline import run
from pipeline_core.stub import StubRuntimeModel
from pipeline_core.tiling import box_to_global, slice_image
from pipeline_core.types import DetectBox, InspectConfig, ObjectSpec
from pipeline_core.verdict import decide_verdict
from skillname import parse_model_ref


TEMPLATE_JSON = """{
  "template_version": 3,
  "model_ref": "3-yolo@ds1",
  "skillname": "ObjectDetection",
  "tile_size": 1280,
  "overlap": 0.2,
  "objects": [
    {"code": "object_fault_type_01", "class_map": {"0": "object_fault_type_01"},
     "thresholds": {"recheck_min": 0.60, "auto_min": 0.90}, "risk_level": 3},
    {"code": "object_fault_type_02", "class_map": {"1": "object_fault_type_02"},
     "thresholds": {"recheck_min": 0.55, "auto_min": 0.88}, "risk_level": 2}
  ]
}"""


def _spec(code="object_fault_type_01", model_ref="1-m@ds1", class_id=0,
          recheck_min=0.5, auto_min=0.9, risk_level=1):
    return ObjectSpec(code=code, model_ref=model_ref,
                      class_map={class_id: code},
                      recheck_min=recheck_min, auto_min=auto_min, risk_level=risk_level)


def _box(code="object_fault_type_01", score=0.8, xyxy=(10, 10, 100, 100), class_id=0):
    return DetectBox(xyxy=xyxy, class_id=class_id, object_code=code,
                     score=score, model_ref="1-m@ds1")


# ---------- box_to_global ----------

def test_box_to_global():
    b = _box(xyxy=(10, 10, 20, 20))
    g = box_to_global(b, (100, 200))
    assert g.xyxy == (110, 210, 120, 220)
    assert b.xyxy == (10, 10, 20, 20)  # 原实例不变


# ---------- merge_across_tiles ----------

def test_merge_same_object_code_suppressed():
    a = _box(code="object_fault_type_01", score=0.9, xyxy=(0, 0, 100, 100))
    b = _box(code="object_fault_type_01", score=0.8, xyxy=(5, 5, 105, 105))
    merged = merge_across_tiles([b, a])
    assert len(merged) == 1
    assert merged[0].score == 0.9


def test_merge_different_object_code_not_suppressed():
    a = _box(code="object_fault_type_01", score=0.9, xyxy=(0, 0, 100, 100))
    b = _box(code="object_fault_type_02", score=0.8, xyxy=(0, 0, 100, 100), class_id=1)
    merged = merge_across_tiles([a, b])
    assert len(merged) == 2


# ---------- decide_verdict ----------

def test_verdict_no_boxes():
    cfg = InspectConfig(objects=[_spec()])
    assert decide_verdict([], cfg) == ("auto_pass", [])


def test_verdict_mid_score():
    cfg = InspectConfig(objects=[_spec(recheck_min=0.5, auto_min=0.9)])
    verdict, reasons = decide_verdict([_box(score=0.7)], cfg)
    assert verdict == "recheck"
    assert "mid_score" in reasons


def test_verdict_low_score():
    cfg = InspectConfig(objects=[_spec(recheck_min=0.5, auto_min=0.9)])
    verdict, reasons = decide_verdict([_box(score=0.3)], cfg)
    assert verdict == "manual"
    assert "low_score" in reasons


def test_verdict_high_risk():
    cfg = InspectConfig(objects=[_spec(recheck_min=0.5, auto_min=0.9, risk_level=3)])
    verdict, reasons = decide_verdict([_box(score=0.95)], cfg)
    assert verdict == "recheck"
    assert "high_risk" in reasons


def test_verdict_unknown_code():
    cfg = InspectConfig(objects=[_spec()])
    verdict, reasons = decide_verdict([_box(code="object_fault_type_99")], cfg)
    assert verdict == "manual"
    assert "unknown_code" in reasons


# ---------- load_config ----------

def test_load_config_valid():
    cfg = load_config(TEMPLATE_JSON)
    assert cfg.tile_size == 1280
    assert cfg.overlap == 0.2
    assert len(cfg.objects) == 2
    o0 = cfg.objects[0]
    assert o0.code == "object_fault_type_01"
    assert o0.model_ref == "3-yolo@ds1"
    assert o0.class_map == {0: "object_fault_type_01"}
    assert o0.recheck_min == 0.60 and o0.auto_min == 0.90
    assert o0.risk_level == 3


def test_load_config_missing_thresholds():
    bad = '{"model_ref":"3-yolo@ds1","objects":[{"code":"object_fault_type_01","class_map":{"0":"object_fault_type_01"},"risk_level":1}]}'
    with pytest.raises(ValueError):
        load_config(bad)


def test_load_config_invalid_code():
    bad = '{"model_ref":"3-yolo@ds1","objects":[{"code":"bad_code","class_map":{"0":"bad_code"},"thresholds":{"recheck_min":0.5,"auto_min":0.9},"risk_level":1}]}'
    with pytest.raises(ValueError):
        load_config(bad)


def test_load_config_class_map_mismatch():
    bad = '{"model_ref":"3-yolo@ds1","objects":[{"code":"object_fault_type_01","class_map":{"0":"object_fault_type_02"},"thresholds":{"recheck_min":0.5,"auto_min":0.9},"risk_level":1}]}'
    with pytest.raises(ValueError):
        load_config(bad)


def test_load_config_threshold_order():
    bad = '{"model_ref":"3-yolo@ds1","objects":[{"code":"object_fault_type_01","class_map":{"0":"object_fault_type_01"},"thresholds":{"recheck_min":0.9,"auto_min":0.5},"risk_level":1}]}'
    with pytest.raises(ValueError):
        load_config(bad)


# ---------- run ----------

def test_run_missing_model_raises():
    cfg = InspectConfig(objects=[_spec()], tile_size=64, overlap=0)
    image = np.zeros((64, 64, 3), dtype=np.uint8)
    with pytest.raises(KeyError):
        run(image, cfg, models={})


def test_run_with_stub():
    cfg = InspectConfig(
        objects=[_spec(code="object_fault_type_01", model_ref="0-stub@ds0", class_id=0,
                       recheck_min=0.5, auto_min=0.9, risk_level=1)],
        tile_size=64, overlap=0,
    )
    image = np.zeros((64, 64, 3), dtype=np.uint8)
    result = run(image, cfg, models={"0-stub@ds0": StubRuntimeModel(model_ref="0-stub@ds0")})
    assert result.boxes
    assert result.verdict == "recheck"  # stub 框 score=0.85 落在 [0.5, 0.9)
    assert "mid_score" in result.verdict_reasons


def test_stub_model_ref_valid():
    assert parse_model_ref(StubRuntimeModel()._model_ref).framework == "stub"


def test_load_config_from_fixture(fixtures_dir):
    """inspect_config_sample.yaml 必须能被 load_config 解析（fixture 与实现互相锁定）。"""
    cfg = load_config((fixtures_dir / "inspect_config_sample.yaml").read_text(encoding="utf-8"))
    assert cfg.tile_size == 1280
    assert cfg.overlap == 0.2
    assert len(cfg.objects) == 2
    assert cfg.objects[0].code == "object_fault_type_01"
    assert cfg.objects[0].risk_level == 3
    assert cfg.objects[0].class_map == {0: "object_fault_type_01"}
