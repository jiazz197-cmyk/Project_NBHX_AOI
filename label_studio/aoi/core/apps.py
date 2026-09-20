import logging
import os

from django.apps import AppConfig

logger = logging.getLogger(__name__)


def _seed_rbac_on_migrate(sender, **kwargs) -> None:
    """``post_migrate`` 播种（幂等）。

    失败只记日志、不阻断 migrate：权限表为空会让全站 aoi 视图返回 40300，
    因此失败必须显式告警，并由 ``manage.py aoi_seed_rbac`` 兜底重跑。
    """
    from aoi.core.bootstrap import ensure_bootstrap_super_admin
    from aoi.core.permissions import seed_rbac

    try:
        stats = seed_rbac()
        ensure_bootstrap_super_admin()
    except Exception:
        logger.exception('aoi_core RBAC seed failed; run `manage.py aoi_seed_rbac` to recover')
        return
    logger.info('aoi_core RBAC seeded: %s', stats)


class AoiCoreConfig(AppConfig):
    name = 'aoi.core'
    label = 'aoi_core'
    verbose_name = 'AOI Core (RBAC)'
    default_auto_field = 'django.db.models.AutoField'

    def ready(self) -> None:
        # 只在 migrate 后播种；不在 ready() 里写库（ready 会在 check/shell/collectstatic 时触发）
        from django.db.models.signals import post_migrate

        post_migrate.connect(_seed_rbac_on_migrate, sender=self, dispatch_uid='aoi_core.seed_rbac')

        # D5：runserver 的 autoreload 子进程（RUN_MAIN）自动带起 aoi Celery worker；
        # 其余命令（migrate/check/shell/测试/uwsgi）没有 RUN_MAIN，零影响（见 aoi/core/dev_worker.py）
        if os.environ.get('RUN_MAIN') == 'true':
            from aoi.core import dev_worker

            if dev_worker.should_autostart_worker():
                dev_worker.start_celery_worker()
