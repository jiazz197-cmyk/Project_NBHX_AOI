"""``/api/train/*`` 路由（契约 §4.2）。"""

from aoi.training import views
from django.urls import path

app_name = 'aoi_training'

urlpatterns = [
    path('/base-models', views.BaseModelListView.as_view(), name='base-models'),
    path('/presets', views.PresetListView.as_view(), name='presets'),
    path('/jobs', views.TrainJobCreateView.as_view(), name='job-create'),
    path('/jobs/<int:id>', views.TrainJobDetailView.as_view(), name='job-detail'),
    path('/jobs/<int:id>/cancel', views.TrainJobCancelView.as_view(), name='job-cancel'),
    path('/jobs/<int:id>/progress', views.TrainJobProgressView.as_view(), name='job-progress'),
    path('/models', views.ModelListView.as_view(), name='model-list'),
    path('/models/<int:id>/approve', views.ModelApproveView.as_view(), name='model-approve'),
    path('/models/<int:id>/publish', views.ModelPublishView.as_view(), name='model-publish'),
]
