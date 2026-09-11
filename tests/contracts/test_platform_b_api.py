"""平台 B 契约测试（D3 收尾）。

覆盖 docs/contracts/平台B_接口与数据契约.md §11：
  信封 / 坏图 40010 / 工位 40402 / 无模板 42200 / 模型拉取幂等与 digest 校验 /
  工位模板校验 / outbox 幂等。

运行：
  cd infer-platform/backend
  docker run --rm -u $(id -u):$(id -g) -v $PWD/../..:/work ... ./.venv/bin/python -m pytest ../../tests/contracts/test_platform_b_api.py -q
"""

from __future__ import annotations

import io
import json
import sys
from pathlib import Path

import pytest
from PIL import Image

ROOT = Path(__file__).resolve().parents[2]
BACKEND = ROOT / "infer-platform" / "backend"
FIXTURES = Path(__file__).parent / "fixtures"

if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

# 必须在 import app 前设置（Settings 单例读 env）
import os  # noqa: E402

os.environ.setdefault("MODEL_PULL_MODE", "fake")
os.environ.setdefault("AOI_FAKE_FIXTURES_DIR", str(FIXTURES))


def _jpeg_bytes() -> bytes:
    buf = io.BytesIO()
    Image.new("RGB", (64, 48), color=(10, 20, 30)).save(buf, format="JPEG")
    return buf.getvalue()


def _valid_template() -> dict:
    return {
        "template_version": 0,
        "model_ref": "3-yolo@ds1",
        "skillname": "ObjectDetection",
        "tile_size": 1280,
        "overlap": 0.2,
        "objects": [
            {"code": "object_fault_type_01", "class_map": {"0": "object_fault_type_01"},
             "thresholds": {"recheck_min": 0.60, "auto_min": 0.90}, "risk_level": 3},
            {"code": "object_fault_type_02", "class_map": {"1": "object_fault_type_02"},
             "thresholds": {"recheck_min": 0.55, "auto_min": 0.88}, "risk_level": 2},
        ],
    }


@pytest.fixture()
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("DB_PATH", str(tmp_path / "infer.db"))
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    monkeypatch.setenv("MODEL_PULL_MODE", "fake")
    monkeypatch.setenv("AOI_FAKE_FIXTURES_DIR", str(FIXTURES))
    from app.config import get_settings

    get_settings.cache_clear()
    from fastapi.testclient import TestClient

    from app.main import create_app

    app = create_app()
    with TestClient(app) as c:
        yield c
    get_settings.cache_clear()


def _assert_envelope(body: dict, code: int = 0):
    assert set(body) >= {"code", "message", "request_id", "data"}, body
    assert body["code"] == code, body
    assert isinstance(body["request_id"], str) and body["request_id"]
    return body


# --------------------------------------------------------------------------- 信封
class TestEnvelope:
    def test_health_envelope(self, client):
        resp = client.get("/api/v1/health")
        assert resp.status_code == 200
        body = _assert_envelope(resp.json())
        assert body["data"]["status"] == "UP"
        assert {"gpu", "disk", "models", "stations", "inspect", "outbox"} <= set(body["data"])

    def test_request_id_passthrough(self, client):
        resp = client.get("/api/v1/health", headers={"X-Request-ID": "req-b-1"})
        assert resp.json()["request_id"] == "req-b-1"


