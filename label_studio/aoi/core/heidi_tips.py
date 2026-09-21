"""``/heidi-tips`` 遮蔽路由：返回平台自有提示文案（D4）。

上游 ``core/views.py::heidi_tips`` 会**实时代理 GitHub raw** 的 ``liveContent.json``：联网环境
下英文营销文案（Label Studio Enterprise / Starter Cloud）会被前端写进 localStorage，覆盖本地
默认文案；空气隔离环境下则超时回落。因此由 aoi 在 ``aoi/urls.py`` 里注册同名路由**遮蔽**它
（aoi 的 include 排在 ``core/urls.py`` 中上游路由之前）。

返回形状必须与 ``web/.../HeidiTips/types.ts`` 的 ``TipsCollection`` 完全一致，且：

- **必须是 200 + 完整集合**：返回 ``{}`` 会让 ``getRandomTip`` 返回 ``null``（tips 全部消失）；
  返回 404 则前端不更新缓存、**永久沿用旧缓存**（``utils.ts`` 的 stale-while-revalidate）。
- ``link.url`` **必须是绝对地址**：前端 ``createURL`` 内部是 ``new URL(base)``，相对路径会抛错。
"""

from __future__ import annotations

from typing import Any

from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework.views import APIView

__all__ = ['HEIDI_TIP_COLLECTIONS', 'HeidiTipsView']

#: 三个集合与 `TipCollectionKey` 一一对应（projectCreation / projectSettings / organizationPage）
HEIDI_TIP_COLLECTIONS: dict[str, tuple[dict[str, Any], ...]] = {
    'projectCreation': (
        {
            'title': '先建数据集，再进标注',
            'content': 'AOI 流程是：数据集 → 缺陷字典 → 导入图片 → 训练 → 发布模型。直接从「新建项目」建的项目不会纳入 AOI 数据集管理。',
            'closable': True,
            'link': {'label': '前往数据集', 'url': '/datasets'},
        },
        {
            'title': '图片从这里导入',
            'content': '在「数据集」页上传的图片会自动去重并做坏图质检，导入完成后标注页才会出现任务。',
            'closable': True,
            'link': {'label': '打开数据集', 'url': '/datasets'},
        },
    ),
    'projectSettings': (
        {
            'title': '标签来自缺陷字典',
            'content': '标注界面的标签由缺陷字典渲染；改字典请到「数据集 → 缺陷字典」，发布新版本后生效。',
            'closable': True,
            'link': {'label': '打开缺陷字典', 'url': '/datasets'},
        },
        {
            'title': 'OK 图也要标',
            'content': '没有缺陷的图片请提交空标注；训练需要负样本，否则模型会倾向漏检。',
            'closable': True,
            'link': {'label': '查看标注规范', 'url': '/datasets'},
        },
    ),
    'organizationPage': (
        {
            'title': '平台有三个角色',
            'content': '操作员负责标注与复审；管理员负责数据集、训练与模型发布；超级管理员额外管理角色授权与审计。',
            'closable': True,
            'link': {'label': '权限说明', 'url': '/system'},
        },
        {
            'title': '权限在平台内管理',
            'content': 'AOI 的权限不依赖 Label Studio 组织设置，请在「系统」页分配角色。',
            'closable': True,
            'link': {'label': '打开系统页', 'url': '/system'},
        },
    ),
}


def _absolute(uri: str, path: str) -> str:
    """把集合里的相对路径渲染为绝对地址（前端 ``new URL()`` 要求）。"""
    return uri.rstrip('/') + path


class HeidiTipsView(APIView):
    """返回平台自有 tips（原始 JSON，**不使用 aoi 信封**——前端直接当集合读取）。"""

    authentication_classes: list = []
    permission_classes = [AllowAny]

    def get(self, request):
        origin = request.build_absolute_uri('/')
        payload = {
            collection: [
                {**tip, 'link': {**tip['link'], 'url': _absolute(origin, tip['link']['url'])}} for tip in tips
            ]
            for collection, tips in HEIDI_TIP_COLLECTIONS.items()
        }
        return Response(payload)
