"""按 OCI / Docker Registry HTTP API v2 拉取模型镜像。

默认 MODEL_PULL_MODE=oci（纯 httpx + tarfile，无 Docker daemon 依赖）。
D3 用 MODEL_PULL_MODE=fake：读取假 manifest + 假层（内存 tar.gz），走通
"manifest → 层 → 解包 → sha256/digest 校验 → 落盘 → 注册"全链路。

对齐 docs/contracts/跨平台契约_A-B.md §2.5、docs/P0骨架设计_双平台.md §1。
"""

from __future__ import annotations

import hashlib
import io
import json
import os
import re
import tarfile
from pathlib import Path
from typing import Any

from ..config import get_settings
from ..envelope import (
    CODE_BAD_PAYLOAD,
    CODE_CONFLICT,
    CODE_NOT_READY,
    CODE_VALIDATION_FAILED,
    BizError,
)
from ..store import models as store_models
from .model_yaml import parse_model_yaml, validate_model_yaml

_FAKE_FIXTURES = Path(
    os.environ.get(
        "AOI_FAKE_FIXTURES_DIR",
        Path(__file__).resolve().parents[4] / "tests" / "contracts" / "fixtures",
    )
)


def pull_model(image: str, digest: str | None = None) -> dict[str, Any]:
    """拉取入口：按 MODEL_PULL_MODE 分发。"""
    settings = get_settings()
    if settings.MODEL_PULL_MODE == "fake":
        return _pull_fake(image, digest)
    return _pull_oci(image, digest)


def _pull_fake(image: str, digest: str | None = None) -> dict[str, Any]:
    """假 manifest 拉取：读 fixture 假 manifest，构造内存假层，走通全链路。"""
    manifest_path = _FAKE_FIXTURES / "model_manifest_sample.json"
    yaml_path = _FAKE_FIXTURES / "model_yaml_sample.yaml"
    if not manifest_path.exists() or not yaml_path.exists():
        raise BizError(503, CODE_NOT_READY, f"fake fixtures 缺失：{_FAKE_FIXTURES}")

    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    annotations = manifest.get("annotations", {})
    model_ref = annotations.get("aoi.model_ref")
    if not model_ref:
        raise BizError(422, CODE_VALIDATION_FAILED, "model config invalid",
                       {"fields": {"manifest": "missing aoi.model_ref annotation"}})
    image_digest = manifest["config"]["digest"]

    # §2.5 幂等：同 model_ref + 同 digest → 直接 ready；同 model_ref 不同 digest → 40900
    existing = store_models.get_model(model_ref)
    if existing is not None:
        if existing.get("image_digest") == image_digest:
            classes = json.loads(existing["class_names"])
            return {"model_ref": model_ref, "digest": image_digest, "status": "ready", "classes": len(classes)}
        raise BizError(409, CODE_CONFLICT, "model_ref 已存在且 digest 不同，请先删除旧版本")

    # 构造假层：model.onnx 固定字节，model.yaml 的 sha256 重算后注入，保证校验可闭环
    onnx_bytes = b"AOI-FAKE-ONNX-WEIGHTS" * 512
    actual_sha = hashlib.sha256(onnx_bytes).hexdigest()
    yaml_text = yaml_path.read_text(encoding="utf-8")
    yaml_text = re.sub(r"sha256: [0-9a-f]+", f"sha256: {actual_sha}", yaml_text, count=1)

    layer = _build_layer({
        "model/model.onnx": onnx_bytes,
        "model/model.yaml": yaml_text.encode("utf-8"),
        "model/model.onnx.sha256": (actual_sha + "\n").encode("utf-8"),
    })

    return _unpack_and_register(layer, model_ref, image_digest, image)


def _pull_oci(image: str, digest: str | None = None) -> dict[str, Any]:
    """Registry v2 真拉取（httpx + tarfile）。D3 后实现，当前返回未就绪。"""
    raise BizError(503, CODE_NOT_READY, "OCI 真拉取尚未实现（D3 用 MODEL_PULL_MODE=fake）")


def _build_layer(files: dict[str, bytes]) -> bytes:
    """构造 gzip tar 层（镜像布局固定 /model/*，见跨平台契约 §2.1）。"""
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w:gz") as tar:
        for name, data in files.items():
            info = tarfile.TarInfo(name)
            info.size = len(data)
            tar.addfile(info, io.BytesIO(data))
    return buf.getvalue()


def _extract_layer(layer: bytes) -> dict[str, bytes]:
    """解包 gzip tar 层 → {路径: 内容}。"""
    try:
        with tarfile.open(fileobj=io.BytesIO(layer), mode="r:gz") as tar:
            return {m.name: tar.extractfile(m).read() for m in tar.getmembers() if m.isfile()}
    except tarfile.TarError as exc:
        raise BizError(400, CODE_BAD_PAYLOAD, "镜像层解包失败") from exc


def _unpack_and_register(layer: bytes, model_ref: str, image_digest: str, source_image: str) -> dict[str, Any]:
    """解包 → sha256 校验 → model.yaml 校验 → 落盘 → 注册 b_model + b_defect_class。"""
    members = _extract_layer(layer)
    prefix = "model/"
    try:
        onnx_bytes = members[prefix + "model.onnx"]
        yaml_text = members[prefix + "model.yaml"].decode("utf-8")
        sha_text = members.get(prefix + "model.onnx.sha256", b"").decode("utf-8").strip()
    except KeyError as exc:
        raise BizError(400, CODE_BAD_PAYLOAD, "镜像层缺少必要文件（/model/*）") from exc

    # §2.3 规则 5：onnx.sha256 与实际文件一致
    actual_sha = hashlib.sha256(onnx_bytes).hexdigest()
    data = parse_model_yaml(yaml_text)
    summary = validate_model_yaml(data)
    onnx_cfg = summary["onnx"]
    if onnx_cfg.get("sha256") != actual_sha or (sha_text and sha_text != actual_sha):
        raise BizError(400, CODE_BAD_PAYLOAD, "onnx sha256 不一致")

    precision = summary["precision"] or "fp32"
    stored_dir = Path(get_settings().DATA_DIR) / "models" / model_ref / precision
    stored_dir.mkdir(parents=True, exist_ok=True)
    (stored_dir / "model.onnx").write_bytes(onnx_bytes)
    (stored_dir / "model.yaml").write_text(yaml_text, encoding="utf-8")
    (stored_dir / "model.onnx.sha256").write_text(actual_sha + "\n", encoding="utf-8")

    classes: list[dict[str, Any]] = summary["classes"]
    class_names = [c["code"] for c in sorted(classes, key=lambda c: c.get("index", 0))]
    onnx_input = onnx_cfg.get("input") or {}
    onnx_output = onnx_cfg.get("output") or {}

    store_models.register_model({
        "model_ref": model_ref,
        "skillname": summary["skillname"],
        "framework": summary["framework"],
        "dataset_version": data.get("dataset_version"),
        "class_names": class_names,
        "cover_classes": [c["code"] for c in classes],
        "precision": precision,
        "config_json": yaml_text,
        "source_image": source_image,
        "image_digest": image_digest,
        "sha256": actual_sha,
        "size_bytes": onnx_cfg.get("size_bytes"),
        "opset": onnx_cfg.get("opset"),
        "input_name": onnx_input.get("name"),
        "output_name": onnx_output.get("name"),
        "input_shape": onnx_input.get("shape"),
        "stored_path": str(stored_dir / "model.onnx"),
        "status": "ready",
    })
    store_models.refresh_defect_classes(model_ref, classes)

    return {"model_ref": model_ref, "digest": image_digest, "status": "ready", "classes": len(classes)}

