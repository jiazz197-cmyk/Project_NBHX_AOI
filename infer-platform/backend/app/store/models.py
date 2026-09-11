"""数据访问层：b_model / b_defect_class 的注册与查询。

SQLite 约定（db._connect）：WAL + NORMAL + busy_timeout，单写锁串行化。
表结构逐字对齐 docs/contracts/平台B_接口与数据契约.md §2。
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any

from ..db import _connect


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _rows_to_dicts(rows: list[Any]) -> list[dict[str, Any]]:
    return [dict(r) for r in rows]


# ---------- b_model ----------

def register_model(info: dict[str, Any]) -> None:
    """INSERT OR REPLACE b_model（同 model_ref 覆盖）。"""
    conn = _connect()
    try:
        conn.execute(
            """
            INSERT OR REPLACE INTO b_model (
              model_ref, skillname, framework, dataset_version,
              class_names, cover_classes, precision, config_json,
              source_image, image_digest, sha256, size_bytes,
              opset, input_name, output_name, input_shape,
              stored_path, status, received_at, activated_at
            ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
            """,
            (
                info["model_ref"], info["skillname"], info["framework"], info.get("dataset_version"),
                json.dumps(info["class_names"], ensure_ascii=False),
                json.dumps(info["cover_classes"], ensure_ascii=False),
                info["precision"], info["config_json"],
                info.get("source_image"), info.get("image_digest"), info["sha256"], info["size_bytes"],
                info.get("opset"), info.get("input_name"), info.get("output_name"),
                json.dumps(info["input_shape"]) if info.get("input_shape") is not None else None,
                info["stored_path"], info.get("status", "ready"), _now(), None,
            ),
        )
        conn.commit()
    finally:
        conn.close()


def get_model(model_ref: str) -> dict[str, Any] | None:
    conn = _connect()
    try:
        row = conn.execute("SELECT * FROM b_model WHERE model_ref = ?", (model_ref,)).fetchone()
        return dict(row) if row else None
    finally:
        conn.close()


def get_model_by_sha(sha256: str) -> dict[str, Any] | None:
    conn = _connect()
    try:
        row = conn.execute("SELECT * FROM b_model WHERE sha256 = ?", (sha256,)).fetchone()
        return dict(row) if row else None
    finally:
        conn.close()


def list_models() -> list[dict[str, Any]]:
    conn = _connect()
    try:
        rows = conn.execute("SELECT * FROM b_model ORDER BY received_at DESC").fetchall()
        return _rows_to_dicts(rows)
    finally:
        conn.close()


def delete_model(model_ref: str) -> None:
    conn = _connect()
    try:
        conn.execute("DELETE FROM b_model WHERE model_ref = ?", (model_ref,))
        conn.execute("DELETE FROM b_defect_class WHERE source_model_ref = ?", (model_ref,))
        conn.commit()
    finally:
        conn.close()


# ---------- b_defect_class ----------

def refresh_defect_classes(model_ref: str, classes: list[dict[str, Any]]) -> None:
    """从 model.yaml 的 classes 刷新展示字典（b_defect_class）。"""
    conn = _connect()
    try:
        conn.execute("DELETE FROM b_defect_class WHERE source_model_ref = ?", (model_ref,))
        now = _now()
        for cls in classes:
            conn.execute(
                """
                INSERT OR REPLACE INTO b_defect_class (code, name_cn, risk_level, color, source_model_ref, updated_at)
                VALUES (?,?,?,?,?,?)
                """,
                (cls["code"], cls.get("name_cn") or "", cls.get("risk_level"), cls.get("color"), model_ref, now),
            )
        conn.commit()
    finally:
        conn.close()


# ---------- 序列化（契约 §3.2 字段） ----------

def to_list_item(row: dict[str, Any]) -> dict[str, Any]:
    """b_model 行 → GET /models 列表项。"""
    return {
        "model_ref": row["model_ref"],
        "skillname": row["skillname"],
        "precision": row["precision"],
        "sha256": row["sha256"],
        "source_image": row["source_image"],
        "image_digest": row["image_digest"],
        "status": row["status"],
        "classes": json.loads(row["class_names"]),
        "received_at": row["received_at"],
    }


# ---------- b_station ----------

def list_stations() -> list[dict[str, Any]]:
    conn = _connect()
    try:
        rows = conn.execute("SELECT * FROM b_station ORDER BY code").fetchall()
        return _rows_to_dicts(rows)
    finally:
        conn.close()


def get_station(code: str) -> dict[str, Any] | None:
    conn = _connect()
    try:
        row = conn.execute("SELECT * FROM b_station WHERE code = ?", (code,)).fetchone()
        return dict(row) if row else None
    finally:
        conn.close()


def create_station(info: dict[str, Any]) -> None:
    conn = _connect()
    try:
        conn.execute(
            """
            INSERT INTO b_station (code, name, enabled, channel_id, status)
            VALUES (?,?,?,?,?)
            """,
            (info["code"], info.get("name"), int(info.get("enabled", False)),
             info.get("channel_id"), "offline"),
        )
        conn.commit()
    finally:
        conn.close()


def update_station(code: str, info: dict[str, Any]) -> None:
    conn = _connect()
    try:
        conn.execute(
            "UPDATE b_station SET name=?, channel_id=? WHERE code = ?",
            (info.get("name"), info.get("channel_id"), code),
        )
        conn.commit()
    finally:
        conn.close()


def delete_station(code: str) -> None:
    conn = _connect()
    try:
        conn.execute("DELETE FROM b_station WHERE code = ?", (code,))
        conn.commit()
    finally:
        conn.close()


def set_station_enabled(code: str, enabled: bool) -> None:
    conn = _connect()
    try:
        conn.execute("UPDATE b_station SET enabled=? WHERE code = ?", (int(enabled), code))
        conn.commit()
    finally:
        conn.close()


def set_station_camera(code: str, camera_config: dict[str, Any]) -> None:
    conn = _connect()
    try:
        conn.execute(
            "UPDATE b_station SET camera_config=? WHERE code = ?",
            (json.dumps(camera_config, ensure_ascii=False), code),
        )
        conn.commit()
    finally:
        conn.close()


def set_station_template(code: str, template_json: str, version: int) -> None:
    conn = _connect()
    try:
        conn.execute(
            "UPDATE b_station SET template_json=?, template_version=? WHERE code = ?",
            (template_json, version, code),
        )
        conn.commit()
    finally:
        conn.close()


# ---------- b_inspection ----------

def insert_inspection(info: dict[str, Any]) -> int:
    conn = _connect()
    try:
        cur = conn.execute(
            """
            INSERT INTO b_inspection (
              station_code, seq, captured_at, received_at, template_version,
              model_refs, verdict, verdict_reasons, boxes, tiling_meta,
              latency_ms, image_path, thumb_path, image_md5, pushed_status, created_at
            ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
            """,
            (
                info["station_code"], info["seq"], info["captured_at"], info["received_at"],
                info.get("template_version"),
                json.dumps(info.get("model_refs", []), ensure_ascii=False),
                info["verdict"],
                json.dumps(info.get("verdict_reasons", []), ensure_ascii=False),
                json.dumps(info.get("boxes", []), ensure_ascii=False),
                json.dumps(info.get("tiling_meta", {}), ensure_ascii=False),
                info.get("latency_ms"),
                info.get("image_path"), info.get("thumb_path"), info.get("image_md5"),
                info.get("pushed_status", "n/a"), _now(),
            ),
        )
        conn.commit()
        return cur.lastrowid
    finally:
        conn.close()


def get_inspection(inspection_id: int) -> dict[str, Any] | None:
    conn = _connect()
    try:
        row = conn.execute("SELECT * FROM b_inspection WHERE id = ?", (inspection_id,)).fetchone()
        return dict(row) if row else None
    finally:
        conn.close()


def list_inspections() -> list[dict[str, Any]]:
    conn = _connect()
    try:
        rows = conn.execute("SELECT * FROM b_inspection ORDER BY id DESC LIMIT 500").fetchall()
        return _rows_to_dicts(rows)
    finally:
        conn.close()


# ---------- b_bad_image ----------

def insert_bad_image(info: dict[str, Any]) -> int:
    """登记坏图；同 (station_code, seq) 已存在则返回既有 id（幂等，防 UNIQUE 冲突）。"""
    conn = _connect()
    try:
        row = conn.execute(
            "SELECT id FROM b_bad_image WHERE station_code = ? AND seq = ?",
            (info["station_code"], info["seq"]),
        ).fetchone()
        if row:
            return row["id"]
        cur = conn.execute(
            """
            INSERT INTO b_bad_image (station_code, seq, captured_at, error_code, note, pushed_status, created_at)
            VALUES (?,?,?,?,?,?,?)
            """,
            (info["station_code"], info["seq"], info.get("captured_at"), info["error_code"],
             info.get("note"), info.get("pushed_status", "pending"), _now()),
        )
        conn.commit()
        return cur.lastrowid
    finally:
        conn.close()


def list_bad_images() -> list[dict[str, Any]]:
    conn = _connect()
    try:
        rows = conn.execute("SELECT * FROM b_bad_image ORDER BY id DESC LIMIT 500").fetchall()
        return _rows_to_dicts(rows)
    finally:
        conn.close()


def next_seq(station_code: str) -> int:
    """该工位下一个检测序号（契约 §5.2：单调递增，重启后从最大值+1 继续）。"""
    conn = _connect()
    try:
        row = conn.execute(
            "SELECT MAX(seq) AS m FROM b_inspection WHERE station_code = ?", (station_code,),
        ).fetchone()
        return (row["m"] or 0) + 1
    finally:
        conn.close()


# ---------- b_report ----------

def list_reports() -> list[dict[str, Any]]:
    conn = _connect()
    try:
        rows = conn.execute("SELECT * FROM b_report ORDER BY day DESC").fetchall()
        return _rows_to_dicts(rows)
    finally:
        conn.close()


def get_report(day: str) -> dict[str, Any] | None:
    conn = _connect()
    try:
        row = conn.execute("SELECT * FROM b_report WHERE day = ?", (day,)).fetchone()
        return dict(row) if row else None
    finally:
        conn.close()

