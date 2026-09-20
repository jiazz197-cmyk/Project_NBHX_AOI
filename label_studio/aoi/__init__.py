"""AOI 平台 A 二开包（唯一可写区）。

上游 LS 模块只读；所有二开逻辑集中在 ``label_studio/aoi/``。
注入点见 ``CHANGES.md``「上游基线锁定（D1）」：``core/settings/base.py``、``core/urls.py``、
``web/.../Menubar/Menubar.jsx``、``web/.../pages/index.js``。
"""

default_app_config = None  # 各 app 自带 AppConfig（显式 label），见 aoi/*/apps.py

# D5：导入包裹 Celery 异步化。在包导入期绑定 aoi app，使 ``@shared_task``/``.delay()``
# 解析到 ``aoi.celery.app``（契约 §5.2）；celery.py 不在导入期触碰 Django ORM。
from .celery import app as celery_app

__all__ = ('celery_app',)
