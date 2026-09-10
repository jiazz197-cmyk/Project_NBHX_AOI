"""SQLite（WAL）+ 顺序迁移执行器。

对齐 docs/P0骨架设计_双平台.md §3.1 的 SQLite 约定：
  journal_mode=WAL、synchronous=NORMAL、busy_timeout=5000。
迁移脚本位于 app/store/migrations/*.sql，按文件名顺序执行；
已应用数量用 SQLite PRAGMA user_version 记录（不引入额外业务表）。
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

from .config import get_settings

MIGRATIONS_DIR = Path(__file__).parent / "store" / "migrations"


def _connect() -> sqlite3.Connection:
    settings = get_settings()
    path = Path(settings.DB_PATH)
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(path))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL;")
    conn.execute("PRAGMA synchronous=NORMAL;")
    conn.execute("PRAGMA busy_timeout=5000;")
    return conn


def init_db() -> None:
    """建库并按顺序执行尚未应用的迁移（幂等）。"""
    conn = _connect()
    try:
        applied = conn.execute("PRAGMA user_version").fetchone()[0]
        migrations = sorted(MIGRATIONS_DIR.glob("*.sql"))
        for idx, path in enumerate(migrations, start=1):
            if idx <= applied:
                continue
            conn.executescript(path.read_text(encoding="utf-8"))
            conn.execute(f"PRAGMA user_version = {idx}")
        conn.commit()
    finally:
        conn.close()

