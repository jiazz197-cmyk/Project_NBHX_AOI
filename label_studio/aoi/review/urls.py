"""``/api/review/*`` 路由（契约 §4.4）。"""

from aoi.review import views
from django.urls import path

app_name = 'aoi_review'

urlpatterns = [
    path('/workitems', views.WorkitemListView.as_view(), name='workitem-list'),
    path('/workitems/<int:id>/claim', views.WorkitemClaimView.as_view(), name='workitem-claim'),
    path('/workitems/<int:id>/finalize', views.WorkitemFinalizeView.as_view(), name='workitem-finalize'),
    path('/suggestions', views.SuggestionListView.as_view(), name='suggestion-list'),
    path('/suggestions/batch-confirm', views.SuggestionBatchConfirmView.as_view(), name='suggestion-batch-confirm'),
    path('/bad-images', views.BadImageListView.as_view(), name='bad-image-list'),
    path('/bad-images/<int:id>/handle', views.BadImageHandleView.as_view(), name='bad-image-handle'),
]
