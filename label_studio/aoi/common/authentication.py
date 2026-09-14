"""aoi DRF 认证类：Bearer JWT（``DEFAULT_AUTHENTICATION_CLASSES`` 用）。

为什么需要这层薄代理
--------------------
``core/settings/label_studio.py`` 在 **settings 导入期**就 ``import core.utils.common`` →
``rest_framework.views`` → ``rest_framework.schemas``；而 ``rest_framework/schemas/__init__.py``
会在模块级立即 import ``DEFAULT_AUTHENTICATION_CLASSES`` 里的每一项
（``authentication_classes=api_settings.DEFAULT_AUTHENTICATION_CLASSES``）。

``rest_framework_simplejwt.authentication`` 在模块级 ``from django.contrib.auth.models import
AbstractBaseUser``，此刻 app registry 尚未 ready，直接抛 ``AppRegistryNotReady``。
因此本模块**只依赖 ``rest_framework.authentication``**（settings 期可安全导入），
把 simplejwt 的 import 推迟到第一次真实认证。

行为与 ``rest_framework_simplejwt.authentication.JWTAuthentication`` 完全一致（原样代理）。
"""

from __future__ import annotations

from rest_framework.authentication import BaseAuthentication

__all__ = ['AoiJWTAuthentication']


class AoiJWTAuthentication(BaseAuthentication):
    """Bearer JWT 认证（延迟导入 simplejwt 实现，绕开 settings 期的 AppRegistryNotReady）。"""

    @staticmethod
    def _impl():
        from rest_framework_simplejwt.authentication import JWTAuthentication

        return JWTAuthentication()

    def authenticate(self, request):
        return self._impl().authenticate(request)

    def authenticate_header(self, request) -> str:
        return self._impl().authenticate_header(request)
