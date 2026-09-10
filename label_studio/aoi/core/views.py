"""aoi.core 端点：权限点查询与角色/授权（D1–D2 stub）。

D4 接入 ``aoi_core`` 四表与判定；当前角色数据为进程内占位（不建表，见 P0 §2 决策 4）。
D1–D2 的写校验（code 唯一 / 内置角色不可删 / 未知角色拒绝 / 角色变更写审计）按 P1 提前落地，
避免 D4 换表时才暴露语义差异。
"""

from __future__ import annotations

from aoi.common.audit import write_audit
from aoi.common.errors import CODE_CONFLICT, CODE_NOT_FOUND, CODE_UNPROCESSABLE, AoiError
from aoi.common.pagination import paginate
from aoi.common.views import AoiAPIView
from drf_spectacular.utils import extend_schema

# 进程内 stub 数据（D4 由 aoi_core.role 表替换）
_BUILTIN_ROLES = [
    {'id': 1, 'code': 'operator', 'name_cn': '操作员', 'description': '日常标注与复审', 'is_builtin': True},
    {'id': 2, 'code': 'admin', 'name_cn': '管理员', 'description': '数据集/训练/模型发布/复审', 'is_builtin': True},
    {
        'id': 3,
        'code': 'super_admin',
        'name_cn': '超级管理员',
        'description': '管理员之上增加角色与授权、审计',
        'is_builtin': True,
    },
]
_ROLES: dict[int, dict] = {role['id']: dict(role) for role in _BUILTIN_ROLES}
_NEXT_ROLE_ID = 4
_USER_ROLES: dict[int, list[str]] = {}


def _role_payload(role: dict) -> dict:
    return {
        'id': role['id'],
        'code': role['code'],
        'name_cn': role['name_cn'],
        'description': role.get('description', ''),
        'is_builtin': role.get('is_builtin', False),
        'permissions': [],
    }


@extend_schema(tags=['aoi-core'])
class PermissionsView(AoiAPIView):
    """``GET /api/core/permissions`` → 当前用户角色/权限点（供前端按钮显隐）。"""

    def get(self, request):
        # D4: 查 aoi_core.user_role → role_permission → permission.code
        roles = _USER_ROLES.get(self.user_id, [])
        perms = []  # D4: 按 roles 聚合权限点
        return self.ok({'user_id': self.user_id, 'roles': roles, 'perms': perms})


@extend_schema(tags=['aoi-core'])
class RoleListCreateView(AoiAPIView):
    """``GET/POST /api/core/roles``（super_admin，D1–D2 不拦截）。"""

    aoi_perm = 'system.roles'

    def get(self, request):
        items = [_role_payload(role) for role in _ROLES.values()]
        return self.ok(paginate(request, items))

    def post(self, request):
        global _NEXT_ROLE_ID
        payload = request.data if isinstance(request.data, dict) else {}
        code = str(payload.get('code') or '').strip()
        name_cn = str(payload.get('name_cn') or payload.get('name') or '').strip()
        description = str(payload.get('description') or '')
        fields = {}
        if not code:
            fields['code'] = 'required'
        elif len(code) > 32:
            fields['code'] = 'must be <= 32 chars'
        elif code in {role['code'] for role in _ROLES.values()}:
            raise AoiError(CODE_CONFLICT, 'role code already exists', fields={'code': code})
        if not name_cn:
            fields['name_cn'] = 'required'
        elif len(name_cn) > 64:
            fields['name_cn'] = 'must be <= 64 chars'
        if fields:
            raise AoiError(CODE_UNPROCESSABLE, 'invalid role payload', fields=fields)
        role = {
            'id': _NEXT_ROLE_ID,
            'code': code,
            'name_cn': name_cn,
            'description': description,
            'is_builtin': False,
        }
        _ROLES[_NEXT_ROLE_ID] = role
        _NEXT_ROLE_ID += 1
        write_audit(
            actor_id=self.user_id,
            action='role.create',
            object_type='aoi_core.role',
            object_id=str(role['id']),
            detail={'code': code},
            request_id=self.request_id,
        )
        return self.ok(_role_payload(role))


@extend_schema(tags=['aoi-core'])
class RoleDetailView(AoiAPIView):
    """``GET/PUT/DELETE /api/core/roles/{id}``（进程内占位；D4 由 ``aoi_core`` 四表替换）。"""

    aoi_perm = 'system.roles'

    def get(self, request, id: int):
        role = _ROLES.get(id)
        if role is None:
            raise AoiError(CODE_NOT_FOUND, 'role not found')
        return self.ok(_role_payload(role))

    def put(self, request, id: int):
        role = _ROLES.get(id)
        if role is None:
            raise AoiError(CODE_NOT_FOUND, 'role not found')
        payload = request.data if isinstance(request.data, dict) else {}
        role.update(
            {
                'name_cn': str(payload.get('name_cn') or role['name_cn']),
                'description': str(payload.get('description') or role.get('description', '')),
            }
        )
        write_audit(
            actor_id=self.user_id,
            action='role.update',
            object_type='aoi_core.role',
            object_id=str(id),
            detail={'code': role['code']},
            request_id=self.request_id,
        )
        return self.ok(_role_payload(role))

    def delete(self, request, id: int):
        role = _ROLES.get(id)
        if role is None:
            raise AoiError(CODE_NOT_FOUND, 'role not found')
        if role.get('is_builtin'):
            raise AoiError(
                CODE_CONFLICT,
                'builtin roles cannot be deleted',
                fields={'id': 'builtin role'},
            )
        _ROLES.pop(id, None)
        write_audit(
            actor_id=self.user_id,
            action='role.delete',
            object_type='aoi_core.role',
            object_id=str(id),
            detail={'code': role['code']},
            request_id=self.request_id,
        )
        return self.ok({'id': id, 'deleted': True})


@extend_schema(tags=['aoi-core'])
class UserRolesView(AoiAPIView):
    """``POST /api/core/users/{id}/roles`` 分配角色（D1–D2 进程内占位）。

    P1：角色必须是已存在的 role code（否则 42200），用户必须存在（否则 40401），变更写审计。
    """

    aoi_perm = 'system.users'

    def post(self, request, id: int):
        payload = request.data if isinstance(request.data, dict) else {}
        roles = payload.get('roles') or payload.get('role_codes') or []
        if isinstance(roles, str):
            roles = [roles]
        if not isinstance(roles, list) or any(not isinstance(role, str) for role in roles):
            raise AoiError(CODE_UNPROCESSABLE, 'invalid roles', fields={'roles': 'must be a list of strings'})

        known = {role['code'] for role in _ROLES.values()}
        unknown = sorted(set(roles) - known)
        if unknown:
            raise AoiError(
                CODE_UNPROCESSABLE,
                'unknown role codes',
                fields={'roles': f'unknown: {unknown}; known: {sorted(known)}'},
            )

        from django.contrib.auth import get_user_model

        if not get_user_model().objects.filter(pk=id).exists():
            raise AoiError(CODE_NOT_FOUND, 'user not found')

        _USER_ROLES[id] = roles
        write_audit(
            actor_id=self.user_id,
            action='user.roles.assign',
            object_type='auth.user',
            object_id=str(id),
            detail={'roles': roles},
            request_id=self.request_id,
        )
        return self.ok({'user_id': id, 'roles': roles})
