"""aoi_core 授权判定与缓存（契约 §3.1）。

判定链 ``user_role → role_permission → permission.code``；结果按 ``(user_id, version)``
缓存 5 分钟。``authz_state.version`` 与授权变更在同一事务内 +1，判定侧**每请求读一次**版本号，
因此即便 ``CACHES`` 未配置（Django 默认 LocMemCache，多 worker 进程间不共享）也**零延迟失效**。
"""

from __future__ import annotations

import logging

from django.core.cache import cache
from django.db import transaction
from django.db.models import F
from django.utils import timezone

logger = logging.getLogger(__name__)

__all__ = [
    'PERMS_CACHE_TTL',
    'current_version',
    'bump_version',
    'resolve_user_perms',
    'role_codes_for_user',
]

#: 契约 §3.1：权限判定结果按用户缓存 5 分钟
PERMS_CACHE_TTL = 300

_STATE_ID = 1


def current_version() -> int:
    """读授权版本号（单行 PK 查询；每请求一次）。"""
    from aoi.core.models import AuthzState

    version = AuthzState.objects.filter(pk=_STATE_ID).values_list('version', flat=True).first()
    if version is None:
        # authz_state 缺失＝未播种（或表被清空）：此时全站 aoi 视图都会 40300，必须显式告警。
        logger.error('aoi_core.authz_state missing: RBAC 未初始化，请运行 `manage.py aoi_seed_rbac`')
        return 0
    return int(version)


def bump_version() -> int:
    """授权变更时 +1（**必须与变更在同一事务内调用**），返回新版本号。"""
    from aoi.core.models import AuthzState

    with transaction.atomic():
        updated = AuthzState.objects.filter(pk=_STATE_ID).update(version=F('version') + 1, updated_at=timezone.now())
        if not updated:
            AuthzState.objects.create(id=_STATE_ID, version=1, updated_at=timezone.now())
    return current_version()


def _cache_key(user_id: int, version: int) -> str:
    return f'aoi:perms:{user_id}:{version}'


def resolve_user_perms(user_id: int | None) -> frozenset[str]:
    """返回用户权限码集合；无角色、用户不存在或未登录 → 空集。"""
    if not user_id:
        return frozenset()

    key = _cache_key(user_id, current_version())
    cached = cache.get(key)
    if cached is not None:
        return frozenset(cached)

    from aoi.core.models import Permission, RolePermission, UserRole
    from django.contrib.auth import get_user_model

    perms: frozenset[str] = frozenset()
    if get_user_model().objects.filter(pk=user_id).exists():
        role_ids = list(UserRole.objects.filter(user_id=user_id).values_list('role_id', flat=True))
        if role_ids:
            perm_ids = list(
                RolePermission.objects.filter(role_id__in=role_ids).values_list('permission_id', flat=True)
            )
            if perm_ids:
                perms = frozenset(Permission.objects.filter(id__in=perm_ids).values_list('code', flat=True))

    cache.set(key, tuple(perms), PERMS_CACHE_TTL)
    return perms


def role_codes_for_user(user_id: int | None) -> list[str]:
    """返回用户角色 code 列表（按 role.id 升序）；用户不存在 → 空列表。"""
    if not user_id:
        return []

    from aoi.core.models import Role, UserRole
    from django.contrib.auth import get_user_model

    if not get_user_model().objects.filter(pk=user_id).exists():
        return []
    role_ids = list(UserRole.objects.filter(user_id=user_id).values_list('role_id', flat=True))
    if not role_ids:
        return []
    return list(Role.objects.filter(id__in=role_ids).order_by('id').values_list('code', flat=True))
