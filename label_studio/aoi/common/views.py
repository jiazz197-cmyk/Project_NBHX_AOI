"""aoi 视图基类：统一信封、request_id、异常 → 错误码。

红线：**不改全局 ``REST_FRAMEWORK``**（``EXCEPTION_HANDLER``/权限类是上游语义），
信封与异常只在 aoi 基类/视图层生效（计划 §3 T1.3）。
"""

from __future__ import annotations

import logging
import uuid
from typing import Any

from aoi.common.envelope import ok as envelope_ok
from aoi.common.errors import (
    CODE_BAD_REQUEST,
    CODE_BY_HTTP_STATUS,
    CODE_CONFLICT,
    CODE_FORBIDDEN,
    CODE_INTERNAL,
    CODE_NOT_FOUND,
    CODE_UNAUTHORIZED,
    CODE_UNPROCESSABLE,
    AoiError,
)
from aoi.common.permissions import aoi_permission
from aoi.common.serializers import EmptySerializer
from django.core.exceptions import PermissionDenied as DjangoPermissionDenied
from django.db import IntegrityError
from django.http import Http404
from rest_framework import exceptions, status
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

logger = logging.getLogger(__name__)

__all__ = ['AoiAPIView', 'request_id_from_request']


def request_id_from_request(request: Any) -> str:
    """``X-Request-ID`` 优先，否则生成 ``req-<uuid12>``（契约 §2.5）。"""
    raw = request.headers.get('X-Request-ID') if request is not None else None
    if raw:
        return raw.strip()
    return f'req-{uuid.uuid4().hex[:12]}'


class AoiAPIView(APIView):
    """aoi 二开视图基类。

    - 显式 ``permission_classes=[IsAuthenticated]``，覆盖全局 ``HasObjectPermission``；
    - ``aoi_perm`` / ``aoi_perm_by_method`` 声明契约 §3.1 的权限点（D4 起由 ``AoiPermission``
      按用户角色判定；D1–D2 恒放行，仅要求登录 → 匿名 40100）；
    - 成功/失败统一走信封；异常统一映射错误码；
    - 响应头回填 ``X-Request-ID``。
    """

    permission_classes = [IsAuthenticated]
    #: 本视图对应的权限点（如 ``training.publish``）；``None`` 表示"仅需登录"（如 /api/core/permissions）
    aoi_perm: str | None = None
    #: 读写同视图时按 HTTP 方法覆盖 ``aoi_perm``（如 ``{'POST': 'datasets.create'}``）
    aoi_perm_by_method: dict[str, str] = {}
    # D1–D2 stub：给 drf-spectacular 一个可用的 serializer_class，保证 aoi 路径进入 OpenAPI
    serializer_class = EmptySerializer

    def get_permissions(self):
        code = self.aoi_perm_by_method.get(getattr(self.request, 'method', ''), self.aoi_perm)
        if code:
            return [aoi_permission(code)()]
        return super().get_permissions()

    # ------------------------------------------------------------------ helpers
    @property
    def request_id(self) -> str:
        if not hasattr(self, '_aoi_request_id'):
            self._aoi_request_id = request_id_from_request(getattr(self, 'request', None))
            if getattr(self, 'request', None) is not None:
                self.request.request_id = self._aoi_request_id
        return self._aoi_request_id

    @property
    def user_id(self) -> int | None:
        user = getattr(getattr(self, 'request', None), 'user', None)
        if user is None or not getattr(user, 'is_authenticated', False):
            return None
        return getattr(user, 'id', None)

    # ------------------------------------------------------------- responses
    def ok(self, data: Any = None, *, message: str = 'ok', status_code: int = status.HTTP_200_OK) -> Response:
        return Response(envelope_ok(data, message=message, request_id=self.request_id), status=status_code)

    def created(self, data: Any = None, *, message: str = 'ok') -> Response:
        return self.ok(data, message=message, status_code=status.HTTP_201_CREATED)

    def fail(self, error: AoiError) -> Response:
        return Response(error.as_response_data(self.request_id), status=error.http_status)

    # -------------------------------------------------------------- exceptions
    def handle_exception(self, exc: Exception) -> Response:
        error = self._to_aoi_error(exc)
        if error.http_status >= 500:
            logger.exception('aoi internal error request_id=%s path=%s', self.request_id, self.request.path)
        return self.fail(error)

    def _to_aoi_error(self, exc: Exception) -> AoiError:
        if isinstance(exc, AoiError):
            return exc
        if isinstance(exc, exceptions.ValidationError):
            fields = exc.detail if isinstance(exc.detail, dict) else {'non_field_errors': exc.detail}
            return AoiError(CODE_UNPROCESSABLE, 'validation failed', fields=fields)
        # Django 原生异常（不是 DRF APIException），必须显式映射，否则会落成 50000
        if isinstance(exc, Http404):
            return AoiError(CODE_NOT_FOUND, 'not found')
        if isinstance(exc, DjangoPermissionDenied):
            return AoiError(CODE_FORBIDDEN, 'forbidden')
        if isinstance(exc, exceptions.NotAuthenticated):
            return AoiError(CODE_UNAUTHORIZED, 'authentication credentials were not provided')
        if isinstance(exc, exceptions.AuthenticationFailed):
            return AoiError(CODE_UNAUTHORIZED, str(exc.detail))
        if isinstance(exc, exceptions.PermissionDenied):
            return AoiError(CODE_FORBIDDEN, str(exc.detail))
        if isinstance(exc, exceptions.NotFound):
            return AoiError(CODE_NOT_FOUND, str(exc.detail))
        if isinstance(exc, IntegrityError):
            return AoiError(CODE_CONFLICT, 'database conflict')
        if isinstance(exc, exceptions.APIException):
            # 按 HTTP 状态反查契约错误码（429→42900、503→50300，B 侧据此判定可重试）
            code = CODE_BY_HTTP_STATUS.get(exc.status_code, CODE_BAD_REQUEST)
            detail = exc.detail
            fields = detail if isinstance(detail, dict) else None
            return AoiError(code, str(detail), fields=fields, http_status=exc.status_code)
        return AoiError(CODE_INTERNAL, 'internal error')

    # ---------------------------------------------------------------- response
    def finalize_response(self, request, response, *args, **kwargs):
        response = super().finalize_response(request, response, *args, **kwargs)
        if not response.has_header('X-Request-ID'):
            response['X-Request-ID'] = self.request_id
        return response
