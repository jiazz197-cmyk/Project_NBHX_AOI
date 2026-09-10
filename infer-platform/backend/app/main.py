"""平台 B 后端入口：装配 FastAPI 应用。

对齐 docs/P0骨架设计_双平台.md §1、平台B契约。
"""

from __future__ import annotations

from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Request

from .api import health, inspect, models, records, reports, stations, stats, system
from .config import get_settings
from .db import init_db
from .envelope import new_request_id, register_exception_handlers
from . import scheduler


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings = get_settings()
    Path(settings.DATA_DIR).mkdir(parents=True, exist_ok=True)
    init_db()
    scheduler.start()
    yield
    scheduler.shutdown()


def create_app() -> FastAPI:
    app = FastAPI(title="aoi-infer", version="0.1.0", lifespan=lifespan)

    @app.middleware("http")
    async def request_id_middleware(request: Request, call_next):
        request.state.request_id = request.headers.get("X-Request-ID") or new_request_id()
        response = await call_next(request)
        return response

    app.include_router(health.router, prefix="/api/v1")
    app.include_router(models.router, prefix="/api/v1")
    app.include_router(stations.router, prefix="/api/v1")
    app.include_router(inspect.router, prefix="/api/v1")
    app.include_router(records.router, prefix="/api/v1")
    app.include_router(stats.router, prefix="/api/v1")
    app.include_router(reports.router, prefix="/api/v1")
    app.include_router(system.router, prefix="/api/v1")
    register_exception_handlers(app)
    return app


app = create_app()

