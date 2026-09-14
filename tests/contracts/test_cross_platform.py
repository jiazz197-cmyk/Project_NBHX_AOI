"""跨平台契约测试 —— 对齐 docs/contracts/跨平台契约_A-B.md §6（B 视角，可无 Django/PostgreSQL 跑）。

用共享 fixtures 锁定跨平台契约本体：
  - ``model_manifest_sample.json`` ↔ ``model_yaml_sample.yaml`` 跨文件一致（model_ref / skillname / precision）
  - 模型拉取（fake）：digest = manifest.config.digest；同 image 幂等
  - model.yaml 校验：fixture 通过 / ``schema_version`` 未知 → 42200
  - 错图回传 fixture：kind 枚举 + 幂等键 ``{station}-{seq}-{kind}`` + bad 无图
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
BACKEND = ROOT / "infer-platform" / "backend"
FIXTURES = Path(__file__).parent / "fixtures"

if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

import os  # noqa: E402

os.environ.setdefault("MODEL_PULL_MODE", "fake")
os.environ.setdefault("AOI_FAKE_FIXTURES_DIR", str(FIXTURES))


def _load(fixtures_dir: Path, name: str):
    return json.loads((fixtures_dir / name).read_text(encoding="utf-8"))


def test_manifest_matches_model_yaml(fixtures_dir):
    """manifest annotations 与 model.yaml 对应字段一致（跨文件锁定）。"""
    from app.registry.model_yaml import parse_model_yaml

    manifest = _load(fixtures_dir, "model_manifest_sample.json")
    doc = parse_model_yaml((fixtures_dir / "model_yaml_sample.yaml").read_text(encoding="utf-8"))
    ann = manifest["annotations"]
    assert ann["aoi.model_ref"] == doc["model_ref"]
    assert ann["aoi.skillname"] == doc["skillname"]
    assert ann["aoi.precision"] == doc["precision"]


def test_model_yaml_sample_valid(fixtures_dir):
    from app.registry.model_yaml import parse_model_yaml, validate_model_yaml

    doc = parse_model_yaml((fixtures_dir / "model_yaml_sample.yaml").read_text(encoding="utf-8"))
    summary = validate_model_yaml(doc)
    assert summary["model_ref"] == "3-yolo@ds1"


def test_model_yaml_unknown_schema_version_rejected(fixtures_dir):
    from app.envelope import BizError
    from app.registry.model_yaml import parse_model_yaml, validate_model_yaml

    doc = parse_model_yaml((fixtures_dir / "model_yaml_sample.yaml").read_text(encoding="utf-8"))
    doc["schema_version"] = 999
    with pytest.raises(BizError) as exc:
        validate_model_yaml(doc)
    assert exc.value.code == 42200


def test_pull_fake_digest_and_idempotent(tmp_path, monkeypatch, fixtures_dir):
    """fake 拉取：digest = manifest.config.digest；同 image 重复拉取 → 幂等同 digest。"""
    monkeypatch.setenv("DB_PATH", str(tmp_path / "infer.db"))
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    monkeypatch.setenv("MODEL_PULL_MODE", "fake")
    monkeypatch.setenv("AOI_FAKE_FIXTURES_DIR", str(fixtures_dir))
    from app.config import get_settings

    get_settings.cache_clear()
    from app.db import init_db

    init_db()
    from app.registry import pull

    manifest = _load(fixtures_dir, "model_manifest_sample.json")
    image = "docker.io/aoi/aoi-model:3-yolo-ds1"
    r1 = pull.pull_model(image)
    assert r1["status"] == "ready"
    assert r1["digest"] == manifest["config"]["digest"]

    r2 = pull.pull_model(image)
    assert r2["status"] == "ready"
    assert r2["digest"] == r1["digest"]
    get_settings.cache_clear()


def test_findings_sample_kinds_and_idempotency_key(fixtures_dir):
    """错图回传 fixture：suspicious+bad 两条、bad 无图、幂等键 ``{station}-{seq}-{kind}``。"""
    samples = _load(fixtures_dir, "findings_ingest_sample.json")
    assert {s["kind"] for s in samples} == {"suspicious", "bad"}
    for s in samples:
        key = f"{s['station_code']}-{s['seq']}-{s['kind']}"
        assert key
        if s["kind"] == "bad":
            assert s["image"] is None
            assert s["verdict"] is None
            assert s["boxes"] == []
