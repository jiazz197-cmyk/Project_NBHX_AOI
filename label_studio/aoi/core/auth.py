"""API 认证端点：登录 / 登出（认证链路标准化，见 CHANGES.md「认证链路」）。

分工
----
- ``POST /api/auth/login``  —— **匿名可访问**：``email`` + ``password`` → ``access`` / ``refresh`` JWT；
  凭据校验先走 LS 的 ``settings.USER_AUTH`` 钩子（LDAP 等自定义后端），再回退 Django 认证后端，
  与浏览器登录 ``users/forms.py::LoginForm`` **完全同源**（契约 §2.4「只复用 LS 的账户与登录」）。
- ``POST /api/auth/logout`` —— **登录可访问**：把 ``refresh`` 加入 simplejwt 黑名单（幂等）。
- 令牌刷新/吊销沿用上游既有端点 ``/api/token/refresh|blacklist|rotate``（``jwt_auth.urls``，未修改）；
  ``/api/token/``（PAT 创建）语义不变。

Bearer 的校验位置
-----------------
由 ``REST_FRAMEWORK.DEFAULT_AUTHENTICATION_CLASSES`` 中的
``rest_framework_simplejwt.authentication.JWTAuthentication`` 完成（标准 DRF 认证链），
上游的 ``jwt_auth.middleware.JWTAuthenticationMiddleware`` 已从 ``MIDDLEWARE`` 移除。
"""

from __future__ import annotations

import logging
from typing import Any

from aoi.common.errors import CODE_FORBIDDEN, CODE_UNAUTHORIZED, CODE_UNPROCESSABLE, AoiError
from aoi.common.views import AoiAPIView
from django.conf import settings
from django.contrib.auth import authenticate, get_user_model
from django.contrib.auth.models import update_last_login
from drf_spectacular.utils import extend_schema
from rest_framework import serializers
from rest_framework.permissions import AllowAny
from rest_framework_simplejwt.exceptions import TokenError
from rest_framework_simplejwt.serializers import TokenObtainPairSerializer
from rest_framework_simplejwt.settings import api_settings as simplejwt_settings
from rest_framework_simplejwt.tokens import RefreshToken

logger = logging.getLogger(__name__)

User = get_user_model()

__all__ = [
    'AoiLoginSerializer',
    'AoiLoginView',
    'AoiLogoutSerializer',
    'AoiLogoutView',
    'AoiTokenPairSerializer',
    'authenticate_with_ls_chain',
]


# --------------------------------------------------------------------------- helpers
def authenticate_with_ls_chain(email: str, password: str):
    """与浏览器登录同源的凭据校验：``settings.USER_AUTH`` 优先，其次 Django 认证后端。

    返回可用的 ``User``；凭据错误、账号不存在或已停用一律返回 ``None``
    （调用方统一抛 40100，不区分「用户不存在 / 密码错误」）。
    """
    user = None
    user_auth = getattr(settings, 'USER_AUTH', None)
    if callable(user_auth):
        try:
            user = user_auth(User, email, password)
        except Exception:  # 自定义后端异常不应把 500 暴露给登录端点
            logger.exception('USER_AUTH hook raised for email=%s', email)
            user = None
    if user is None:
        user = authenticate(email=email, password=password)
    if user is None or not getattr(user, 'is_active', False):
        return None
    return user


def _field_errors(errors: Any) -> dict[str, str]:
    """DRF serializer.errors → ``{field: message}``（契约 ``data.detail.fields`` 形状）。"""
    flat: dict[str, str] = {}
    for field, messages in dict(errors).items():
        if isinstance(messages, (list, tuple)):
            flat[field] = '; '.join(str(message) for message in messages)
        else:
            flat[field] = str(messages)
    return flat


# ------------------------------------------------------------------------- serializers
class AoiLoginUserSerializer(serializers.Serializer):
    id = serializers.IntegerField()
    email = serializers.EmailField()


class AoiTokenPairSerializer(serializers.Serializer):
    """登录成功响应体（信封 ``data``）。"""

    access = serializers.CharField()
    refresh = serializers.CharField()
    token_type = serializers.CharField()
    expires_in = serializers.IntegerField()
    user = AoiLoginUserSerializer()


