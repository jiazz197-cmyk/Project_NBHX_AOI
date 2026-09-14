"""环境变量契约（24 个键，逐字对齐 docs/P0骨架设计_双平台.md §6）。"""

from __future__ import annotations

import os
from functools import lru_cache

from pydantic import BaseModel


class Settings(BaseModel):
    """平台 B 全部 24 个配置键，键名与 §6 逐字一致。"""

    # ---------- 服务 ----------
    PORT: int = 8990
    TZ: str = "Asia/Shanghai"
    INSTANCE_CODE: str = "B01"
    LOG_LEVEL: str = "INFO"

    # ---------- 数据库 ----------
    DB_PATH: str = "/data/infer.db"

    # ---------- 文件存储 ----------
    DATA_DIR: str = "/data"

    # ---------- 模型拉取 ----------
    MODEL_REGISTRY: str = "docker.io"
    MODEL_REGISTRY_USER: str = ""
    MODEL_REGISTRY_TOKEN: str = ""
    MODEL_IMAGE_REPO: str = ""
    MODEL_PULL_MODE: str = "oci"

    # ---------- 对接平台 A ----------
    TRAIN_PLATFORM_BASE_URL: str = ""
    INTERNAL_TOKEN: str = ""

    # ---------- 推理 ----------
    INSPECT_QUEUE_MAX: int = 32
    INSPECT_CONCURRENCY: int = 2
    INFER_TIMEOUT_MS: int = 10000
    ONNX_PROVIDER: str = "cpu"

    # ---------- 存储保留策略 ----------
    AUTO_PASS_KEEP_IMAGE: bool = False
    AUTO_PASS_KEEP_THUMB: bool = True
    IMAGE_RETENTION_DAYS: int = 30
    MODEL_KEEP_VERSIONS: int = 3
    REPORT_RETENTION_DAYS: int = 90

    # ---------- 定时任务 ----------
    REPORT_CRON: str = "10 0 * * *"
    OUTBOX_MAX_AGE_HOURS: int = 24
    PULL_TMP_TTL_HOURS: int = 24

    @classmethod
    def from_env(cls) -> "Settings":
        """从环境变量读取；缺省值用上面默认值，类型交给 pydantic 强转。"""
        data = {name: os.environ[name] for name in cls.model_fields if name in os.environ}
        return cls(**data)


@lru_cache
def get_settings() -> Settings:
    """Settings 单例（进程内缓存）。"""
    return Settings.from_env()

