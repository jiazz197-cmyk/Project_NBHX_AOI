"""``/api/datasets/*`` 路由（契约 §4.1；T2.9：CRUD 路径为 ``/api/datasets`` + ``/api/datasets/{id}``）。"""

from aoi.datasets import views
from django.urls import path

app_name = 'aoi_datasets'

urlpatterns = [
    # 字面量优先；前缀不含尾斜杠，子路由以 / 开头（与契约路径字面一致）
    path('/import', views.ImportCreateView.as_view(), name='import-create'),
    path('/import/<str:job_id>', views.ImportDetailView.as_view(), name='import-detail'),
    path('/images', views.ImageListView.as_view(), name='image-list'),
    path('/images/<int:id>', views.ImageDetailView.as_view(), name='image-detail'),
    path('/images/<int:id>/download', views.ImageDownloadView.as_view(), name='image-download'),
    path('/defects/publish', views.DefectPublishView.as_view(), name='defect-publish'),
    path('/defects/versions', views.DefectVersionListView.as_view(), name='defect-versions'),
    path('/defects', views.DefectListCreateUpdateView.as_view(), name='defect-list'),
    path('/annotation-stats', views.AnnotationStatsView.as_view(), name='annotation-stats'),
    # datasets CRUD（T2.9 裁定：/api/datasets 与 /api/datasets/{id}）
    path('', views.DatasetListCreateView.as_view(), name='dataset-list'),
    path('/<int:id>', views.DatasetDetailView.as_view(), name='dataset-detail'),
    path('/<int:id>/versions', views.DatasetVersionCreateView.as_view(), name='dataset-version-create'),
    path('/<int:id>/versions/<str:v>/export', views.DatasetExportView.as_view(), name='dataset-export'),
]