# --------------------------------------------------------------------------- 坏图 40010
class TestBadImage:
    def test_decode_failed_returns_40010(self, client):
        resp = client.post(
            "/api/v1/inspect/image",
            files={"file": ("bad.jpg", b"not-an-image", "image/jpeg")},
            data={"station_code": "ST01", "seq": 1},
        )
        assert resp.status_code == 400
        assert resp.json()["code"] == 40010

    def test_bad_enqueues_outbox(self, client):
        resp = client.post(
            "/api/v1/inspect/image",
            files={"file": ("bad.jpg", b"not-an-image", "image/jpeg")},
            data={"station_code": "ST01", "seq": 1},
        )
        assert resp.status_code == 400
        assert resp.json()["code"] == 40010

        from app.outbox import queue
        from app.store import models as store_models

        items = queue.list_items()
        assert len(items) == 1
        item = items[0]
        assert item["kind"] == "bad"
        assert item["idempotency_key"] == "ST01-1-bad"

        payload = json.loads(item["payload"])
        assert payload["error_code"] == "decode_failed"
        assert payload["image"] is None
        assert payload["verdict"] is None

        bads = store_models.list_bad_images()
        assert len(bads) == 1
        assert item["ref_id"] == bads[0]["id"]

    def test_bad_duplicate_no_dup(self, client):
        for _ in range(2):
            resp = client.post(
                "/api/v1/inspect/image",
                files={"file": ("bad.jpg", b"not-an-image", "image/jpeg")},
                data={"station_code": "ST01", "seq": 1},
            )
            assert resp.status_code == 400
            assert resp.json()["code"] == 40010

        from app.outbox import queue
        from app.store import models as store_models

        assert len(queue.list_items()) == 1
        assert len(store_models.list_bad_images()) == 1

    def test_capture_failed_enqueues_outbox(self, client, tmp_path):
        client.post("/api/v1/stations", json={"code": "ST01", "name": "1号线"})
        client.post("/api/v1/stations/ST01/enable")
        empty_dir = tmp_path / "empty"
        empty_dir.mkdir()
        client.put("/api/v1/stations/ST01/camera", json={"adapter": "directory", "source": str(empty_dir)})

        resp = client.post("/api/v1/stations/ST01/capture")
        assert resp.status_code == 400
        assert resp.json()["code"] == 40010

        from app.outbox import queue
        from app.store import models as store_models

        items = queue.list_items()
        assert len(items) == 1
        item = items[0]
        assert item["kind"] == "bad"
        assert item["idempotency_key"] == "ST01-1-bad"

        payload = json.loads(item["payload"])
        assert payload["error_code"] == "capture_failed"
        assert payload["image"] is None
        assert payload["verdict"] is None

        bads = store_models.list_bad_images()
        assert len(bads) == 1
        assert bads[0]["error_code"] == "capture_failed"
        assert item["ref_id"] == bads[0]["id"]

    def test_consecutive_capture_failed_seq_increments(self, client, tmp_path):
        client.post("/api/v1/stations", json={"code": "ST01", "name": "1号线"})
        client.post("/api/v1/stations/ST01/enable")
        empty_dir = tmp_path / "empty"
        empty_dir.mkdir()
        client.put("/api/v1/stations/ST01/camera", json={"adapter": "directory", "source": str(empty_dir)})

        from app.outbox import queue
        from app.store import models as store_models

        for _ in range(3):
            resp = client.post("/api/v1/stations/ST01/capture")
            assert resp.status_code == 400
            assert resp.json()["code"] == 40010

        # 连续坏图 seq 单调递增（坏图也占号，不重号、不吞图）
        bads = store_models.list_bad_images()
        assert sorted(b["seq"] for b in bads) == [1, 2, 3]
        assert len(queue.list_items()) == 3


# --------------------------------------------------------------------------- 工位 40402
class TestStation:
    def test_unregistered_station_returns_40402(self, client):
        resp = client.post(
            "/api/v1/inspect/image",
            files={"file": ("a.jpg", _jpeg_bytes(), "image/jpeg")},
            data={"station_code": "NOTEXIST", "seq": 1},
        )
        assert resp.status_code == 404
        assert resp.json()["code"] == 40402

    def test_no_template_returns_42200(self, client):
        client.post("/api/v1/stations", json={"code": "ST01", "name": "1号线"})
        client.post("/api/v1/stations/ST01/enable")
        resp = client.post(
            "/api/v1/inspect/image",
            files={"file": ("a.jpg", _jpeg_bytes(), "image/jpeg")},
            data={"station_code": "ST01", "seq": 1},
        )
        assert resp.status_code == 422
        assert resp.json()["code"] == 42200


