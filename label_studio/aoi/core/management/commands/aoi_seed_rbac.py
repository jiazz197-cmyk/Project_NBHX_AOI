"""幂等播种 aoi_core 权限点与内置角色授权（契约 §3.1）。

``post_migrate`` 已会自动播种；本命令用于兜底与运维手动重跑
（例如播种失败、或新增权限点后想立即生效而不重启）。
"""

from __future__ import annotations

from aoi.core.bootstrap import ensure_bootstrap_super_admin
from aoi.core.permissions import PERMISSION_CODES, seed_rbac
from django.core.management.base import BaseCommand


class Command(BaseCommand):
    help = 'Idempotently seed aoi_core permissions and builtin role grants.'

    def handle(self, *args, **options):
        stats = seed_rbac()
        if ensure_bootstrap_super_admin():
            self.stdout.write('bootstrap super_admin created')
        self.stdout.write(
            'aoi_core seeded: permissions +{created} (updated {updated}), roles +{roles}, '
            'grants +{grants} / {total} codes'.format(
                created=stats['permissions_created'],
                updated=stats['permissions_updated'],
                roles=stats['roles_created'],
                grants=stats['grants_created'],
                total=len(PERMISSION_CODES),
            )
        )
