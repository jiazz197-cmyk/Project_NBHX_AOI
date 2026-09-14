"""固定超管引导（契约 §3.1 超管引导，D5）。

随 ``post_migrate`` / ``aoi_seed_rbac`` 幂等执行：固定超管不存在则按 LS 注册链路
（``users.functions.common.save_user``）的等价接线创建；已存在**不重置密码**
（改密走 LS 原生账户页），只补授 ``super_admin``（只加不减）。
"""

from __future__ import annotations

import logging

from django.db import transaction

logger = logging.getLogger(__name__)

__all__ = ['BOOTSTRAP_SUPER_ADMIN_EMAIL', 'BOOTSTRAP_SUPER_ADMIN_PASSWORD', 'ensure_bootstrap_super_admin']

BOOTSTRAP_SUPER_ADMIN_EMAIL = 'superadmin@nbhx.com'
BOOTSTRAP_SUPER_ADMIN_PASSWORD = 'superadmin.5003'


def _wire_organization(user) -> None:
    """镜像 ``users.functions.common.save_user``：挂第一个组织（无则创建）并设 active_organization。"""
    from organizations.models import Organization, OrganizationMember

    if OrganizationMember.objects.filter(user=user).exists():
        if user.active_organization_id is None:
            member = OrganizationMember.objects.filter(user=user).select_related('organization').first()
            if member is not None:
                user.active_organization = member.organization
                user.save(update_fields=['active_organization'])
        return

    org = Organization.objects.first()
    if org is None:
        org = Organization.create_organization(created_by=user, title='AOI')
    else:
        org.add_user(user)
    if user.active_organization_id is None:
        user.active_organization = org
        user.save(update_fields=['active_organization'])


def ensure_bootstrap_super_admin() -> bool:
    """确保固定超管存在且持 ``super_admin``；返回是否新建了账号。"""
    from aoi.core import authz
    from aoi.core.models import Role, UserRole
    from django.contrib.auth import get_user_model

    created = False
    with transaction.atomic():
        user = get_user_model().objects.filter(email__iexact=BOOTSTRAP_SUPER_ADMIN_EMAIL).first()
        if user is None:
            # username 取邮箱前缀，与注册链路 save_user 一致
            user = get_user_model().objects.create_user(BOOTSTRAP_SUPER_ADMIN_EMAIL, BOOTSTRAP_SUPER_ADMIN_PASSWORD)
            user.username = user.email.split('@')[0]
            user.save(update_fields=['username'])
            created = True

        _wire_organization(user)

        super_admin = Role.objects.filter(code='super_admin').first()
        if super_admin is not None and not UserRole.objects.filter(user_id=user.id, role_id=super_admin.id).exists():
            UserRole.objects.create(user_id=user.id, role_id=super_admin.id)
            authz.bump_version()

    if created:
        logger.info('aoi_core bootstrap super_admin created: %s', BOOTSTRAP_SUPER_ADMIN_EMAIL)
    return created
