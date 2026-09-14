"""aoi.core 端点：权限点查询与角色/授权（契约 §3.1/§4.0）。

D4：进程内占位已由 `aoi_core` 五表替换；判定与缓存见 :mod:`aoi.core.authz`。
所有写操作在**同一事务**内 bump 授权版本号（角色/授权变更零延迟生效）并写审计。
"""

from __future__ import annotations

from aoi.common.audit import write_audit
from aoi.common.errors import CODE_CONFLICT, CODE_NOT_FOUND, CODE_UNPROCESSABLE, AoiError
from aoi.common.pagination import paginate
from aoi.common.views import AoiAPIView
from aoi.core import authz
from aoi.core.models import Permission, Role, RolePermission, UserRole
from aoi.core.permissions import PERMISSION_CODES
from django.contrib.auth import get_user_model
from django.db import transaction
from django.utils import timezone
from drf_spectacular.utils import extend_schema

_KNOWN_PERMISSIONS = frozenset(PERMISSION_CODES)


def _permission_codes_by_role(role_ids: list[int]) -> dict[int, list[str]]:
    """``role_id → [code]``；一次查询取回，避免逐行查询。"""
    codes_by_id = dict(Permission.objects.values_list('id', 'code'))
    result: dict[int, list[str]] = {role_id: [] for role_id in role_ids}
    rows = RolePermission.objects.filter(role_id__in=role_ids).values_list('role_id', 'permission_id')
    for role_id, permission_id in rows:
        code = codes_by_id.get(permission_id)
        if code:
            result[role_id].append(code)
    return {role_id: sorted(codes) for role_id, codes in result.items()}


def _role_payload(role: Role, permissions: list[str]) -> dict:
    return {
        'id': role.id,
        'code': role.code,
        'name_cn': role.name_cn,
        'description': role.description or '',
        'is_builtin': role.is_builtin,
        'permissions': permissions,
    }


def _validated_permissions(payload: dict) -> list[str] | None:
    """校验可选入参 ``permissions``；未提供返回 ``None``，非法抛 42200。"""
    if 'permissions' not in payload:
        return None
    codes = payload.get('permissions') or []
    if not isinstance(codes, (list, tuple)) or any(not isinstance(code, str) for code in codes):
        raise AoiError(CODE_UNPROCESSABLE, 'invalid permissions', fields={'permissions': 'must be a list of strings'})
    unknown = sorted(set(codes) - _KNOWN_PERMISSIONS)
    if unknown:
        raise AoiError(
            CODE_UNPROCESSABLE,
            'unknown permission codes',
            fields={'permissions': f'unknown: {unknown}'},
        )
    return sorted(set(codes))


def _replace_permissions(role_id: int, codes: list[str]) -> None:
    """全量覆盖该角色的 ``role_permission``。"""
    permission_ids = dict(Permission.objects.filter(code__in=codes).values_list('code', 'id'))
    RolePermission.objects.filter(role_id=role_id).delete()
    RolePermission.objects.bulk_create(
        [RolePermission(role_id=role_id, permission_id=permission_ids[code]) for code in codes]
    )


def _active_super_admin_ids() -> set[int]:
    """活跃超管的 ``user_id`` 集合（``is_active=True`` 且持 ``super_admin``）。"""
    from aoi.core.models import Role, UserRole

    super_admin = Role.objects.filter(code='super_admin').first()
    if super_admin is None:
        return set()
    ids = set(UserRole.objects.filter(role_id=super_admin.id).values_list('user_id', flat=True))
    if not ids:
        return set()
    return set(get_user_model().objects.filter(id__in=ids, is_active=True).values_list('id', flat=True))


def _guard_last_super_admin(user_id: int, *, keeps_super_admin: bool) -> None:
    """最后超管守卫（契约 §3.1）：该变更会让活跃超管归零 → 40900。

    ``keeps_super_admin`` 表示变更后目标用户是否仍持 ``super_admin``（roles 覆盖场景）；
    停用场景恒为 ``False``（停用即不活跃）。
    """
    active_ids = _active_super_admin_ids()
    if user_id in active_ids and len(active_ids) == 1 and not keeps_super_admin:
        raise AoiError(
            CODE_CONFLICT,
            'cannot remove the last active super_admin',
            fields={'id': 'last active super_admin'},
        )


@extend_schema(tags=['aoi-core'])
class PermissionsView(AoiAPIView):
    """``GET /api/core/permissions`` → 当前用户角色/权限点（供前端按钮与菜单显隐）。

    唯一豁免权限点的 aoi 视图：无角色用户也应能拿到空的 ``roles``/``perms``。
    """

    def get(self, request):
        user_id = self.user_id
        return self.ok(
            {
                'user_id': user_id,
                'roles': authz.role_codes_for_user(user_id),
                'perms': sorted(authz.resolve_user_perms(user_id)),
            }
        )


