"""AOI 平台 A 二开包（唯一可写区）。

上游 LS 模块只读；所有二开逻辑集中在 ``label_studio/aoi/``。
注入点见 ``CHANGES.md``「上游基线锁定（D1）」：``core/settings/base.py``、``core/urls.py``、
``web/.../Menubar/Menubar.jsx``、``web/.../pages/index.js``。
"""

default_app_config = None  # 各 app 自带 AppConfig（显式 label），见 aoi/*/apps.py
