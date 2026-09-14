"""aoi 路由公共件：LS ``APPEND_SLASH`` 中间件的二次派发兜底。

背景（P1 实测）：LS 用 ``core.middleware.CommonMiddlewareAppendSlashWithoutRedirect``
覆盖了 Django 的 APPEND_SLASH —— 任何 **404** 响应都会被改写成"带尾斜杠"的 URL 再派发一次
（``core/middleware.py:54-108``）。aoi 契约路径刻意不带尾斜杠（如 ``/api/train/models/{id}/publish``），
若不做兜底，视图正常返回的 ``40401 + 信封`` 会被换成 LS 的 HTML 404 页面，
B 侧/前端拿不到错误码。

因此 ``aoi/urls.py`` 在真实路由**之后**注册本兜底：
把 ``/api/.../<x>/`` 内部派发到 ``/api/.../<x>``（同请求、不产生 302、保留原响应与信封）。
"""

from __future__ import annotations

__all__ = ['slash_fallback']


def slash_fallback(request, aoi_path: str):
    """``/api/.../<x>/`` → 内部派发 ``/api/.../<x>``（同请求，不重定向）。"""
    from django.urls import resolve

    match = resolve('/' + aoi_path.rstrip('/'))
    return match.func(request, *match.args, **match.kwargs)


urlpatterns: list = []