@extend_schema(tags=['aoi-core'])
class RoleListCreateView(AoiAPIView):
    """``GET/POST /api/core/roles``（system.roles）。"""

    aoi_perm = 'system.roles'

    def get(self, request):
        roles = list(Role.objects.all().order_by('id'))
        codes_by_role = _permission_codes_by_role([role.id for role in roles])
        items = [_role_payload(role, codes_by_role.get(role.id, [])) for role in roles]
        return self.ok(paginate(request, items))

    def post(self, request):
        payload = request.data if isinstance(request.data, dict) else {}
        code = str(payload.get('code') or '').strip()
        name_cn = str(payload.get('name_cn') or payload.get('name') or '').strip()
        description = str(payload.get('description') or '')
        permissions = _validated_permissions(payload)

        fields = {}
        if not code:
            fields['code'] = 'required'
        elif len(code) > 32:
            fields['code'] = 'must be <= 32 chars'
        elif Role.objects.filter(code=code).exists():
            raise AoiError(CODE_CONFLICT, 'role code already exists', fields={'code': code})
        if not name_cn:
            fields['name_cn'] = 'required'
        elif len(name_cn) > 64:
            fields['name_cn'] = 'must be <= 64 chars'
        if fields:
            raise AoiError(CODE_UNPROCESSABLE, 'invalid role payload', fields=fields)

        with transaction.atomic():
            role = Role.objects.create(
                code=code,
                name_cn=name_cn,
                description=description,
                is_builtin=False,
            )
            if permissions:
                _replace_permissions(role.id, permissions)
            authz.bump_version()
            write_audit(
                actor_id=self.user_id,
                action='role.create',
                object_type='aoi_core.role',
                object_id=str(role.id),
                detail={'code': code, 'permissions': permissions or []},
                request_id=self.request_id,
            )
        return self.ok(_role_payload(role, permissions or []))


@extend_schema(tags=['aoi-core'])
class RoleDetailView(AoiAPIView):
    """``GET/PUT/DELETE /api/core/roles/{id}``（system.roles）。

    PUT 支持 ``permissions`` **全量覆盖**；内置角色禁改 ``code``（PUT 不读取该字段）、禁删。
    """

    aoi_perm = 'system.roles'

    def get(self, request, id: int):
        role = Role.objects.filter(id=id).first()
        if role is None:
            raise AoiError(CODE_NOT_FOUND, 'role not found')
        codes_by_role = _permission_codes_by_role([role.id])
        return self.ok(_role_payload(role, codes_by_role.get(role.id, [])))

    def put(self, request, id: int):
        payload = request.data if isinstance(request.data, dict) else {}
        permissions = _validated_permissions(payload)

        with transaction.atomic():
            role = Role.objects.select_for_update().filter(id=id).first()
            if role is None:
                raise AoiError(CODE_NOT_FOUND, 'role not found')

            role.name_cn = str(payload.get('name_cn') or role.name_cn)
            role.description = str(payload.get('description') or role.description or '')
            role.save(update_fields=['name_cn', 'description'])

            detail: dict = {'code': role.code}
            if permissions is not None:
                before = set(_permission_codes_by_role([role.id]).get(role.id, []))
                _replace_permissions(role.id, permissions)
                detail['permissions_added'] = sorted(set(permissions) - before)
                detail['permissions_removed'] = sorted(before - set(permissions))

            authz.bump_version()
            write_audit(
                actor_id=self.user_id,
                action='role.update',
                object_type='aoi_core.role',
                object_id=str(role.id),
                detail=detail,
                request_id=self.request_id,
            )

        codes_by_role = _permission_codes_by_role([role.id])
        return self.ok(_role_payload(role, codes_by_role.get(role.id, [])))

    def delete(self, request, id: int):
        with transaction.atomic():
            role = Role.objects.select_for_update().filter(id=id).first()
            if role is None:
                raise AoiError(CODE_NOT_FOUND, 'role not found')
            if role.is_builtin:
                raise AoiError(CODE_CONFLICT, 'builtin roles cannot be deleted', fields={'id': 'builtin role'})

            UserRole.objects.filter(role_id=id).delete()
            RolePermission.objects.filter(role_id=id).delete()
            role.delete()
            authz.bump_version()
            write_audit(
                actor_id=self.user_id,
                action='role.delete',
                object_type='aoi_core.role',
                object_id=str(id),
                detail={'code': role.code},
                request_id=self.request_id,
            )
        return self.ok({'id': id, 'deleted': True})