class AoiLoginSerializer(TokenObtainPairSerializer):
    """``email`` + ``password`` → ``{access, refresh}``。

    仅替换凭据校验部分（``USER_AUTH`` 钩子 + Django 后端），其余（字段定义、``UPDATE_LAST_LOGIN``、
    令牌签发）沿用 simplejwt 的 ``TokenObtainPairSerializer`` 行为。
    """

    def validate(self, attrs: dict[str, Any]) -> dict[str, str]:
        email = attrs.get(self.username_field)
        password = attrs.get('password')
        user = authenticate_with_ls_chain(email, password)
        if user is None:
            logger.info('aoi login rejected: email=%s', email)
            raise AoiError(CODE_UNAUTHORIZED, 'invalid credentials')
        self.user = user
        refresh = self.get_token(user)
        if simplejwt_settings.UPDATE_LAST_LOGIN:
            update_last_login(None, user)
        return {'refresh': str(refresh), 'access': str(refresh.access_token)}


class AoiLogoutSerializer(serializers.Serializer):
    refresh = serializers.CharField(required=False, allow_blank=True)


class AoiLogoutResultSerializer(serializers.Serializer):
    revoked = serializers.BooleanField()


# ------------------------------------------------------------------------------- views
@extend_schema(
    tags=['aoi-auth'],
    summary='API 登录',
    description=(
        'email + password 换取 access/refresh JWT（匿名可访问）。'
        '凭据校验与浏览器登录同源；失败返回 40100，字段缺失返回 42200。'
    ),
    request=AoiLoginSerializer,
    responses={200: AoiTokenPairSerializer},
)
class AoiLoginView(AoiAPIView):
    """``POST /api/auth/login``（契约 §4.0）。"""

    # 登录端点本身不做认证：带过期/错误 Bearer 也应能重新登录
    authentication_classes: list = []
    permission_classes = [AllowAny]
    serializer_class = AoiLoginSerializer

    def post(self, request):
        serializer = self.serializer_class(data=request.data, context={'request': request})
        if not serializer.is_valid():
            raise AoiError(CODE_UNPROCESSABLE, 'validation failed', fields=_field_errors(serializer.errors))
        data = serializer.validated_data
        user = serializer.user
        return self.ok(
            {
                'access': data['access'],
                'refresh': data['refresh'],
                'token_type': 'Bearer',
                'expires_in': int(simplejwt_settings.ACCESS_TOKEN_LIFETIME.total_seconds()),
                'user': {'id': user.id, 'email': user.email},
            }
        )


@extend_schema(
    tags=['aoi-auth'],
    summary='登出',
    description='把 refresh 令牌加入黑名单（幂等：无效/已吊销的令牌同样返回 200，``revoked=false``）。',
    request=AoiLogoutSerializer,
    responses={200: AoiLogoutResultSerializer},
)
class AoiLogoutView(AoiAPIView):
    """``POST /api/auth/logout``（契约 §4.0）；仅需登录，权限点留空。"""

    serializer_class = AoiLogoutSerializer

    def post(self, request):
        serializer = self.serializer_class(data=request.data)
        if not serializer.is_valid():
            raise AoiError(CODE_UNPROCESSABLE, 'validation failed', fields=_field_errors(serializer.errors))

        raw_refresh = serializer.validated_data.get('refresh') or ''
        if not raw_refresh:
            return self.ok({'revoked': False}, message='no refresh token supplied')

        try:
            token = RefreshToken(raw_refresh)
        except TokenError:
            logger.info('logout: refresh invalid or already revoked (user_id=%s)', self.user_id)
            return self.ok({'revoked': False}, message='refresh token invalid or already revoked')

        if int(token.get('user_id') or 0) != int(self.user_id or 0):
            raise AoiError(CODE_FORBIDDEN, 'refresh token does not belong to the current user')

        try:
            token.blacklist()
        except TokenError:
            return self.ok({'revoked': False}, message='refresh token invalid or already revoked')
        return self.ok({'revoked': True})