# --------------------------------------------------------------------------- 模型拉取幂等 + digest
class TestModelPull:
    def test_pull_idempotent_same_digest(self, client):
        payload = {"image": "docker.io/aoi/aoi-model:3-yolo-ds1"}
        r1 = client.post("/api/v1/models/pull", json=payload)
        assert r1.status_code == 200
        d1 = r1.json()["data"]
        assert d1["status"] == "ready"
        assert d1["model_ref"] == "3-yolo@ds1"
        assert d1["digest"].startswith("sha256:")

        r2 = client.post("/api/v1/models/pull", json=payload)
        assert r2.status_code == 200
        d2 = r2.json()["data"]
        assert d2["digest"] == d1["digest"]
        assert d2["status"] == "ready"

        listing = client.get("/api/v1/models").json()["data"]
        assert len(listing) == 1
        assert listing[0]["classes"] == ["object_fault_type_01", "object_fault_type_02"]

    def test_pull_missing_image_returns_40010(self, client):
        resp = client.post("/api/v1/models/pull", json={})
        assert resp.status_code == 400
        assert resp.json()["code"] == 40010


# --------------------------------------------------------------------------- 工位模板校验
class TestTemplate:
    def _prepare_model_and_station(self, client):
        client.post("/api/v1/models/pull", json={"image": "docker.io/aoi/aoi-model:3-yolo-ds1"})
        client.post("/api/v1/stations", json={"code": "ST01", "name": "1号线"})

    def test_valid_template_ok(self, client):
        self._prepare_model_and_station(client)
        resp = client.put("/api/v1/stations/ST01/template", json=_valid_template())
        assert resp.status_code == 200
        assert resp.json()["data"]["template_version"] == 1

    def test_invalid_code_returns_42200(self, client):
        self._prepare_model_and_station(client)
        bad = _valid_template()
        bad["objects"][0]["code"] = "object_fault_type_99"
        resp = client.put("/api/v1/stations/ST01/template", json=bad)
        assert resp.status_code == 422
        assert resp.json()["code"] == 42200

    def test_unknown_model_returns_42200(self, client):
        self._prepare_model_and_station(client)
        bad = _valid_template()
        bad["model_ref"] = "9-yolo@ds9"
        resp = client.put("/api/v1/stations/ST01/template", json=bad)
        assert resp.status_code == 422
        assert resp.json()["code"] == 42200


# --------------------------------------------------------------------------- outbox 幂等
class TestOutbox:
    def test_enqueue_idempotent(self, tmp_path, monkeypatch):
        monkeypatch.setenv("DB_PATH", str(tmp_path / "infer.db"))
        monkeypatch.setenv("DATA_DIR", str(tmp_path))
        from app.config import get_settings

        get_settings.cache_clear()
        from app.db import init_db

        init_db()
        from app.outbox import queue

        meta = {"kind": "suspicious", "station_code": "ST01", "seq": 1042, "verdict": "recheck"}
        id1 = queue.enqueue("suspicious", 1, "ST01", 1042, meta)
        id2 = queue.enqueue("suspicious", 1, "ST01", 1042, meta)
        assert id1 == id2
        assert len(queue.list_items()) == 1
        get_settings.cache_clear()

    def test_mark_pushed_syncs_bad_image_status(self, tmp_path, monkeypatch):
        monkeypatch.setenv("DB_PATH", str(tmp_path / "infer.db"))
        monkeypatch.setenv("DATA_DIR", str(tmp_path))
        from app.config import get_settings

        get_settings.cache_clear()
        from app.db import init_db

        init_db()
        from app.outbox import queue
        from app.store import models as store_models

        bad_id = store_models.insert_bad_image({"station_code": "ST01", "seq": 1, "error_code": "capture_failed"})
        oid = queue.enqueue("bad", bad_id, "ST01", 1, {"kind": "bad"})

        queue.mark_pushed(oid)

        bads = store_models.list_bad_images()
        assert bads[0]["pushed_status"] == "pushed"
        assert bads[0]["pushed_at"]
        get_settings.cache_clear()
