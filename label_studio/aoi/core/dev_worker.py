"""开发态 worker 托管：``runserver`` 时自动带起 aoi Celery worker。

挂点与守卫：``RUN_MAIN`` 只在 ``manage.py runserver`` 的 autoreload **子进程**里为
``true``（Django 5.2 ``autoreload.DJANGO_AUTORELOAD_ENV``）；migrate/check/shell/
collectstatic/契约测试/uwsgi 均无此变量——因此不会在其它命令里误拉起 worker
（这正是 D6「不在 ready() 做无守卫副作用」约束所排除的场景，此处用变量精确圈定）。

生命周期：

- 随 runserver 启动（默认 ``--queues=default --pool=solo``，与 ``make run-celery`` 同参）；
- Ctrl+C：同前台进程组都收 SIGINT，worker 与 Django 一起 warm shutdown；
- 文件变更重载：autoreload 子进程 ``SIGTERM → sys.exit(0)`` → ``atexit`` 终止 worker，
  新子进程重新拉起；
- 仅当父进程被 SIGKILL 才可能遗留孤儿 worker（``pkill -f 'aoi worker'`` 清理）。

开关：``AOI_AUTOSTART_CELERY=false`` 关闭；``CELERY_TASK_ALWAYS_EAGER=true``（eager
同步模式）时不需要 worker，自动跳过。
"""

from __future__ import annotations

import atexit
import logging
import os
import signal
import subprocess
import sys
from pathlib import Path

from core.utils.params import get_bool_env

logger = logging.getLogger(__name__)

#: worker 启动参数：仅 default 队列；solo 单进程池（本地导入量级足够，不依赖 /dev/shm）
_CELERY_ARGS = (
    '-m',
    'celery',
    '-A',
    'aoi',
    'worker',
    '--queues=default',
    '--pool=solo',
    '--concurrency=1',
    '--loglevel=info',
)


def should_autostart_worker() -> bool:
    """eager 模式无需 worker；默认开启，``AOI_AUTOSTART_CELERY=false`` 关闭。"""
    from django.conf import settings

    if settings.CELERY_TASK_ALWAYS_EAGER:
        return False
    return get_bool_env('AOI_AUTOSTART_CELERY', True)


def _pdeathsig() -> None:  # pragma: no cover - preexec 钩子，仅 Linux
    """子进程侧内核兜底：父进程死亡时由内核向本进程发 SIGTERM。

    必要性：autoreload 模式下 Django 的 runserver 在**线程**里起服务，启动失败
    （如端口占用）时用 ``os._exit(1)`` 退出——``os._exit`` 跳过 atexit/finally，
    仅靠父进程 atexit 清理会孤儿化 worker。PR_SET_PDEATHSIG 由内核保证随父进程
    （创建本子进程的主线程）死亡而递送，与 atexit 互补。macOS 无 prctl，静默跳过
    （该平台不在本仓库交付面内）。
    """
    try:
        import ctypes

        libc = ctypes.CDLL('libc.so.6', use_errno=True)
        libc.prctl(1, signal.SIGTERM)  # 1 = PR_SET_PDEATHSIG
        # fork 与 prctl 之间的竞态窗口：父进程若已先死，立即自我了断
        if os.getppid() == 1:
            os.kill(os.getpid(), signal.SIGTERM)
    except Exception:
        pass


def start_celery_worker():
    """启动 worker 子进程并注册退出清理；失败只告警不阻断 runserver（fail-open）。"""
    try:
        env = os.environ.copy()
        # celery 子进程需要能 import aoi：manage.py 自带的 label_studio 路径只在父进程生效。
        # 本文件位于 label_studio/aoi/core/dev_worker.py → parents[2] 即 label_studio/
        # （注意不能用 settings.BASE_DIR：那是 label_studio/core，不含 aoi 包）。
        label_studio_dir = Path(__file__).resolve().parents[2]
        env['PYTHONPATH'] = os.pathsep.join(filter(None, (str(label_studio_dir), env.get('PYTHONPATH', ''))))
        # 关键：剥掉 RUN_MAIN，否则 worker 进程自身 django.setup() 时会再次触发本模块
        # 的 ready() 守卫 → 递归拉起 worker（fork 风暴）。
        env.pop('RUN_MAIN', None)
        # PDEATHSIG：覆盖 Django runserver 启动失败时 os._exit(1) 跳过 atexit 的路径（见上）
        worker = subprocess.Popen((sys.executable, *_CELERY_ARGS), env=env, preexec_fn=_pdeathsig)
    except Exception:
        logger.warning('aoi celery worker auto-start failed; import falls back to 50300', exc_info=True)
        return None
    atexit.register(stop_celery_worker, worker)
    logger.info('aoi celery worker auto-started (pid=%s)', worker.pid)
    return worker


def stop_celery_worker(worker) -> None:
    """终止 worker 子进程（幂等：已退出则跳过）。"""
    if worker is None or worker.poll() is not None:
        return
    worker.terminate()
    try:
        worker.wait(timeout=10)
    except subprocess.TimeoutExpired:
        worker.kill()
