"""平台 B 后端入口：装配 FastAPI 应用并托管前端静态产物。

对齐 docs/P0骨架设计_双平台.md §1、docs/contracts/平台B_接口与数据契约.md。
"""

from fastapi import FastAPI


def create_app() -> FastAPI:
    """创建并装配 FastAPI 应用。"""
    app = FastAPI(title="aoi-infer", version="0.1.0")

    # TODO: 挂载 app/api 下各路由
    #   health / inspect / records / stats / reports / models / stations / templates / system
    # TODO: 用 StaticFiles 托管前端构建产物，并把 SPA fallback 到 index.html
    # TODO: 注册 scheduler（APScheduler 定时任务）

    return app


app = create_app()
