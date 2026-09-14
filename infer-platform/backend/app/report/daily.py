"""日报生成（HTML / CSV）。

对齐 docs/contracts/平台B_接口与数据契约.md §3.7、§7：
  每日 cron 聚合 b_inspection / b_bad_image → b_stats_daily / b_report → HTML/CSV。
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from jinja2 import Environment, FileSystemLoader

from ..config import get_settings
from ..db import _connect

_TEMPLATE_DIR = Path(__file__).parent / "templates"


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def aggregate_day(day: str) -> dict[str, Any]:
    """从 b_inspection / b_bad_image 聚合当日数据（D3：按 captured_at 前缀匹配）。"""
    conn = _connect()
    try:
        rows = conn.execute(
            "SELECT verdict, COUNT(*) AS n FROM b_inspection WHERE captured_at LIKE ? GROUP BY verdict",
            (day + "%",),
        ).fetchall()
        total = sum(r["n"] for r in rows)
        by_verdict = {r["verdict"]: r["n"] for r in rows}

        bad_count = conn.execute(
            "SELECT COUNT(*) AS n FROM b_bad_image WHERE captured_at LIKE ?", (day + "%",),
        ).fetchone()["n"]

        defect: dict[str, int] = {}
        for r in conn.execute(
            "SELECT boxes FROM b_inspection WHERE boxes IS NOT NULL AND captured_at LIKE ?",
            (day + "%",),
        ):
            for b in json.loads(r["boxes"] or "[]"):
                code = b.get("object_code")
                if code:
                    defect[code] = defect.get(code, 0) + 1

        errors: dict[str, int] = {}
        for r in conn.execute(
            "SELECT error_code, COUNT(*) AS n FROM b_bad_image WHERE captured_at LIKE ? GROUP BY error_code",
            (day + "%",),
        ):
            errors[r["error_code"]] = r["n"]

        latencies = [r["latency_ms"] for r in conn.execute(
            "SELECT latency_ms FROM b_inspection WHERE latency_ms IS NOT NULL AND captured_at LIKE ?",
            (day + "%",),
        )]
        avg_latency = int(sum(latencies) / len(latencies)) if latencies else 0
        p95_latency = sorted(latencies)[int(len(latencies) * 0.95)] if latencies else 0

        return {
            "day": day,
            "total": total,
            "auto_pass": by_verdict.get("auto_pass", 0),
            "recheck": by_verdict.get("recheck", 0),
            "manual": by_verdict.get("manual", 0),
            "bad_count": bad_count,
            "defect_counts": defect,
            "error_counts": errors,
            "avg_latency_ms": avg_latency,
            "p95_latency_ms": p95_latency,
        }
    finally:
        conn.close()


def _render_html(agg: dict[str, Any]) -> str:
    env = Environment(loader=FileSystemLoader(str(_TEMPLATE_DIR)), autoescape=True)
    template = env.get_template("daily.html.j2")
    pass_rate = (agg["auto_pass"] / agg["total"] * 100) if agg["total"] else 0.0
    return template.render(
        **agg,
        pass_rate=round(pass_rate, 1),
        defect_topn=sorted(agg["defect_counts"].items(), key=lambda kv: kv[1], reverse=True)[:10],
        error_items=agg["error_counts"].items(),
    )


def _to_csv(agg: dict[str, Any]) -> str:
    lines = ["day,total,auto_pass,recheck,manual,bad_count"]
    lines.append(f"{agg['day']},{agg['total']},{agg['auto_pass']},{agg['recheck']},{agg['manual']},{agg['bad_count']}")
    return "\n".join(lines) + "\n"


def generate_daily(day: str) -> dict[str, Any]:
    """聚合 → 渲染 HTML/CSV → 写 b_report。"""
    settings = get_settings()
    agg = aggregate_day(day)
    reports_dir = Path(settings.DATA_DIR) / "reports"
    reports_dir.mkdir(parents=True, exist_ok=True)

    html_path = reports_dir / f"{day}.html"
    csv_path = reports_dir / f"{day}.csv"
    html_path.write_text(_render_html(agg), encoding="utf-8")
    csv_path.write_text(_to_csv(agg), encoding="utf-8")

    conn = _connect()
    try:
        conn.execute(
            "INSERT OR REPLACE INTO b_report (day, html_path, csv_path, stats_json, generated_at) VALUES (?,?,?,?,?)",
            (day, str(html_path), str(csv_path), json.dumps(agg, ensure_ascii=False), _now()),
        )
        conn.commit()
    finally:
        conn.close()

    return {
        "day": day, "total": agg["total"], "auto_pass": agg["auto_pass"],
        "recheck": agg["recheck"], "manual": agg["manual"], "bad_count": agg["bad_count"],
        "html_path": str(html_path), "csv_path": str(csv_path),
    }

