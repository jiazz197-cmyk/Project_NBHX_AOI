"""``/api/system/*`` 路由（契约 §4.5）。"""

from aoi.audit import views
from django.urls import path

app_name = 'aoi_audit'

urlpatterns = [
    path('/audit', views.AuditListView.as_view(), name='audit-list'),
]
