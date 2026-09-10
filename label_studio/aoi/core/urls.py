"""``/api/core/*`` 路由（契约 §4.0）。"""

from aoi.core import views
from django.urls import path

app_name = 'aoi_core'

urlpatterns = [
    path('/permissions', views.PermissionsView.as_view(), name='permissions'),
    path('/roles', views.RoleListCreateView.as_view(), name='role-list'),
    path('/roles/<int:id>', views.RoleDetailView.as_view(), name='role-detail'),
    path('/users/<int:id>/roles', views.UserRolesView.as_view(), name='user-roles'),
]
