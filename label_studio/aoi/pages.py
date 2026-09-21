"""aoi SPA 页面路由（契约 §2.2，D5/H22）。

LS 原生页面各由上游 app 注册路由渲染壳模板（如 ``/projects/``）；aoi 页面在此
**点名**注册，不使用泛 catch-all——``aoi.urls`` 在 ``core/urls.py`` 中无前缀 include，
其后还有 30+ 条上游路由（``admin/``、``docs/``、``heidi-tips/`` 等），泛 ``^.*$`` 会全部吞掉。
"""

from __future__ import annotations

from django.contrib.auth.decorators import login_required
from django.shortcuts import render

__all__ = ['aoi_spa_page']

#: aoi SPA 页面路径（与 ``web/apps/labelstudio/src/pages/index.js`` 注册的 ``.path`` 一一对应）
AOI_SPA_PAGES = 'datasets|training|review|system|organization-admin'


@login_required
def aoi_spa_page(request, page: str):
    """渲染 SPA 壳模板（形态同上游 ``projects/list.html``），React 在客户端接管路由。"""
    return render(request, 'aoi/page.html')
