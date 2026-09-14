"""aoi 二开路由汇总（由 ``core/urls.py`` 一行注入）。

前缀**不带尾斜杠**，与契约 §4 的路径字面一致（如 ``/api/datasets/{id}``）。
``core/urls.py`` 中本 include 必须放在 ``organizations.urls`` **之前**，
确保 aoi 的 ``/api/*`` 优先匹配（见 CHANGES.md 注入点 2）。

末尾的 ``slash_fallback`` 用于兜住 LS ``APPEND_SLASH`` 中间件对 404 的二次派发
（带尾斜杠的 URL 会被内部派发回无尾斜杠的真实路由，保住 ``40401`` 信封）。
"""

from aoi.common.urls import slash_fallback
from aoi.core import auth as auth_views
from aoi.core import heidi_tips as heidi_tips_views
from aoi.pages import AOI_SPA_PAGES, aoi_spa_page
from django.urls import include, path, re_path

#: aoi 业务前缀（**不含 auth**：`/api/auth/` 下混有上游端点 `/api/auth/export/`，
#: 通配会把上游导出鉴权端点吞成 404——D4 实测修复）
AOI_PREFIXES = 'core|datasets|train|prelabel|review|system|ingest'
#: aoi 的 auth 端点只有这两个，兜底逐个点名，不放通配
AOI_AUTH_ENDPOINTS = 'login|logout'

urlpatterns = [
    # 认证端点（D3 认证链路标准化）：与上游 /api/token/*（PAT/刷新/吊销）并存
    path('api/auth/login', auth_views.AoiLoginView.as_view(), name='aoi-auth-login'),
    path('api/auth/logout', auth_views.AoiLogoutView.as_view(), name='aoi-auth-logout'),
    # LS 原生 heidi-tips 代理（core/urls.py 中同名的上游路由）会被本路由遮蔽：
    # 上游实现实时代理 GitHub raw 的营销文案，联网时会把英文文案写回前端缓存（D4）
    path('heidi-tips/', heidi_tips_views.HeidiTipsView.as_view(), name='aoi-heidi-tips'),
    path('api/core', include('aoi.core.urls')),
    path('api/datasets', include('aoi.datasets.urls')),
    path('api/train', include('aoi.training.urls')),
    path('api/prelabel', include('aoi.prelabel.urls')),
    path('api/review', include('aoi.review.urls')),
    path('api/system', include('aoi.audit.urls')),
    path('api/ingest', include('aoi.review.ingest_urls')),
    # aoi SPA 页面（契约 §2.2，H22）：点名注册，非泛 catch-all（见 aoi.pages 模块注释）
    re_path(rf'^(?P<page>{AOI_SPA_PAGES})/?$', aoi_spa_page, name='aoi-spa-page'),
    # 必须放在最后：只接管「同一 aoi 路由 + 尾斜杠」的二次派发
    re_path(
        rf'^(?P<aoi_path>api/(?:(?:{AOI_PREFIXES})/.+|auth/(?:{AOI_AUTH_ENDPOINTS})))/$',
        slash_fallback,
        name='aoi-slash-fallback',
    ),
]
