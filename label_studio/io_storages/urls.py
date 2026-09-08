"""This file and its contents are licensed under the Apache License 2.0. Please see the included NOTICE for copyright information and LICENSE for a copy of the license."""

from django.conf import settings
from django.urls import include, path, re_path
from io_storages import proxy_api
from io_storages.all_api import (
    AllExportStorageListAPI,
    AllExportStorageTypesAPI,
    AllImportStorageListAPI,
    AllImportStorageTypesAPI,
)
from io_storages.api import ImportStorageListFilesAPI
from io_storages.localfiles.api import (
    LocalFilesExportStorageDetailAPI,
    LocalFilesExportStorageFormLayoutAPI,
    LocalFilesExportStorageListAPI,
    LocalFilesExportStorageSyncAPI,
    LocalFilesExportStorageValidateAPI,
    LocalFilesImportStorageDetailAPI,
    LocalFilesImportStorageFormLayoutAPI,
    LocalFilesImportStorageListAPI,
    LocalFilesImportStorageSerializer,
    LocalFilesImportStorageSyncAPI,
    LocalFilesImportStorageValidateAPI,
)
from io_storages.localfiles.views import localfiles_data
from io_storages.react_code_proxy import ReactCodeResolveView, ReactCodeTokenView

app_name = 'storages'

# IO Storages CRUD: AOI 二开仅保留 localfiles/上传导入
_api_urlpatterns = [
    path('', AllImportStorageListAPI.as_view(), name='storage-list'),
    path('export', AllExportStorageListAPI.as_view(), name='export-storage-list'),
    path('types', AllImportStorageTypesAPI.as_view(), name='storage-types'),
    path('export/types', AllExportStorageTypesAPI.as_view(), name='export-storage-types'),
]

if settings.ENABLE_LOCAL_FILES_STORAGE:
    _api_urlpatterns += [
        # Local files
        path('localfiles/', LocalFilesImportStorageListAPI.as_view(), name='storage-localfiles-list'),
        path('localfiles/<int:pk>', LocalFilesImportStorageDetailAPI.as_view(), name='storage-localfiles-detail'),
        path('localfiles/<int:pk>/sync', LocalFilesImportStorageSyncAPI.as_view(), name='storage-localfiles-sync'),
        path('localfiles/validate', LocalFilesImportStorageValidateAPI.as_view(), name='storage-localfiles-validate'),
        path('localfiles/form', LocalFilesImportStorageFormLayoutAPI.as_view(), name='storage-localfiles-form'),
        path(
            'localfiles/files',
            ImportStorageListFilesAPI().as_view(serializer_class=LocalFilesImportStorageSerializer),
            name='storage-localfiles-list-files',
        ),
        path('export/localfiles', LocalFilesExportStorageListAPI.as_view(), name='export-storage-localfiles-list'),
        path(
            'export/localfiles/<int:pk>',
            LocalFilesExportStorageDetailAPI.as_view(),
            name='export-storage-localfiles-detail',
        ),
        path(
            'export/localfiles/<int:pk>/sync',
            LocalFilesExportStorageSyncAPI.as_view(),
            name='export-storage-localfiles-sync',
        ),
        path(
            'export/localfiles/validate',
            LocalFilesExportStorageValidateAPI.as_view(),
            name='export-storage-localfiles-validate',
        ),
        path(
            'export/localfiles/form',
            LocalFilesExportStorageFormLayoutAPI.as_view(),
            name='export-storage-localfiles-form',
        ),
    ]

urlpatterns = [
    path('api/storages/', include((_api_urlpatterns, app_name), namespace='api')),
]

# URI Resolving: proxy or redirect to presigned URLs
urlpatterns += [
    path('tasks/<int:task_id>/resolve/', proxy_api.TaskResolveStorageUri.as_view(), name='task-storage-data-resolve'),
    path(
        'projects/<int:project_id>/resolve/',
        proxy_api.ProjectResolveStorageUri.as_view(),
        name='project-storage-data-resolve',
    ),
    path('tasks/<int:task_id>/presign/', proxy_api.TaskResolveStorageUri.as_view(), name='task-storage-data-presign'),
    path(
        'projects/<int:project_id>/presign/',
        proxy_api.ProjectResolveStorageUri.as_view(),
        name='project-storage-data-presign',
    ),
]

# ReactCode token-authenticated proxy for sandboxed iframe storage URL resolution
urlpatterns += [
    path('api/react-code/token/', ReactCodeTokenView.as_view(), name='react-code-token'),
    path('api/react-code/resolve/<str:token>/', ReactCodeResolveView.as_view(), name='react-code-resolve'),
]

urlpatterns += [
    re_path(r'data/local-files/', localfiles_data, name='localfiles_data'),
]
