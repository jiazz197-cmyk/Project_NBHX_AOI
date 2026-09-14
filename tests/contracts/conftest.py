"""契约测试公共 fixtures（B 归属；D2）。"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
CONTRACTS_DIR = Path(__file__).resolve().parent
FIXTURES_DIR = CONTRACTS_DIR / 'fixtures'

#: 契约测试账号（``test_user`` 与 ``/api/auth/login`` 用例共用，避免两处漂移）
TEST_USER_EMAIL = 'aoi-tester@example.com'
TEST_USER_PASSWORD = 'test-pass-123'

for path in (ROOT / 'label_studio', CONTRACTS_DIR):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))


def pytest_configure(config):
    config.addinivalue_line('markers', 'reuse: LS 原生复用验证 smoke（需要 LS_REUSE_BASE_URL/LS_REUSE_TOKEN）')


@pytest.fixture(autouse=True)
def reset_authz_cache():
    """清空权限判定缓存。

    D4 起权限判定缓存是 ``LocMemCache``（跨用例共享），而用例结束会回滚 ``authz_state.version``：
    若不清空，下一个用例 bump 回同一版本号时会读到上一个用例的陈旧权限集。
    Django 不可用时（例如只跑 ``packages/skillname`` 的纯包测试）直接放行。
    """
    try:
        from django.core.cache import cache
    except Exception:  # pragma: no cover - 纯包测试环境
        yield
        return
    cache.clear()
    yield
    cache.clear()


@pytest.fixture(autouse=True)
def force_fake_publish_mode(request):
    """契约测试一律走 fake 发布模式，且默认不落盘。

    本地 ``.env`` 可能开着 ``AOI_PUBLISH_MODE=registry``（真推 Docker Hub）：测试必须与本地配置解耦，
    否则会联网推仓库、污染外部状态。需要验证 registry 客户端的用例自行改 ``settings.AOI_PUBLISH_MODE``
    并 mock HTTP 层；需要验证落盘的用例用 ``tmp_path`` 覆盖 ``AOI_PUBLISH_ARTIFACTS_DIR``。

    pytest-django 不可用时（例如只跑 ``packages/*`` 或平台 B 的纯包/纯 FastAPI 测试）直接放行，
    不把"零三方依赖"的包测试与 B 侧测试绑死在 Django 的 ``settings`` fixture 上。
    """
    try:
        settings = request.getfixturevalue('settings')
    except Exception:  # pragma: no cover - 无 pytest-django 的测试环境
        yield
        return
    settings.AOI_PUBLISH_MODE = 'fake'
    settings.AOI_PUBLISH_ARTIFACTS_DIR = ''
    yield


@pytest.fixture
def fixtures_dir() -> Path:
    return FIXTURES_DIR


@pytest.fixture
def api_client():
    from rest_framework.test import APIClient

    return APIClient()


@pytest.fixture
def test_user(db):
    """契约测试主账号：默认授予 ``super_admin``。

    D4 起 RBAC 真实生效（无角色 → 40300），既有用例依赖"登录即可访问"，
    故主账号取全权限角色；**RBAC 用例自建各角色用户，不复用本账号**。
    """
    from aoi.core import authz
    from aoi.core.models import Role, UserRole
    from django.contrib.auth import get_user_model

    User = get_user_model()
    user = User.objects.create_user(email=TEST_USER_EMAIL, password=TEST_USER_PASSWORD)
    role = Role.objects.filter(code='super_admin').first()
    if role is not None:
        UserRole.objects.create(user_id=user.id, role_id=role.id)
        authz.bump_version()
    return user


@pytest.fixture
def auth_client(api_client, test_user):
    api_client.force_authenticate(user=test_user)
    return api_client


@pytest.fixture
def internal_headers(settings):
    # Django 测试环境强制 DEBUG=False（fail closed 生效），因此显式配置测试令牌
    if not getattr(settings, 'INTERNAL_TOKEN', ''):
        settings.INTERNAL_TOKEN = 'test-internal-token'
    from aoi.common.settings import get_internal_token

    return {'X-Internal-Token': get_internal_token()}


@pytest.fixture(scope='module')
def jpeg_bytes():
    """最小可解码 JPEG（Pillow 生成）。"""
    from io import BytesIO

    from PIL import Image

    buffer = BytesIO()
    Image.new('RGB', (32, 24), color=(120, 130, 140)).save(buffer, format='JPEG')
    return buffer.getvalue()
