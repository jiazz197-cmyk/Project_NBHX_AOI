"""aoi Celery 应用（契约 §5.2，D5 导入包裹异步化）。

- ``Celery('aoi')``：aoi 二开任务统一 Celery；LS 自带 ``django_rq`` 保持不动（Redis DB 0），
  aoi broker 默认走 Redis DB 1（``CELERY_BROKER_URL``，见 ``core/settings/base.py`` 注入点）。
- ``config_from_object`` 用 ``CELERY_`` 命名空间读 Django settings，配置项全部落在
  ``core/settings/base.py``（带 AOI 注释标记），本模块**不在导入期触碰 Django ORM/DB**。
- worker 启动：``celery -A aoi worker --queues=default --loglevel=info``。
"""

from __future__ import annotations

import os

from celery import Celery

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'core.settings.label_studio')

app = Celery('aoi')
app.config_from_object('django.conf:settings', namespace='CELERY')
app.autodiscover_tasks()
