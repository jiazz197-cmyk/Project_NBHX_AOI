"""APScheduler 任务注册。

- outbox 推送循环：每 30s 扫到期记录推送到 A（断网积压，恢复补传）
- 日报生成：REPORT_CRON（默认 "10 0 * * *"，每日 00:10 本地时区）
"""

from __future__ import annotations

from datetime import datetime
from zoneinfo import ZoneInfo

from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.interval import IntervalTrigger

from .config import get_settings
from .outbox import queue
from .report import daily

_scheduler: BackgroundScheduler | None = None


def _outbox_tick() -> None:
    queue.process_due()


def _daily_report() -> None:
    settings = get_settings()
    try:
        day = datetime.now(ZoneInfo(settings.TZ)).strftime("%Y-%m-%d")
    except Exception:  # noqa: BLE001
        day = datetime.now().strftime("%Y-%m-%d")
    daily.generate_daily(day)


def start() -> BackgroundScheduler:
    """启动后台调度器（幂等）。"""
    global _scheduler
    if _scheduler is not None:
        return _scheduler
    settings = get_settings()
    sched = BackgroundScheduler(timezone=settings.TZ)
    sched.add_job(_outbox_tick, IntervalTrigger(seconds=30), id="outbox_tick", replace_existing=True)
    sched.add_job(_daily_report, CronTrigger.from_crontab(settings.REPORT_CRON), id="daily_report", replace_existing=True)
    sched.start()
    _scheduler = sched
    return sched


def shutdown() -> None:
    global _scheduler
    if _scheduler is not None:
        _scheduler.shutdown(wait=False)
        _scheduler = None

