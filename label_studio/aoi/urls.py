"""aoi 二开路由汇总（由 ``core/urls.py`` 一行注入）。

前缀**不带尾斜杠**，与契约 §4 的路径字面一致（如 ``/api/datasets/{id}``）。
``core/urls.py`` 中本 include 必须放在 ``organizations.urls`` **之前**，
确保 aoi 的 ``/api/*`` 优先匹配（见 CHANGES.md 注入点 2）。

末尾的 ``slash_fallback`` 用于兜住 LS ``APPEND_SLASH`` 中间件对 404 的二次派发
（带尾斜杠的 URL 会被内部派发回无尾斜杠的真实路由，保住 ``40401`` 信封）。
"""

from aoi.common.urls import slash_fallback
from django.urls import include, path, re_path

#: aoi 前缀（slash_fallback 只接管这些前缀，不碰上游路由）
AOI_PREFIXES = 'core|datasets|train|prelabel|review|system|ingest'

urlpatterns = [
    path('api/core', include('aoi.core.urls')),
    path('api/datasets', include('aoi.datasets.urls')),
    path('api/train', include('aoi.training.urls')),
    path('api/prelabel', include('aoi.prelabel.urls')),
    path('api/review', include('aoi.review.urls')),
    path('api/system', include('aoi.audit.urls')),
    path('api/ingest', include('aoi.review.ingest_urls')),
    # 必须放在最后：只接管「同一 aoi 路由 + 尾斜杠」的二次派发
    re_path(rf'^(?P<aoi_path>api/(?:{AOI_PREFIXES})/.+)/$', slash_fallback, name='aoi-slash-fallback'),
]
