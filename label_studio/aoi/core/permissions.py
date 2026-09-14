"""aoi_core 权限点常量、内置角色矩阵与播种（契约 §3.1）。

码表：``MODULES(4) × ACTIONS(6) = 24`` + ``EXTRA_PERMISSIONS(14)`` = **38 码**。
``ACTIONS`` 不扩——新增权限点一律进 ``EXTRA_PERMISSIONS``，否则会生成
``training.delete``/``review.config`` 这类永无视图使用的空码。

播种语义（``seed_rbac()``，幂等）：

1. ``permission`` 按码表全量 upsert，不删除多余行；
2. 三角色按 ``code`` upsert；**角色已存在则不动其 ``role_permission``**（人工调整不被重启回滚）；
3. 角色**首次创建**时按 :data:`DEFAULT_ROLE_MATRIX` 写授权；
4. ``super_admin`` **每次补授缺失码（只加不减）**——它天然是全权限角色。

触发点：``post_migrate`` signal（``aoi.core.apps``）+ 幂等管理命令 ``aoi_seed_rbac``。
"""

from __future__ import annotations

from typing import Iterable

__all__ = [
    'MODULES',
    'ACTIONS',
    'EXTRA_PERMISSIONS',
    'PERMISSION_CODES',
    'PERMISSION_NAMES_CN',
    'BUILTIN_ROLES',
    'DEFAULT_ROLE_MATRIX',
    'is_known_permission',
    'permission_module_action',
    'seed_rbac',
]

#: 模块级权限点模块
MODULES = ('datasets', 'training', 'review', 'system')

#: 动作（**不扩**：新增权限点走 EXTRA_PERMISSIONS）
ACTIONS = ('view', 'create', 'update', 'cancel', 'approve', 'publish')

#: 契约权限矩阵中额外出现的权限点（含闸门专用码与保留码）
EXTRA_PERMISSIONS = (
    'datasets.export',
    'datasets.delete',
    'datasets.config',
    'prelabel.view',
    'prelabel.create',
    'prelabel.update',
    'review.finalize',
    'system.roles',
    'system.users',
    'system.audit',
    'system.storage',
    'system.ml',
    'system.webhook',
    'system.labels',
)

PERMISSION_CODES = tuple(f'{module}.{action}' for module in MODULES for action in ACTIONS) + EXTRA_PERMISSIONS

#: 权限点中文名（写入 ``aoi_core.permission.name_cn``，供角色授权界面渲染）
PERMISSION_NAMES_CN = {
    'datasets.view': '查看数据集',
    'datasets.create': '新建数据集/导入',
    'datasets.update': '修改数据集/标注',
    'datasets.cancel': '取消数据集操作',
    'datasets.approve': '审批数据集',
    'datasets.publish': '发布缺陷字典',
    'datasets.export': '导出数据集',
    'datasets.delete': '删除数据集/项目',
    'datasets.config': '修改标注项目配置',
    'training.view': '查看训练任务',
    'training.create': '创建训练任务',
    'training.update': '修改训练任务',
    'training.cancel': '取消训练任务',
    'training.approve': '审批训练结果',
    'training.publish': '发布模型镜像',
    'review.view': '查看复审队列',
    'review.create': '创建复审项',
    'review.update': '认领/处理复审项',
    'review.cancel': '取消复审项',
    'review.approve': '复核复审结论',
    'review.publish': '发布复审结果',
    'review.finalize': '终裁复审项',
    'prelabel.view': '查看预标任务',
    'prelabel.create': '创建预标任务',
    'prelabel.update': '修改预标任务',
    'system.view': '查看系统信息',
    'system.create': '系统新增操作',
    'system.update': '系统修改操作',
    'system.cancel': '系统取消操作',
    'system.approve': '系统审批操作',
    'system.publish': '系统发布操作',
    'system.roles': '管理角色与授权',
    'system.users': '管理用户与组织',
    'system.audit': '查看审计日志',
    'system.storage': '管理存储配置',
    'system.ml': '管理 ML 后端配置',
    'system.webhook': '管理 Webhook 配置',
    'system.labels': '管理标签库',
}

