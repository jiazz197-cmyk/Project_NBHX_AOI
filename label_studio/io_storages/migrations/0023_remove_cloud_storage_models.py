"""Remove cloud storage provider models.

AOI 二开只保留 local files / upload import; external cloud storage providers
(S3/GCS/Azure/Redis data sources) are removed.
"""

from django.db import migrations

_CLOUD_MODELS = [
    # Links first (they have FKs to concrete storage models)
    "s3importstoragelink",
    "s3exportstoragelink",
    "gcsimportstoragelink",
    "gcsexportstoragelink",
    "azureblobimportstoragelink",
    "azureblobexportstoragelink",
    "redisimportstoragelink",
    "redisexportstoragelink",
    # Concrete storage models
    "s3importstorage",
    "s3exportstorage",
    "gcsimportstorage",
    "gcsexportstorage",
    "azureblobimportstorage",
    "azureblobexportstorage",
    "redisimportstorage",
    "redisexportstorage",
    # Mixin tables
    "azureblobstoragemixin",
    "gcsstoragemixin",
    "redisstoragemixin",
]


class Migration(migrations.Migration):

    dependencies = [
        ("io_storages", "0022_normalize_localfiles_paths"),
    ]

    operations = [
        migrations.DeleteModel(name=name)
        for name in _CLOUD_MODELS
    ]
