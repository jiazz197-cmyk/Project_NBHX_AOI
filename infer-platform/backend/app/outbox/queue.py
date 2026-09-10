"""outbox 队列：入队 / 重试 / 幂等 / 退避状态机。

跨平台回传以 (station_code, seq, kind) 幂等；断网时积压，恢复后补传。
对齐 docs/contracts/跨平台契约_A-B.md §3.5：
  pending → pushing → pushed
                    ↘ retrying（1m/5m/15m/1h/6h，最长 24h）→ dead（人工重推/导出）
"""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from typing import Any

from ..config import get_settings
from ..db import _connect

# §3.5 退避间隔（分钟）
RETRY_BACKOFF_MINUTES = (1, 5, 15, 60, 360)


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _add_minutes(iso: str, minutes: int) -> str:
    dt = datetime.strptime(iso, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)
    return (dt + timedelta(minutes=minutes)).strftime("%Y-%m-%dT%H:%M:%SZ")


def _age_hours(iso: str) -> float:
    dt = datetime.strptime(iso, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)
    return (datetime.now(timezone.utc) - dt).total_seconds() / 3600


# ---------- 入队 ----------

def enqueue(kind: str, ref_id: int, station_code: str, seq: int, payload: dict[str, Any]) -> int:
    """入队；幂等键 {station}-{seq}-{kind}，已存在则返回既有 id（不重复入队）。"""
    key = f"{station_code}-{seq}-{kind}"
    conn = _connect()
    try:
        row = conn.execute("SELECT id FROM b_outbox WHERE idempotency_key = ?", (key,)).fetchone()
        if row:
            return row["id"]
        cur = conn.execute(
            """
            INSERT INTO b_outbox (kind, ref_id, idempotency_key, payload, attempts, status, created_at)
            VALUES (?,?,?,?,0,'pending',?)
            """,
            (kind, ref_id, key, json.dumps(payload, ensure_ascii=False), _now()),
        )
        conn.commit()
        return cur.lastrowid
    finally:
        conn.close()


# ---------- 查询 ----------

def list_items() -> list[dict[str, Any]]:
    conn = _connect()
    try:
        rows = conn.execute("SELECT * FROM b_outbox ORDER BY id DESC").fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


def get_item(outbox_id: int) -> dict[str, Any] | None:
    conn = _connect()
    try:
        row = conn.execute("SELECT * FROM b_outbox WHERE id = ?", (outbox_id,)).fetchone()
        return dict(row) if row else None
    finally:
        conn.close()


def counts() -> dict[str, int]:
    conn = _connect()
    try:
        rows = conn.execute("SELECT status, COUNT(*) AS n FROM b_outbox GROUP BY status").fetchall()
        result = {"pending": 0, "pushing": 0, "pushed": 0, "dead": 0}
        for r in rows:
            if r["status"] in result:
                result[r["status"]] = r["n"]
        return result
    finally:
        conn.close()


def due_items(limit: int = 50) -> list[dict[str, Any]]:
    """pending 且到期（next_retry_at 为空或已过）的记录。"""
    conn = _connect()
    try:
        rows = conn.execute(
            """
            SELECT * FROM b_outbox
            WHERE status = 'pending' AND (next_retry_at IS NULL OR next_retry_at <= ?)
            ORDER BY id ASC LIMIT ?
            """,
            (_now(), limit),
        ).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


# ---------- 状态机 ----------

def mark_pushing(outbox_id: int) -> None:
    conn = _connect()
    try:
        conn.execute("UPDATE b_outbox SET status='pushing' WHERE id = ?", (outbox_id,))
        conn.commit()
    finally:
        conn.close()


def mark_pushed(outbox_id: int) -> None:
    conn = _connect()
    try:
        conn.execute(
            "UPDATE b_outbox SET status='pushed', pushed_at=?, last_error=NULL WHERE id = ?",
            (_now(), outbox_id),
        )
        conn.commit()
    finally:
        conn.close()


