"""aoi_core 权限点常量（契约 §3.1）。

D4 启动时全量 upsert 到 ``aoi_core.permission``；D1–D2 仅作为视图声明与前端按钮显隐的约定。
"""

from __future__ import annotations

__all__ = [
    'MODULES',
    'ACTIONS',
    'EXTRA_PERMISSIONS',
    'PERMISSION_CODES',
    'is_known_permission',
]

#: 模块级权限点模块
MODULES = ('datasets', 'training', 'review', 'system')

#: 动作
ACTIONS = ('view', 'create', 'update', 'cancel', 'approve', 'publish')

#: 契约权限矩阵中额外出现的权限点
EXTRA_PERMISSIONS = (
    'datasets.export',
    'prelabel.view',
    'prelabel.create',
    'prelabel.update',
    'review.finalize',
    'system.roles',
    'system.users',
    'system.audit',
)

PERMISSION_CODES = tuple(f'{module}.{action}' for module in MODULES for action in ACTIONS) + EXTRA_PERMISSIONS


def is_known_permission(code: str) -> bool:
    return code in PERMISSION_CODES
