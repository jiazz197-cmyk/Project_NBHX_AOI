"""``/api/ingest/*`` 路由（契约 §4.6）。"""

from aoi.review import ingest
from django.urls import path

app_name = 'aoi_ingest'

urlpatterns = [
    path('/findings', ingest.IngestFindingsView.as_view(), name='findings'),
]
