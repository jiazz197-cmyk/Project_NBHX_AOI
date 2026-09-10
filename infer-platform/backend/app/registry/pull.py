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

import httpx

from ..config import get_settings
from ..envelope import (
    CODE_BAD_PAYLOAD,
    CODE_BACKPRESSURE,
    CODE_CONFLICT,
    CODE_NOT_FOUND,
    CODE_NOT_READY,
    CODE_REGISTRY_UNAUTHORIZED,
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
    """Registry v2 真拉取（httpx + tarfile，无 Docker daemon）。

    流程（跨平台契约 §2.5）：解析 image → token（若需）→ GET manifest →
    校验 digest（若给定）→ GET 层 blob → 解包 → sha256/model.yaml 校验 → 落盘注册。
    """
    settings = get_settings()
    registry, repo, tag = _parse_image(image, settings.MODEL_REGISTRY)
    api_registry = _api_registry(registry)
    auth = (
        (settings.MODEL_REGISTRY_USER, settings.MODEL_REGISTRY_TOKEN)
        if settings.MODEL_REGISTRY_USER else None
    )

    with httpx.Client(
        follow_redirects=True,
        timeout=httpx.Timeout(connect=5.0, read=600.0, write=30.0, pool=30.0),
    ) as client:
        manifest, manifest_digest = _get_manifest(client, api_registry, repo, tag, auth)
        if digest and digest != manifest_digest:
            raise BizError(400, CODE_BAD_PAYLOAD, "digest 不一致")
        layers = manifest.get("layers") or []
        if not layers:
            raise BizError(400, CODE_BAD_PAYLOAD, "manifest 无层")
        layer = _download_layer(client, api_registry, repo, layers[0]["digest"], auth)

    # 提取 model.yaml 拿 model_ref（幂等检查用）
    members = _extract_layer(layer)
    try:
        yaml_text = members["model/model.yaml"].decode("utf-8")
    except KeyError as exc:
        raise BizError(400, CODE_BAD_PAYLOAD, "镜像层缺少 /model/model.yaml") from exc
    data = parse_model_yaml(yaml_text)
    model_ref = data.get("model_ref")
    if not isinstance(model_ref, str) or not model_ref:
        raise BizError(422, CODE_VALIDATION_FAILED, "model config invalid", {"fields": {"model_ref": "required"}})

    # §2.5 幂等：同 model_ref + 同 digest → 直接 ready；同 model_ref 不同 digest → 40900
    existing = store_models.get_model(model_ref)
    if existing is not None:
        if existing.get("image_digest") == manifest_digest:
            classes = json.loads(existing["class_names"])
            return {"model_ref": model_ref, "digest": manifest_digest, "status": "ready", "classes": len(classes)}
        raise BizError(409, CODE_CONFLICT, "model_ref 已存在且 digest 不同，请先删除旧版本")

    return _unpack_and_register(layer, model_ref, manifest_digest, image)


# ---------- Registry v2 底层 ----------

_OCI_MANIFEST_ACCEPT = ", ".join([
    "application/vnd.oci.image.manifest.v1+json",
    "application/vnd.oci.image.index.v1+json",
    "application/vnd.docker.distribution.manifest.v2+json",
    "application/vnd.docker.distribution.manifest.list.v2+json",
])

_DOCKER_HUB_API = "registry-1.docker.io"


def _parse_image(image: str, default_registry: str) -> tuple[str, str, str]:
    """解析 image → (registry, repository, tag)。

    支持：``docker.io/<org>/aoi-model:tag``、``<org>/aoi-model:tag``、
    ``registry.corp:5000/<org>/aoi-model:tag``。无 registry 时用 default_registry。
    """
    s = image
    if "://" in s:
        s = s.split("://", 1)[1]
    if "@" in s:
        s = s.split("@", 1)[0]

    tag = "latest"
    head, sep, maybe_tag = s.rpartition(":")
    if sep and "/" not in maybe_tag:
        s, tag = head, maybe_tag

    parts = s.split("/")
    if parts and ("." in parts[0] or ":" in parts[0] or parts[0] == "localhost"):
        registry, repository = parts[0], "/".join(parts[1:])
    else:
        registry, repository = default_registry, "/".join(parts)
    if not repository:
        raise BizError(400, CODE_BAD_PAYLOAD, "image 缺少仓库名")
    return registry, repository, tag


def _api_registry(registry: str) -> str:
    """docker.io 的 v2 API 走 registry-1.docker.io，其余原样。"""
    if registry == "docker.io":
        return _DOCKER_HUB_API
    return registry


def _registry_base(api_registry: str) -> str:
    """registry 基础 URL：本地回环用 http（测试/内网），其余 https（契约 §1.1）。"""
    if api_registry.startswith(("localhost", "127.0.0.1")):
        return f"http://{api_registry}"
    return f"https://{api_registry}"


def _parse_bearer_challenge(header: str) -> dict[str, str]:
    """解析 ``WWW-Authenticate: Bearer realm="...",service="...",scope="..."``。"""
    result: dict[str, str] = {}
    if not header or not header.lower().startswith("bearer "):
        return result
    for item in header[len("bearer "):].split(","):
        item = item.strip()
        if "=" in item:
            k, v = item.split("=", 1)
            result[k.strip()] = v.strip().strip('"')
    return result


def _get_token(client: httpx.Client, api_registry: str, repo: str, auth: Any) -> str | None:
    """向 registry 申请只读 token；匿名可访问时返回 None。"""
    probe = client.get(f"{_registry_base(api_registry)}/v2/")
    if probe.status_code != 401:
        return None
    challenge = _parse_bearer_challenge(probe.headers.get("WWW-Authenticate", ""))
    realm = challenge.get("realm")
    if not realm:
        return None
    params = {
        "service": challenge.get("service"),
        "scope": f"repository:{repo}:pull",
    }
    resp = client.get(realm, params={k: v for k, v in params.items() if v}, auth=auth)
    if resp.status_code >= 400:
        raise BizError(401, CODE_REGISTRY_UNAUTHORIZED, "registry 鉴权失败")
    try:
        return resp.json()["token"]
    except (ValueError, KeyError) as exc:
        raise BizError(401, CODE_REGISTRY_UNAUTHORIZED, "registry 鉴权失败") from exc


def _get_manifest(client: httpx.Client, api_registry: str, repo: str, tag: str, auth: Any) -> tuple[dict[str, Any], str]:
    """GET manifest，返回 (manifest_dict, digest)；匿名失败则走 token 重试。"""
    url = f"{_registry_base(api_registry)}/v2/{repo}/manifests/{tag}"
    headers = {"Accept": _OCI_MANIFEST_ACCEPT}
    resp = client.get(url, headers=headers)
    if resp.status_code == 401:
        token = _get_token(client, api_registry, repo, auth)
        if token:
            headers["Authorization"] = f"Bearer {token}"
            resp = client.get(url, headers=headers)
    if resp.status_code == 404:
        raise BizError(404, CODE_NOT_FOUND, "镜像/标签/清单不存在")
    if resp.status_code == 401:
        raise BizError(401, CODE_REGISTRY_UNAUTHORIZED, "registry 鉴权失败")
    if resp.status_code == 429:
        raise BizError(429, CODE_BACKPRESSURE, "registry 限流")
    if resp.status_code >= 400:
        raise BizError(400, CODE_BAD_PAYLOAD, f"拉取 manifest 失败 HTTP {resp.status_code}")
    try:
        manifest = resp.json()
    except ValueError as exc:
        raise BizError(400, CODE_BAD_PAYLOAD, "manifest 解析失败") from exc
    digest = resp.headers.get("Docker-Content-Digest") or (manifest.get("config") or {}).get("digest")
    return manifest, digest


def _download_layer(client: httpx.Client, api_registry: str, repo: str, layer_digest: str, auth: Any) -> bytes:
    """GET 层 blob；401 时走 token 重试。"""
    url = f"{_registry_base(api_registry)}/v2/{repo}/blobs/{layer_digest}"
    resp = client.get(url)
    if resp.status_code == 401:
        token = _get_token(client, api_registry, repo, auth)
        if not token:
            raise BizError(401, CODE_REGISTRY_UNAUTHORIZED, "registry 鉴权失败")
        resp = client.get(url, headers={"Authorization": f"Bearer {token}"})
    if resp.status_code == 404:
        raise BizError(404, CODE_NOT_FOUND, "镜像层不存在")
    if resp.status_code == 401:
        raise BizError(401, CODE_REGISTRY_UNAUTHORIZED, "registry 鉴权失败")
    if resp.status_code >= 400:
        raise BizError(400, CODE_BAD_PAYLOAD, f"下载层失败 HTTP {resp.status_code}")
    return resp.content


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

