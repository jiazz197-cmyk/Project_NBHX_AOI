"""``/api/prelabel/*`` 路由（契约 §4.3）。"""

from aoi.prelabel import views
from django.urls import path

app_name = 'aoi_prelabel'

urlpatterns = [
    path('/tasks', views.PrelabelTaskListCreateView.as_view(), name='task-list'),
    path('/tasks/<int:task_id>', views.PrelabelTaskDetailView.as_view(), name='task-detail'),
    path('/<int:task_id>/health', views.PrelabelHealthView.as_view(), name='health'),
    path('/<int:task_id>/setup', views.PrelabelSetupView.as_view(), name='setup'),
    path('/<int:task_id>/predict', views.PrelabelPredictView.as_view(), name='predict'),
    path('/<int:task_id>/validate', views.PrelabelValidateView.as_view(), name='validate'),
    path('/<int:task_id>/webhook', views.PrelabelWebhookView.as_view(), name='webhook'),
]
