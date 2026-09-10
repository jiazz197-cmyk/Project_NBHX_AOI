"""解析并校验 model.yaml（模型能力描述）。

对齐 docs/contracts/跨平台契约_A-B.md §2.3：
  - 必填字段齐全 → 42200
  - schema_version 已知且支持 → 42200
  - skillname ∈ skillname.SkillName → 42200
  - model_ref 可被 skillname.parse_model_ref 解析 → 42200
  - classes[].code 通过 is_valid_fault_code 且不重复 → 42200
  - classes[].index 唯一且连续 → 42200
  - 0 < recommended.recheck_min < recommended.auto_min < 1 → 42200
  - onnx.sha256 与实际 model.onnx sha256 一致 → 40010（解包后由调用方校验）
  - 可选/预留/未知字段 → 缺省值 / 原样保存，不报错
"""

from __future__ import annotations

from typing import Any

import yaml

from ..envelope import CODE_VALIDATION_FAILED, BizError

SUPPORTED_SCHEMA_VERSION = 1

_REQUIRED_TOP = (
    "schema_version", "model_ref", "skillname", "framework",
    "precision", "gate_status", "dataset_version", "created_at",
)
_REQUIRED_ONNX = ("file", "sha256", "size_bytes", "opset", "input", "output")
_REQUIRED_ONNX_INPUT = ("name", "shape", "dtype", "layout")
_REQUIRED_ONNX_OUTPUT = ("name", "shape", "format")
_REQUIRED_CLASS = ("index", "code", "name_cn", "risk_level", "recommended")


def _invalid(fields: dict[str, str]) -> None:
    raise BizError(422, CODE_VALIDATION_FAILED, "model config invalid", {"fields": fields})


def parse_model_yaml(text: str) -> dict[str, Any]:
    """YAML 文本 → dict；解析失败按 42200 处理。"""
    try:
        data = yaml.safe_load(text)
    except yaml.YAMLError as exc:
        _invalid({"model": f"yaml parse failed: {exc}"})
    if not isinstance(data, dict):
        _invalid({"model": "must be a mapping"})
    return data


def validate_model_yaml(data: dict[str, Any]) -> dict[str, Any]:
    """执行 §2.3 全部校验规则，返回结构化摘要。

    返回键：model_ref / skillname / precision / framework / classes / onnx / raw。
    """
    from skillname import SkillName, is_valid_fault_code, parse_model_ref

    fields: dict[str, str] = {}

    # 1. 必填字段齐全（顶层 + onnx）
    for key in _REQUIRED_TOP:
        if data.get(key) is None:
            fields[key] = "required"
    onnx = data.get("onnx")
    if not isinstance(onnx, dict):
        fields["onnx"] = "required mapping"
    else:
        for key in _REQUIRED_ONNX:
            if onnx.get(key) is None:
                fields[f"onnx.{key}"] = "required"
        inp, out = onnx.get("input"), onnx.get("output")
        if not isinstance(inp, dict):
            fields["onnx.input"] = "required mapping"
        else:
            for key in _REQUIRED_ONNX_INPUT:
                if inp.get(key) is None:
                    fields[f"onnx.input.{key}"] = "required"
        if not isinstance(out, dict):
            fields["onnx.output"] = "required mapping"
        else:
            for key in _REQUIRED_ONNX_OUTPUT:
                if out.get(key) is None:
                    fields[f"onnx.output.{key}"] = "required"

    classes = data.get("classes")
    if not isinstance(classes, list) or not classes:
        fields["classes"] = "must be a non-empty list"

    # 2. schema_version 已知且支持
    sv = data.get("schema_version")
    if isinstance(sv, int) and sv > SUPPORTED_SCHEMA_VERSION:
        fields["schema_version"] = f"unsupported {sv} (supported: {SUPPORTED_SCHEMA_VERSION})"

    # 3. skillname
    skillname = data.get("skillname")
    if isinstance(skillname, str):
        try:
            SkillName(skillname)
        except ValueError:
            fields["skillname"] = f"unknown skillname: {skillname!r}"

    # 4. model_ref 可解析
    model_ref = data.get("model_ref")
    if isinstance(model_ref, str):
        try:
            parse_model_ref(model_ref)
        except ValueError as exc:
            fields["model_ref"] = str(exc)

    # 6/7/8. classes 逐条校验
    if isinstance(classes, list):
        seen_codes: set[str] = set()
        indexes: list[int] = []
        for i, cls in enumerate(classes):
            if not isinstance(cls, dict):
                fields[f"classes[{i}]"] = "must be a mapping"
                continue
            for key in _REQUIRED_CLASS:
                if cls.get(key) is None:
                    fields[f"classes[{i}].{key}"] = "required"
            code = cls.get("code")
            if isinstance(code, str):
                if not is_valid_fault_code(code):
                    fields[f"classes[{i}].code"] = f"unknown fault code: {code!r}"
                elif code in seen_codes:
                    fields[f"classes[{i}].code"] = f"duplicate fault code: {code!r}"
                else:
                    seen_codes.add(code)
            index = cls.get("index")
            if isinstance(index, int) and not isinstance(index, bool):
                indexes.append(index)
            # 8. recommended 阈值关系
            rec = cls.get("recommended")
            if isinstance(rec, dict):
                recheck, auto = rec.get("recheck_min"), rec.get("auto_min")
                if isinstance(recheck, (int, float)) and isinstance(auto, (int, float)):
                    if not (0 < recheck < auto < 1):
                        fields[f"classes[{i}].recommended"] = "require 0 < recheck_min < auto_min < 1"
        # 7. index 唯一且连续
        if indexes and (len(set(indexes)) != len(indexes) or indexes != list(range(min(indexes), min(indexes) + len(indexes)))):
            fields["classes.index"] = "indexes must be unique and contiguous"

    if fields:
        _invalid(fields)

    return {
        "model_ref": model_ref,
        "skillname": skillname,
        "precision": data.get("precision"),
        "framework": data.get("framework"),
        "classes": classes,
        "onnx": onnx,
        "raw": data,
    }

