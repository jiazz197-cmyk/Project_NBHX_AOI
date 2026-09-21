"""LS 原生闸门（契约 §3.1.1）。

RBAC 只覆盖 aoi 视图；LS 原生端点在 LSO 下等价于「登录即可写」（`projects/mixins.py::has_permission`
只检查是否被移出组织），因此按 **deny-list** 拦截 4 类高危写操作。

- **默认放行**：不在 :data:`DENY_RULES` 内的路径一律放行；标注 / Data Manager / 上传 / current-user
  全部不受影响（用 allow-list 会让标注主流程直接不可用）。
- **fail-open**：闸门自身异常一律放行并告警——加固手段不得因自身缺陷锁死平台。
- 插在 ``REST_FRAMEWORK.DEFAULT_PERMISSION_CLASSES`` **首位**（`core/settings/base.py` 注入点 1）；
  之所以不用 Django 中间件：D3 已移除 JWT 中间件，中间件里 ``request.user`` 只有 session 身份。
- 拒绝时抛 DRF ``PermissionDenied`` → 上游 ``custom_exception_handler`` 返回 **LS 方言**
  ``{"detail": ...}``（不是 aoi 信封，契约 §3.1.1）。
"""

from __future__ import annotations

import logging
import re
from typing import NamedTuple

from rest_framework.permissions import BasePermission

logger = logging.getLogger(__name__)

__all__ = ['DENY_RULES', 'AoiNativeGatePermission']


class _Rule(NamedTuple):
    methods: frozenset[str]
    pattern: re.Pattern[str]
    perm_code: str


#: ``(methods, path regex, perm code)``；`methods` 用 ``|`` 分隔
DENY_RULES: tuple[tuple[str, str, str], ...] = (
    # ① 项目删除 / 配置改写（含 label config；reimport 触发也走 PATCH 项目）
    ('DELETE', r'^/api/projects/\d+/?$', 'datasets.delete'),
    ('PATCH|PUT', r'^/api/projects/\d+/?$', 'datasets.config'),
    ('POST', r'^/api/projects/\d+/summary/reset/?$', 'datasets.config'),
    # ② 导出（含导出产物读取）
    ('POST', r'^/api/projects/\d+/export/?$', 'datasets.export'),
    ('POST', r'^/api/projects/\d+/exports/?$', 'datasets.export'),
    ('DELETE', r'^/api/projects/\d+/exports/\d+/?$', 'datasets.export'),
    ('POST', r'^/api/projects/\d+/exports/\d+/convert/?$', 'datasets.export'),
    ('GET', r'^/api/projects/\d+/export/files/?$', 'datasets.export'),
    ('GET', r'^/api/auth/export/?$', 'datasets.export'),
    # ③ 基础设施配置（写方法）
    ('POST|PATCH|PUT|DELETE', r'^/api/storages/', 'system.storage'),
    ('POST|PATCH|PUT|DELETE', r'^/api/ml/', 'system.ml'),
    ('POST|PATCH|PUT|DELETE', r'^/api/webhooks/', 'system.webhook'),
    ('POST|PATCH|PUT|DELETE', r'^/api/labels/', 'system.labels'),
    # ④ 组织与用户（写方法）
    ('POST|PATCH|PUT|DELETE', r'^/api/organizations/', 'system.users'),
    ('POST', r'^/api/invite/?$', 'system.users'),
    ('POST', r'^/api/invite/reset-token/?$', 'system.users'),
    ('POST|PATCH|PUT|DELETE', r'^/api/users/', 'system.users'),
    # ⑤ 权限锚点（非高危；operator 持 datasets.create → 放行）
    ('POST', r'^/api/projects/?$', 'datasets.create'),
)

_COMPILED_RULES: tuple[_Rule, ...] = tuple(
    _Rule(frozenset(methods.split('|')), re.compile(pattern), perm_code) for methods, pattern, perm_code in DENY_RULES
)


def _has_perm(request, perm_code: str) -> bool:
    user = getattr(request, 'user', None)
    if user is None or not getattr(user, 'is_authenticated', False):
        return False

    from aoi.core.authz import resolve_user_perms

    return perm_code in resolve_user_perms(getattr(user, 'id', None))


class AoiNativeGatePermission(BasePermission):
    """LS 原生端点闸门（deny-list，默认放行，fail-open）。"""

    def has_permission(self, request, view) -> bool:
        try:
            return self._check(request)
        except Exception:  # pragma: no cover - fail-open
            logger.warning('aoi native gate failed open path=%s', getattr(request, 'path', '?'), exc_info=True)
            return True

    def has_object_permission(self, request, view, obj) -> bool:
        return True

    @staticmethod
    def _check(request) -> bool:
        method = (getattr(request, 'method', '') or '').upper()
        path = getattr(request, 'path', '') or ''
        for rule in _COMPILED_RULES:
            if method in rule.methods and rule.pattern.match(path):
                return _has_perm(request, rule.perm_code)
        return True
