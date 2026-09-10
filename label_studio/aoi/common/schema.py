"""drf-spectacular 扩展：把 Bearer JWT 认证类映射为 OpenAPI securityScheme。

只在 ``AoiCommonConfig.ready()`` 里导入（app registry ready 之后），
避免 settings 导入期触碰 ``rest_framework.schemas`` 的 eager import 链。

对应设置：``SPECTACULAR_SETTINGS['AUTHENTICATION_WHITELIST']`` 必须包含
``aoi.common.authentication.AoiJWTAuthentication``，否则 drf-spectacular 不会为它生成安全方案
（并且会在日志里给一条 "could not resolve authenticator" 警告）。
"""

from __future__ import annotations

from drf_spectacular.extensions import OpenApiAuthenticationExtension

__all__ = ['AoiBearerAuthScheme']


class AoiBearerAuthScheme(OpenApiAuthenticationExtension):
    target_class = 'aoi.common.authentication.AoiJWTAuthentication'
    name = 'Bearer'

    def get_security_definition(self, auto_schema):
        return {
            'type': 'http',
            'scheme': 'bearer',
            'bearerFormat': 'JWT',
            'description': (
                '先 ``POST /api/auth/login``（email + password）取得 ``access``，'
                '再以 ``Authorization: Bearer <access>`` 调用业务接口；'
                '``access`` 默认 30 分钟，用 ``POST /api/token/refresh/`` 续期。'
            ),
        }
