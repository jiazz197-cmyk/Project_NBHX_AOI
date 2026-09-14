"""aoi 环境变量/设置访问（不在上游 settings 中硬编码）。

配置键清单见 ``docs/P0骨架设计_双平台.md`` §6：``INTERNAL_TOKEN`` 等。
"""

from __future__ import annotations

import hmac
import logging
import os

from django.conf import settings
from django.core.exceptions import ImproperlyConfigured

__all__ = [
    'get_internal_token',
    'internal_token_matches',
    'get_prelabel_require_internal_token',
    'get_model_registry',
    'get_model_image_repo',
    'get_model_registry_user',
    'get_model_registry_password',
    'get_publish_retry',
    'get_publish_mode',
    'get_registry_proxy',
    'get_publish_artifacts_dir',
]

#: 发布模式：``fake`` 纯离线假推送（默认）/ ``registry`` 走 Registry v2 API 真推送
PUBLISH_MODES = ('fake', 'registry')

logger = logging.getLogger(__name__)

#: 仅 ``DEBUG=True``（本地开发/测试）时可用的回落值；生产必须显式配置 INTERNAL_TOKEN
_DEV_INTERNAL_TOKEN = 'dev-internal-token'


def _get(name: str, default: str = '') -> str:
    value = getattr(settings, name, None)
    if value in (None, ''):
        value = os.environ.get(name, default)
    return value or default


def get_internal_token() -> str:
    """``X-Internal-Token`` 校验值（B→A 错图回传，契约 §2.4）。

    **fail closed**：未配置 ``INTERNAL_TOKEN`` 时只有 ``DEBUG=True`` 才回落到开发默认值；
    生产（``DEBUG=False``）直接抛 ``ImproperlyConfigured``，绝不把公开默认值当凭据。
    """
    token = _get('INTERNAL_TOKEN', '')
    if token:
        return token
    if settings.DEBUG:
        return _DEV_INTERNAL_TOKEN
    raise ImproperlyConfigured(
        'INTERNAL_TOKEN is not configured. Set it in .env (see .env.example / P0 §6); '
        'refusing to fall back to the built-in development token.'
    )


def internal_token_matches(provided: str | None) -> bool:
    """恒定时间比较 ``X-Internal-Token``；未配置 / 缺失 / 非 ASCII 一律不通过。

    fail closed：``INTERNAL_TOKEN`` 未配置（生产）时返回 ``False`` 并记 error 日志，
    调用方据此返回 40100，而不是回落到默认凭据。
    """
    try:
        expected = get_internal_token()
    except ImproperlyConfigured:
        logger.error('INTERNAL_TOKEN is not configured; rejecting internal-token request (fail closed)')
        return False
    if not provided:
        return False
    # WSGI header 是 latin-1 str：先编码再比较，避免 hmac.compare_digest 对非 ASCII 抛 TypeError
    return hmac.compare_digest(provided.encode('utf-8', 'ignore'), expected.encode('utf-8'))


def get_prelabel_require_internal_token() -> bool:
    """预标 ML backend 端点是否强制内部头。

    默认 ``False``：LS 1.x ``MLApi`` 只发送 ``User-Agent``（可选 Basic Auth），
    **不携带** ``X-Internal-Token``（见 ``label_studio/ml/api_connector.py`` 的 HEADERS）。
    D2 复用验证日实测确认（回归：``TestPrelabelProtocol::test_optional_internal_token``）；
    如需强制可置 ``AOI_PRELABEL_REQUIRE_INTERNAL_TOKEN=true``。
    """
    raw = _get('AOI_PRELABEL_REQUIRE_INTERNAL_TOKEN', 'false')
    return str(raw).strip().lower() in {'1', 'true', 'yes', 'on'}


def get_model_registry() -> str:
    return _get('MODEL_REGISTRY', 'docker.io')


def get_model_image_repo() -> str:
    return _get('MODEL_IMAGE_REPO', 'aoi/aoi-model')


def get_model_registry_user() -> str:
    return _get('MODEL_REGISTRY_USER', '')


def get_model_registry_password() -> str:
    return _get('MODEL_REGISTRY_PASSWORD', '')


def get_publish_retry() -> int:
    try:
        return int(_get('PUBLISH_RETRY', '3'))
    except (TypeError, ValueError):
        return 3


def get_publish_mode() -> str:
    """发布模式（D3）：``fake``（默认，纯离线）或 ``registry``（Registry v2 真推送）。

    未知取值一律回落 ``fake``（宁可不推，也不误连外网）；D7 真实流水线上线后本开关保留用于离线开发。
    """
    mode = str(_get('AOI_PUBLISH_MODE', 'fake')).strip().lower()
    return mode if mode in PUBLISH_MODES else 'fake'


def get_registry_proxy() -> str:
    """发布推送（registry/auth）专用 HTTP 代理；空 = 直连。

    只作用于 ``aoi.training.publish.RegistryPushClient`` 的会话，不影响平台其它出网流量。
    取值只从 ``AOI_REGISTRY_PROXY`` 环境变量读，**端口等地基信息不写进代码**；
    Docker Hub 直连不通的机器按本机实际代理填写（格式与占位见 ``.env.example``）。
    """
    return _get('AOI_REGISTRY_PROXY', '')


def get_publish_artifacts_dir() -> str:
    """发布产物落盘目录（相对路径按**仓库根**解析）；空字符串 = 不落盘。

    产物（layer/config/manifest + model.yaml + 占位权重）供人工核查与「有网机器手工直推」临时通道，
    默认 ``tmp/publish``——``tmp/`` 已在 ``.gitignore``，不会进版本库。

    **显式空串即关闭**：与其它键不同，这里空串是有效取值（关掉落盘），因此显式设置的
    ``settings.AOI_PUBLISH_ARTIFACTS_DIR``（含空串，测试常用）优先于环境变量，不再回落默认值。
    """
    override = getattr(settings, 'AOI_PUBLISH_ARTIFACTS_DIR', None)
    if override is not None:
        return str(override)
    return os.environ.get('AOI_PUBLISH_ARTIFACTS_DIR', 'tmp/publish')
