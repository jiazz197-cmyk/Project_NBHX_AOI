"""回传 A 平台的 HTTP 客户端。

携带 INTERNAL_TOKEN；目标地址见 TRAIN_PLATFORM_BASE_URL。
对齐 docs/contracts/跨平台契约_A-B.md §3.2：
  POST {A}/api/ingest/findings，multipart meta + file；
  头 X-Internal-Token / X-Request-ID / Idempotency-Key。
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import httpx

from ..config import get_settings
from ..envelope import new_request_id


def push_findings(meta: dict[str, Any], idempotency_key: str, image_path: str | None = None) -> dict[str, Any]:
    """POST {A}/api/ingest/findings；返回 A 侧 data，失败抛异常（由调用方退避）。"""
    settings = get_settings()
    base = settings.TRAIN_PLATFORM_BASE_URL.rstrip("/")
    if not base:
        raise RuntimeError("TRAIN_PLATFORM_BASE_URL 未配置")

    headers = {
        "X-Internal-Token": settings.INTERNAL_TOKEN,
        "X-Request-ID": new_request_id(),
        "Idempotency-Key": idempotency_key,
    }
    data = {"meta": json.dumps(meta, ensure_ascii=False)}
    files = {}
    if image_path and Path(image_path).exists():
        files["file"] = (Path(image_path).name, open(image_path, "rb"), "application/octet-stream")

    resp = httpx.post(
        f"{base}/api/ingest/findings",
        headers=headers,
        data=data,
        files=files or None,
        timeout=60,
    )
    try:
        body = resp.json()
    except ValueError:
        body = {}
    if resp.status_code >= 400 or body.get("code") != 0:
        raise RuntimeError(f"回传失败 HTTP {resp.status_code}: {body}")
    return body.get("data", {})

