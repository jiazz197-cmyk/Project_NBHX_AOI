"""授予/覆盖用户角色（契约 §3.1）——首个 super_admin 由本命令产生。

用法::

    manage.py aoi_grant_role ops@nbhx.com super_admin      # 全量覆盖该用户角色
    manage.py aoi_grant_role ops@nbhx.com operator admin
    manage.py aoi_grant_role ops@nbhx.com --clear          # 清空该用户角色
    manage.py aoi_grant_role --list                        # 查看 用户 → 角色 映射
"""

from __future__ import annotations

from aoi.common.audit import write_audit
from aoi.core import authz
from aoi.core.models import Role, UserRole
from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction


class Command(BaseCommand):
    help = 'Grant roles to a user (full overwrite); use it to seed the first super_admin.'

    def add_arguments(self, parser):
        parser.add_argument('email', nargs='?', help='LS account email')
        parser.add_argument('roles', nargs='*', help='role codes (full overwrite)')
        parser.add_argument('--list', action='store_true', help='list user → roles mapping and exit')
        parser.add_argument('--clear', action='store_true', help='clear all roles of the user')
        parser.add_argument('--actor', type=int, default=None, help='operator user id recorded in audit')

    def handle(self, *args, **options):
        if options['list']:
            return self._list()

        email = (options.get('email') or '').strip()
        roles = [code.strip() for code in options.get('roles') or [] if code.strip()]
        if not email:
            raise CommandError('email is required (or use --list)')
        if options['clear'] and roles:
            raise CommandError('--clear cannot be combined with role codes')
        if not roles and not options['clear']:
            raise CommandError('no role codes given (use --clear to wipe roles)')

        user = get_user_model().objects.filter(email__iexact=email).first()
        if user is None:
            raise CommandError(f'user not found: {email}')

        wanted = sorted(set(roles))
        role_ids = dict(Role.objects.filter(code__in=wanted).values_list('code', 'id')) if wanted else {}
        unknown = sorted(set(wanted) - set(role_ids))
        if unknown:
            known = sorted(Role.objects.values_list('code', flat=True))
            raise CommandError(f'unknown role codes {unknown}; known: {known}')

        actor_id = options['actor']
        with transaction.atomic():
            UserRole.objects.filter(user_id=user.id).delete()
            if wanted:
                UserRole.objects.bulk_create(
                    [UserRole(user_id=user.id, role_id=role_ids[code], granted_by=actor_id) for code in wanted]
                )
            authz.bump_version()
            write_audit(
                actor_id=actor_id,
                action='user.roles.assign',
                object_type='auth.user',
                object_id=str(user.id),
                detail={'roles': wanted, 'source': 'aoi_grant_role'},
            )

        self.stdout.write(f'{email} (id={user.id}) roles: {wanted}')

    def _list(self) -> None:
        role_codes = dict(Role.objects.values_list('id', 'code'))
        rows = list(UserRole.objects.all().order_by('user_id', 'role_id'))
        emails = dict(get_user_model().objects.filter(id__in=[row.user_id for row in rows]).values_list('id', 'email'))
        if not rows:
            self.stdout.write('no user-role grants')
            return
        for row in rows:
            self.stdout.write(
                f'{row.user_id}\t{emails.get(row.user_id, "<deleted user>")}\t{role_codes.get(row.role_id, "?")}'
            )
