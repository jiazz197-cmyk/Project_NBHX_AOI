from django.apps import AppConfig


class AoiCommonConfig(AppConfig):
    name = 'aoi.common'
    label = 'aoi_common'
    verbose_name = 'AOI Common'
    default_auto_field = 'django.db.models.AutoField'

    def ready(self) -> None:
        # 注册 Bearer JWT 的 OpenAPI securityScheme（drf-spectacular 扩展按导入注册）。
        # 放在 ready()：settings 导入期不能碰 drf_spectacular/rest_framework.schemas 的 eager import 链。
        from aoi.common import schema  # noqa: F401
