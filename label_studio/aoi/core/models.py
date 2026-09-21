"""aoi_core RBAC 数据模型（契约 §3.1）。

四张 RBAC 表（`role`/`permission`/`role_permission`/`user_role`）+ 授权版本号表 `authz_state`，
全部落在 PostgreSQL schema ``aoi_core``（仅支持 PostgreSQL，建 schema 的 RunSQL 在 0001 迁移首条）。

``user_role.user_id`` 逻辑引用 LS ``users.id``，**不建外键**（上游 users 表只读）。
"""

from __future__ import annotations

from django.db import models
from django.utils import timezone

__all__ = ['Role', 'Permission', 'RolePermission', 'UserRole', 'AuthzState']


class Role(models.Model):
    """角色（内置三角色 + 可扩展自定义角色）。"""

    id = models.AutoField(primary_key=True)
    code = models.CharField(max_length=32, unique=True)
    name_cn = models.CharField(max_length=64)
    description = models.TextField(null=True, blank=True)
    is_builtin = models.BooleanField(default=True)

    class Meta:
        app_label = 'aoi_core'
        db_table = '"aoi_core"."role"'

    def __str__(self) -> str:
        return self.code


class Permission(models.Model):
    """权限点（模块级：``{module}.{action}``）。"""

    id = models.AutoField(primary_key=True)
    code = models.CharField(max_length=64, unique=True)
    module = models.CharField(max_length=32)
    action = models.CharField(max_length=32)
    name_cn = models.CharField(max_length=64, null=True, blank=True)

    class Meta:
        app_label = 'aoi_core'
        db_table = '"aoi_core"."permission"'

    def __str__(self) -> str:
        return self.code


class RolePermission(models.Model):
    """角色-权限点授权关系。"""

    pk = models.CompositePrimaryKey('role_id', 'permission_id')
    role_id = models.IntegerField()
    permission_id = models.IntegerField()

    class Meta:
        app_label = 'aoi_core'
        db_table = '"aoi_core"."role_permission"'


class UserRole(models.Model):
    """用户-角色授权关系；``user_id`` 逻辑引用 LS users，不建外键。"""

    pk = models.CompositePrimaryKey('user_id', 'role_id')
    user_id = models.IntegerField()
    role_id = models.IntegerField()
    granted_by = models.IntegerField(null=True, blank=True)
    granted_at = models.DateTimeField(default=timezone.now)

    class Meta:
        app_label = 'aoi_core'
        db_table = '"aoi_core"."user_role"'


class AuthzState(models.Model):
    """授权版本号（单行，``id`` 固定 1）。

    角色/授权变更在同一事务内 +1；判定侧每请求读一次版本号，从而在
    ``CACHES`` 未配置（LocMemCache，多 worker 进程间不共享）时依然零延迟失效。
    """

    id = models.IntegerField(primary_key=True, default=1)
    version = models.BigIntegerField(default=0)
    updated_at = models.DateTimeField(default=timezone.now)

    class Meta:
        app_label = 'aoi_core'
        db_table = '"aoi_core"."authz_state"'

    def __str__(self) -> str:
        return f'authz-state@{self.version}'
