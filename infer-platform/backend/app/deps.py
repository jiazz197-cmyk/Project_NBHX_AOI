"""依赖注入（FastAPI Depends 提供者）。

对齐 docs/P0骨架设计_双平台.md §3.1：
  无 RBAC / 无用户认证；B 只注入请求标识（request_id）。
"""

from __future__ import annotations

from fastapi import Request

from .envelope import new_request_id


def get_request_id(request: Request) -> str:
    """取请求内统一 request_id（由中间件设置），缺省生成。"""
    rid = getattr(request.state, "request_id", None)
    return rid or new_request_id()