@extend_schema(tags=['aoi-core'])
class UserRolesView(AoiAPIView):
    """``POST /api/core/users/{id}/roles`` 分配角色（**全量覆盖**，system.users）。"""

    aoi_perm = 'system.users'

    def post(self, request, id: int):
        payload = request.data if isinstance(request.data, dict) else {}
        roles = payload.get('roles') or payload.get('role_codes') or []
        if isinstance(roles, str):
            roles = [roles]
        if not isinstance(roles, list) or any(not isinstance(role, str) for role in roles):
            raise AoiError(CODE_UNPROCESSABLE, 'invalid roles', fields={'roles': 'must be a list of strings'})

        wanted = sorted(set(roles))
        role_ids = dict(Role.objects.filter(code__in=wanted).values_list('code', 'id'))
        unknown = sorted(set(wanted) - set(role_ids))
        if unknown:
            known = sorted(Role.objects.values_list('code', flat=True))
            raise AoiError(
                CODE_UNPROCESSABLE,
                'unknown role codes',
                fields={'roles': f'unknown: {unknown}; known: {known}'},
            )

        if not get_user_model().objects.filter(pk=id).exists():
            raise AoiError(CODE_NOT_FOUND, 'user not found')

        _guard_last_super_admin(id, keeps_super_admin='super_admin' in wanted)

        with transaction.atomic():
            UserRole.objects.filter(user_id=id).delete()
            UserRole.objects.bulk_create(
                [UserRole(user_id=id, role_id=role_ids[code], granted_by=self.user_id) for code in wanted]
            )
            authz.bump_version()
            write_audit(
                actor_id=self.user_id,
                action='user.roles.assign',
                object_type='auth.user',
                object_id=str(id),
                detail={'roles': wanted},
                request_id=self.request_id,
            )
        return self.ok({'user_id': id, 'roles': wanted})


@extend_schema(tags=['aoi-core'])
class UserListView(AoiAPIView):
    """``GET /api/core/users`` 用户列表 + aoi 角色（system.users）。

    LS 原生 ``GET /api/users/`` 拿不到 aoi 角色，故新开（契约 §4.0）。
    """

    aoi_perm = 'system.users'

    def get(self, request):
        from aoi.core.models import Role, UserRole

        role_codes = dict(Role.objects.values_list('id', 'code'))
        roles_by_user: dict[int, list[str]] = {}
        for user_id, role_id in UserRole.objects.order_by('role_id').values_list('user_id', 'role_id'):
            code = role_codes.get(role_id)
            if code:
                roles_by_user.setdefault(user_id, []).append(code)

        rows = list(get_user_model().objects.order_by('id').values('id', 'email', 'is_active'))
        items = [
            {
                'id': row['id'],
                'email': row['email'],
                'is_active': row['is_active'],
                'roles': roles_by_user.get(row['id'], []),
            }
            for row in rows
        ]
        return self.ok(paginate(request, items))


class _UserActiveViewBase(AoiAPIView):
    """停用/启用共享实现（契约 §3.1 停用语义）。"""

    aoi_perm = 'system.users'
    #: 目标状态；子类固定为 True/False
    target_active: bool = True

    def post(self, request, id: int):
        from aoi.core.models import UserRole
        from organizations.models import OrganizationMember

        user = get_user_model().objects.filter(pk=id).first()
        if user is None:
            raise AoiError(CODE_NOT_FOUND, 'user not found')

        with transaction.atomic():
            update_fields = ['is_active']
            if self.target_active:
                # 启用：恢复成员关系；active_organization 为空时指回第一个组织；角色保持为空（重新任命）
                OrganizationMember.objects.filter(user=user).update(deleted_at=None)
                if user.active_organization_id is None:
                    member = OrganizationMember.objects.filter(user=user).select_related('organization').first()
                    if member is not None:
                        user.active_organization = member.organization
                        update_fields.append('active_organization')
            else:
                # 停用：清空 aoi 角色（同事务 bump 版本）+ 软移除全部组织成员关系
                OrganizationMember.objects.filter(user=user, deleted_at__isnull=True).update(deleted_at=timezone.now())
                UserRole.objects.filter(user_id=id).delete()
                # active_organization 仍指向已移除的成员关系时，core.views.main 会误判账号有效；镜像上游成员软删行为
                if user.active_organization_id is not None:
                    member = (
                        OrganizationMember.objects.filter(user=user, deleted_at__isnull=True)
                        .select_related('organization')
                        .first()
                    )
                    user.active_organization = member.organization if member else None
                    update_fields.append('active_organization')

            user.is_active = self.target_active
            user.save(update_fields=update_fields)

            if not self.target_active:
                authz.bump_version()
            write_audit(
                actor_id=self.user_id,
                action='user.activate' if self.target_active else 'user.deactivate',
                object_type='auth.user',
                object_id=str(id),
                detail={'is_active': self.target_active},
                request_id=self.request_id,
            )

        return self.ok({'user_id': id, 'is_active': self.target_active})


@extend_schema(tags=['aoi-core'])
class UserDeactivateView(_UserActiveViewBase):
    """``POST /api/core/users/{id}/deactivate`` 停用组合拳（契约 §3.1/§4.0）。"""

    target_active = False

    def post(self, request, id: int):
        _guard_last_super_admin(id, keeps_super_admin=False)
        return super().post(request, id)


@extend_schema(tags=['aoi-core'])
class UserActivateView(_UserActiveViewBase):
    """``POST /api/core/users/{id}/activate`` 启用（角色保持为空，契约 §4.0）。"""

    target_active = True