#: 内置角色（``code``, ``name_cn``, ``description``）
BUILTIN_ROLES = (
    ('operator', '操作员', '日常标注与复审'),
    ('admin', '管理员', '数据集/训练/模型发布/复审'),
    ('super_admin', '超级管理员', '管理员之上增加角色与授权、审计'),
)

_SUPER_ADMIN = 'super_admin'

_OPERATOR_PERMISSIONS = (
    'datasets.view',
    'datasets.create',
    'datasets.update',
    'training.view',
    'review.view',
    'review.update',
    'review.finalize',
)

_ADMIN_PERMISSIONS = _OPERATOR_PERMISSIONS + (
    'datasets.publish',
    'datasets.export',
    'datasets.delete',
    'datasets.config',
    'prelabel.view',
    'prelabel.create',
    'prelabel.update',
    'training.create',
    'training.cancel',
    'training.approve',
    'training.publish',
)

#: 内置角色默认权限矩阵；``super_admin`` 为全码（播种时另做「只加不减」补授）
DEFAULT_ROLE_MATRIX = {
    'operator': _OPERATOR_PERMISSIONS,
    'admin': _ADMIN_PERMISSIONS,
    _SUPER_ADMIN: PERMISSION_CODES,
}


def permission_module_action(code: str) -> tuple[str, str]:
    """``datasets.view`` → ``('datasets', 'view')``。"""
    module, _, action = code.partition('.')
    return module, action


def is_known_permission(code: str) -> bool:
    return code in PERMISSION_CODES


def _grant(role_id: int, codes: Iterable[str], permission_ids: dict[str, int]) -> int:
    """给角色补授缺失的权限点（已存在的跳过），返回新增行数。"""
    from aoi.core.models import RolePermission

    existing = set(RolePermission.objects.filter(role_id=role_id).values_list('permission_id', flat=True))
    rows = [
        RolePermission(role_id=role_id, permission_id=permission_ids[code])
        for code in codes
        if permission_ids[code] not in existing
    ]
    if rows:
        RolePermission.objects.bulk_create(rows)
    return len(rows)


def seed_rbac() -> dict[str, int]:
    """全量 upsert 权限点并按 §3.1 语义播种内置角色（幂等）。"""
    from aoi.core.models import Permission, Role
    from django.db import transaction

    stats = {'permissions_created': 0, 'permissions_updated': 0, 'roles_created': 0, 'grants_created': 0}
    if not PERMISSION_CODES:
        raise AssertionError('PERMISSION_CODES is empty')

    with transaction.atomic():
        known = {perm.code: perm for perm in Permission.objects.all()}
        missing = []
        for code in PERMISSION_CODES:
            module, action = permission_module_action(code)
            name_cn = PERMISSION_NAMES_CN.get(code)
            perm = known.get(code)
            if perm is None:
                missing.append(Permission(code=code, module=module, action=action, name_cn=name_cn))
            elif (perm.module, perm.action, perm.name_cn) != (module, action, name_cn):
                perm.module, perm.action, perm.name_cn = module, action, name_cn
                perm.save(update_fields=['module', 'action', 'name_cn'])
                stats['permissions_updated'] += 1
        if missing:
            Permission.objects.bulk_create(missing)
            stats['permissions_created'] = len(missing)

        permission_ids = dict(Permission.objects.values_list('code', 'id'))
        for code, name_cn, description in BUILTIN_ROLES:
            role = Role.objects.filter(code=code).first()
            if role is None:
                role = Role.objects.create(code=code, name_cn=name_cn, description=description, is_builtin=True)
                stats['roles_created'] += 1
                stats['grants_created'] += _grant(role.id, DEFAULT_ROLE_MATRIX.get(code, ()), permission_ids)

        super_admin = Role.objects.filter(code=_SUPER_ADMIN).first()
        if super_admin is not None:
            stats['grants_created'] += _grant(super_admin.id, PERMISSION_CODES, permission_ids)

    return stats