def mark_dead(outbox_id: int, error: str) -> None:
    conn = _connect()
    try:
        conn.execute(
            "UPDATE b_outbox SET status='dead', last_error=? WHERE id = ?",
            (error[:500], outbox_id),
        )
        conn.commit()
    finally:
        conn.close()


def on_failure(outbox_id: int, error: str) -> None:
    """推送失败：attempts+1；退避用尽或超 24h → dead，否则定下次重试时间。"""
    settings = get_settings()
    conn = _connect()
    try:
        row = conn.execute("SELECT attempts, created_at FROM b_outbox WHERE id = ?", (outbox_id,)).fetchone()
        if row is None:
            return
        attempts = row["attempts"] + 1
        if attempts >= len(RETRY_BACKOFF_MINUTES) or _age_hours(row["created_at"]) >= settings.OUTBOX_MAX_AGE_HOURS:
            conn.execute("UPDATE b_outbox SET status='dead', attempts=?, last_error=? WHERE id = ?",
                         (attempts, error[:500], outbox_id))
        else:
            next_retry = _add_minutes(_now(), RETRY_BACKOFF_MINUTES[attempts - 1])
            conn.execute(
                "UPDATE b_outbox SET status='pending', attempts=?, next_retry_at=?, last_error=? WHERE id = ?",
                (attempts, next_retry, error[:500], outbox_id),
            )
        conn.commit()
    finally:
        conn.close()


def retry_one(outbox_id: int) -> bool:
    """把单条置回 pending 并清空退避（立即可推）。"""
    conn = _connect()
    try:
        cur = conn.execute(
            "UPDATE b_outbox SET status='pending', next_retry_at=NULL, last_error=NULL WHERE id = ?",
            (outbox_id,),
        )
        conn.commit()
        return cur.rowcount > 0
    finally:
        conn.close()


def retry_all() -> int:
    """所有 dead → pending（立即可推），返回重置条数。"""
    conn = _connect()
    try:
        cur = conn.execute(
            "UPDATE b_outbox SET status='pending', next_retry_at=NULL, last_error=NULL WHERE status = 'dead'",
        )
        conn.commit()
        return cur.rowcount
    finally:
        conn.close()


# ---------- 推送装配 ----------

def _resolve_image_path(kind: str, ref_id: int) -> str | None:
    conn = _connect()
    try:
        if kind == "suspicious":
            row = conn.execute("SELECT image_path FROM b_inspection WHERE id = ?", (ref_id,)).fetchone()
        else:
            row = conn.execute("SELECT image_path FROM b_bad_image WHERE id = ?", (ref_id,)).fetchone()
        return row["image_path"] if row else None
    finally:
        conn.close()


def process_due(limit: int = 50) -> dict[str, int]:
    """推送到期记录（由 scheduler 定时或 retry 端点触发）。"""
    from .client import push_findings

    result = {"processed": 0, "pushed": 0, "failed": 0}
    for item in due_items(limit):
        result["processed"] += 1
        mark_pushing(item["id"])
        try:
            meta = json.loads(item["payload"])
            image_path = _resolve_image_path(item["kind"], item["ref_id"])
            push_findings(meta, item["idempotency_key"], image_path)
            mark_pushed(item["id"])
            result["pushed"] += 1
        except Exception as exc:  # noqa: BLE001
            result["failed"] += 1
            on_failure(item["id"], str(exc))
    return result


def push_one(outbox_id: int) -> dict[str, Any]:
    """立即推送单条（retry 端点用）；失败自动退避。"""
    from .client import push_findings

    item = get_item(outbox_id)
    if item is None:
        raise KeyError(f"outbox {outbox_id} not found")
    mark_pushing(outbox_id)
    try:
        meta = json.loads(item["payload"])
        image_path = _resolve_image_path(item["kind"], item["ref_id"])
        push_findings(meta, item["idempotency_key"], image_path)
        mark_pushed(outbox_id)
        return {"pushed": True}
    except Exception as exc:  # noqa: BLE001
        on_failure(outbox_id, str(exc))
        return {"pushed": False, "error": str(exc)}

