"""平台 A 契约测试（T2.8）：信封/鉴权/全量 stub 200/OpenAPI/label config/model.yaml/幂等。

运行：``PYTHONPATH=label_studio .venv/bin/python -m pytest tests/contracts -q``
"""

from __future__ import annotations

import base64
import copy
import gzip
import hashlib
import io
import json
import os
import re
import tarfile
from pathlib import Path
from urllib.parse import parse_qs, urlparse

import pytest
import requests
import requests_mock
import yaml
from aoi.common.settings import get_internal_token
from conftest import TEST_USER_EMAIL, TEST_USER_PASSWORD
from django.core.files.uploadedfile import SimpleUploadedFile
from django.urls import Resolver404, resolve
from rest_framework.test import APIClient
from samples import (
    build_model_yaml_sample,
    label_config_sample_defects,
    ml_backend_sample,
    model_manifest_sample,
    model_yaml_sample_inputs,
)

FIXTURES = Path(__file__).parent / 'fixtures'

#: 测试专用代理占位值：端口等本机地基信息**不进代码**，用例只验证「代理被挂到发布客户端会话上」。
#: 需要指向真实代理时用环境变量覆盖（``export TEST_REGISTRY_PROXY=http://host:port``）。
REGISTRY_PROXY_FOR_TESTS = os.environ.get('TEST_REGISTRY_PROXY', 'http://proxy.invalid:3128')

METHOD_CALL = {
    'GET': 'get',
    'POST': 'post',
    'PUT': 'put',
    'DELETE': 'delete',
    'PATCH': 'patch',
}


def load_json(name: str):
    return json.loads((FIXTURES / name).read_text(encoding='utf-8'))


def load_text(name: str) -> str:
    return (FIXTURES / name).read_text(encoding='utf-8')


def load_yaml(name: str):
    return yaml.safe_load(load_text(name))


def assert_envelope(response, code: int = 0):
    body = response.json()
    assert set(body) >= {'code', 'message', 'request_id', 'data'}
    assert body['code'] == code, body
    assert isinstance(body['request_id'], str) and body['request_id']
    return body


def materialize(path: str) -> str:
    return path.replace('{id}', '1').replace('{job_id}', 'stub-job').replace('{task_id}', '1').replace('{v}', '1.0.0')


def payload_for(entry: dict, predict_request: dict | None = None):
    method, path = entry['method'], entry['path']
    if path == '/api/core/roles' and method == 'POST':
        return {'code': 'qa_reviewer', 'name_cn': 'QA 复审员'}
    if path == '/api/core/users/{id}/roles':
        # D4 起为全量覆盖语义：不能传空数组，否则会清空调用者自己的角色，后续用例全变 40300
        return {'roles': ['super_admin']}
    if path == '/api/datasets/defects' and method in ('POST', 'PUT'):
        return {'code': 'object_fault_type_01', 'name_cn': '划伤', 'risk_level': 3}
    if path == '/api/datasets/defects/publish':
        return {'defects': label_config_sample_defects()}
    if path == '/api/datasets' and method == 'POST':
        return {'name': 'stub-dataset'}
    if path.endswith('/versions') and method == 'POST':
        return {'version': '1.0.0'}
    if path == '/api/train/jobs' and method == 'POST':
        return {'dataset_version': '1.0.0', 'framework': 'yolo', 'preset': {'class_subset': ['object_fault_type_01']}}
    if path == '/api/train/models/{id}/approve':
        return {'decision': 'approve', 'note': 'ok'}
    if path == '/api/prelabel/tasks' and method == 'POST':
        return {'dataset_id': 1, 'model_ref': '3-yolo@ds1'}
    if path == '/api/prelabel/{task_id}/predict':
        return predict_request or {}
    if path == '/api/review/workitems/{id}/finalize':
        return {'verdict': 'defect_confirmed', 'final_reason': 'misdetection'}
    if path == '/api/review/suggestions/batch-confirm':
        return {'ids': []}
    return {}


# --------------------------------------------------------------------------- envelope
@pytest.mark.django_db
class TestEnvelopeAndAuth:
    def test_envelope_shape(self, auth_client):
        response = auth_client.get('/api/core/permissions')
        assert response.status_code == 200
        body = assert_envelope(response)
        assert body['message'] == 'ok'
        assert body['data']['user_id'] is not None
        # D4：RBAC 真实生效；`test_user` 持 super_admin → 全码
        assert body['data']['roles'] == ['super_admin']
        assert 'system.roles' in body['data']['perms']

    def test_unauthenticated_returns_40100(self, api_client):
        response = api_client.get('/api/core/permissions')
        assert response.status_code == 401
        assert_envelope(response, code=40100)

    def test_request_id_passthrough(self, auth_client):
        response = auth_client.get('/api/core/permissions', HTTP_X_REQUEST_ID='req-contract-1')
        assert response.status_code == 200
        assert response.json()['request_id'] == 'req-contract-1'
        assert response['X-Request-ID'] == 'req-contract-1'

    def test_pagination_envelope(self, auth_client):
        response = auth_client.get('/api/datasets/images')
        assert response.status_code == 200
        body = assert_envelope(response)
        assert set(body['data']) == {'total', 'items'}

    def test_idempotency_key_accepted(self, auth_client):
        response = auth_client.post(
            '/api/datasets', {'name': 'with-idem'}, format='json', HTTP_IDEMPOTENCY_KEY='idem-1'
        )
        assert response.status_code == 200
        assert_envelope(response)


# ------------------------------------------------------------------- auth (D3 认证链路)
def decode_jwt_payload(token: str) -> dict:
    """只解 claims，不验签（测试用；与 LS 复用 smoke 的 `_decode_claims` 同源）。"""
    payload = token.split('.')[1]
    payload += '=' * (-len(payload) % 4)
    return json.loads(base64.urlsafe_b64decode(payload))


@pytest.mark.django_db
class TestAoiJwtAuth:
    """D3：Bearer JWT 由 DRF 认证类承担（``jwt_auth`` 中间件已移除），登录/登出为 aoi 自有端点。"""

    @staticmethod
    def _login(client, email=TEST_USER_EMAIL, password=TEST_USER_PASSWORD):
        return client.post('/api/auth/login', {'email': email, 'password': password}, format='json')

    def test_login_issues_access_and_refresh(self, api_client, test_user):
        response = self._login(api_client)
        assert response.status_code == 200, response.content[:300]
        data = assert_envelope(response)['data']
        assert data['token_type'] == 'Bearer'
        assert data['expires_in'] > 0
        assert data['user'] == {'id': test_user.id, 'email': test_user.email}

        access_claims = decode_jwt_payload(data['access'])
        assert access_claims['token_type'] == 'access'
        assert int(access_claims['user_id']) == test_user.id  # simplejwt 的 user_id claim 是字符串
        refresh_claims = decode_jwt_payload(data['refresh'])
        assert refresh_claims['token_type'] == 'refresh'
        assert int(refresh_claims['user_id']) == test_user.id

    def test_bearer_authenticates_aoi_endpoint(self, api_client, test_user):
        """不加 force_authenticate：走真实 DRF 认证类（这是本改动的核心断言）。"""
        access = assert_envelope(self._login(api_client))['data']['access']
        client = APIClient()
        response = client.get('/api/core/permissions', HTTP_AUTHORIZATION=f'Bearer {access}')
        assert response.status_code == 200, response.content[:300]
        assert assert_envelope(response)['data']['user_id'] == test_user.id

    def test_bearer_authenticates_ls_native_endpoint(self, api_client, test_user):
        """LS 原生 DRF 端点同样识别 Bearer（与 /data/upload 同一认证链）。"""
        access = assert_envelope(self._login(api_client))['data']['access']
        client = APIClient()
        response = client.get('/api/current-user/whoami', HTTP_AUTHORIZATION=f'Bearer {access}')
        assert response.status_code == 200, response.content[:300]
        assert response.json()['email'] == test_user.email

    def test_browser_session_login_still_works(self, api_client, test_user):
        """浏览器链路不受影响：走 LS 原生 ``/user/login/``（sessionid + ``session['last_login']``）。

        注：不能用 Django 测试客户端的 ``client.login()`` 代替——它绕过 LS 的登录包装
        （``users/functions/common.py::login`` 会写 ``session['last_login']``），
        会被 ``InactivitySessionTimeoutMiddleWare`` 当成长时间未活动立即登出。
        """
        from organizations.models import Organization

        Organization.create_organization(created_by=test_user, title='AOI Session Contract')
        page = api_client.get('/user/login/')
        assert page.status_code == 200
        csrf = api_client.cookies['csrftoken'].value
        response = api_client.post(
            '/user/login/',
            {'email': TEST_USER_EMAIL, 'password': TEST_USER_PASSWORD},
            HTTP_X_CSRFTOKEN=csrf,
        )
        assert response.status_code in (200, 302), response.content[:200]

        permissions = api_client.get('/api/core/permissions')
        assert permissions.status_code == 200, permissions.content[:200]
        assert assert_envelope(permissions)['data']['user_id'] == test_user.id

    def test_invalid_bearer_is_40100(self, api_client):
        client = APIClient()
        response = client.get('/api/core/permissions', HTTP_AUTHORIZATION='Bearer not-a-jwt')
        assert response.status_code == 401
        body = assert_envelope(response, code=40100)
        # message 必须是人类可读文案，不能是 simplejwt 嵌套 detail 的 Python repr
        assert '{' not in body['message'] and body['message']

    def test_expired_or_foreign_signature_bearer_is_40100(self, api_client, test_user):
        """签名不匹配的 Bearer：DRF 认证类直接拒绝（不再静默降级为匿名）。"""
        from rest_framework_simplejwt.tokens import AccessToken

        token = AccessToken.for_user(test_user)
        # 篡改签名段，保持结构合法
        forged = '.'.join(token.__str__().split('.')[:2] + ['x' * 43])
        response = api_client.get('/api/core/permissions', HTTP_AUTHORIZATION=f'Bearer {forged}')
        assert response.status_code == 401
        assert_envelope(response, code=40100)

    def test_refresh_exchanges_for_access(self, api_client, test_user):
        refresh = assert_envelope(self._login(api_client))['data']['refresh']
        response = api_client.post('/api/token/refresh/', {'refresh': refresh}, format='json')
        assert response.status_code == 200, response.content[:300]
        assert decode_jwt_payload(response.json()['access'])['token_type'] == 'access'

    def test_wrong_password_is_40100(self, api_client, test_user):
        response = self._login(api_client, password='wrong-password')
        assert response.status_code == 401
        assert_envelope(response, code=40100)

    def test_unknown_email_is_40100(self, api_client, db):
        response = self._login(api_client, email='nobody@example.com')
        assert response.status_code == 401
        assert_envelope(response, code=40100)

    def test_missing_password_is_42200(self, api_client, db):
        response = api_client.post('/api/auth/login', {'email': TEST_USER_EMAIL}, format='json')
        assert response.status_code == 422
        body = assert_envelope(response, code=42200)
        assert 'password' in body['data']['detail']['fields']

    def test_logout_blacklists_refresh(self, api_client, test_user):
        login = assert_envelope(self._login(api_client))['data']
        client = APIClient()
        response = client.post(
            '/api/auth/logout',
            {'refresh': login['refresh']},
            format='json',
            HTTP_AUTHORIZATION=f'Bearer {login["access"]}',
        )
        assert response.status_code == 200, response.content[:300]
        assert assert_envelope(response)['data'] == {'revoked': True}

        # 已吊销的 refresh 不能再换 access（上游端点，错误响应不走 aoi 信封）
        assert client.post('/api/token/refresh/', {'refresh': login['refresh']}, format='json').status_code == 401

    def test_logout_is_idempotent(self, api_client, test_user):
        login = assert_envelope(self._login(api_client))['data']
        headers = {'HTTP_AUTHORIZATION': f'Bearer {login["access"]}'}
        first = api_client.post('/api/auth/logout', {'refresh': login['refresh']}, format='json', **headers)
        assert assert_envelope(first)['data'] == {'revoked': True}
        second = api_client.post('/api/auth/logout', {'refresh': login['refresh']}, format='json', **headers)
        assert second.status_code == 200
        assert assert_envelope(second)['data'] == {'revoked': False}

    def test_logout_without_refresh_is_noop(self, auth_client):
        response = auth_client.post('/api/auth/logout', {}, format='json')
        assert response.status_code == 200
        assert assert_envelope(response)['data'] == {'revoked': False}

    def test_logout_requires_authentication(self, api_client):
        response = api_client.post('/api/auth/logout', {}, format='json')
        assert response.status_code == 401
        assert_envelope(response, code=40100)

    def test_logout_rejects_foreign_refresh(self, api_client, test_user, db):
        """不能拿别人的 refresh 做吊销。"""
        from django.contrib.auth import get_user_model

        other = get_user_model().objects.create_user(email='other@example.com', password='other-pass-123')
        other_refresh = assert_envelope(self._login(api_client, email=other.email, password='other-pass-123'))['data'][
            'refresh'
        ]
        mine = assert_envelope(self._login(api_client))['data']
        response = api_client.post(
            '/api/auth/logout',
            {'refresh': other_refresh},
            format='json',
            HTTP_AUTHORIZATION=f'Bearer {mine["access"]}',
        )
        assert response.status_code == 403
        assert_envelope(response, code=40300)
        assert other.is_active

    def test_jwt_middleware_removed_auth_classes_configured(self):
        """回归守卫：认证不再依赖 Django 中间件。"""
        from django.conf import settings

        assert 'jwt_auth.middleware.JWTAuthenticationMiddleware' not in settings.MIDDLEWARE
        assert (
            'aoi.common.authentication.AoiJWTAuthentication'
            in settings.REST_FRAMEWORK['DEFAULT_AUTHENTICATION_CLASSES']
        )
        assert settings.SIMPLE_JWT['AUTH_HEADER_TYPES'] == ('Bearer',)


# ----------------------------------------------------------------------------- paths
@pytest.mark.django_db
class TestPathContract:
    def test_datasets_path_contract(self, auth_client):
        """T2.9 四件套：新路径 200、旧路径 404。"""
        response = auth_client.get('/api/datasets/1')
        assert response.status_code == 200
        body = assert_envelope(response)
        assert body['data']['id'] == 1

        assert auth_client.get('/api/datasets/datasets').status_code == 404
        assert auth_client.get('/api/datasets/datasets/1').status_code == 404

    def test_route_and_openapi_baseline(self):
        from drf_spectacular.generators import SchemaGenerator

        baseline = load_json('aoi_api_paths.json')
        paths = baseline['paths']
        assert any(entry['path'] == '/api/datasets/{id}' for entry in paths)
        assert not any(entry['path'].startswith('/api/datasets/datasets') for entry in paths)

        for entry in paths:
            url = materialize(entry['path'])
            try:
                resolve(url)
            except Resolver404 as exc:  # pragma: no cover - 失败时给出清晰信息
                raise AssertionError(f'route not resolved: {url}') from exc

        schema = SchemaGenerator().get_schema(public=True)
        schema_paths = schema['paths']
        for entry in paths:
            assert entry['path'] in schema_paths, f'OpenAPI missing {entry["path"]}'
            assert entry['method'].lower() in schema_paths[entry['path']], (
                f'OpenAPI missing {entry["method"]} {entry["path"]}'
            )

        # 基线 == OpenAPI aoi 路径集合（不多不少），方法集合也一致
        # 注：/api/auth 下上游还有 /api/auth/export/（@extend_schema(exclude=True)，不进 schema），
        # 因此按"精确路径"而不是前缀纳入基线。
        prefixes = (
            '/api/auth/login',
            '/api/auth/logout',
            '/api/core',
            '/api/datasets',
            '/api/train',
            '/api/prelabel',
            '/api/review',
            '/api/system',
            '/api/ingest',
        )
        schema_aoi = {path for path in schema_paths if path.startswith(prefixes)}
        assert schema_aoi == {entry['path'] for entry in paths}
        expected_methods: dict[str, set[str]] = {}
        for entry in paths:
            expected_methods.setdefault(entry['path'], set()).add(entry['method'].lower())
        for path, methods in expected_methods.items():
            assert set(schema_paths[path]) == methods, (path, set(schema_paths[path]), methods)

        assert '/api/datasets/datasets' not in schema_paths
        assert '/api/datasets/datasets/{id}' not in schema_paths


@pytest.mark.django_db
class TestExportContract:
    def test_yolo_export_layout_contract(self, auth_client):
        """契约 §9 修正：LS 原生产物无 data.yaml，classes.txt 为准。"""
        layout = load_json('yolo_export_layout_sample.json')
        assert layout['has_data_yaml'] is False
        assert 'classes.txt' in layout['entries'] and 'data.yaml' not in layout['entries']
        assert layout['classes_source'] == 'classes.txt'

        response = auth_client.get('/api/datasets/1/versions/1.0.0/export')
        assert response.status_code == 200
        data = assert_envelope(response)['data']
        assert data['format'] == 'yolo'
        assert data['classes_source'] == 'classes.txt'
        assert data['data_yaml'] is None


@pytest.mark.django_db
class TestTaskDetailConcatRegression:
    """D2 已知问题回归：云存储 provider 清理后单 link name 不应触发 Concat 500。

    根因：清理云存储 provider 后 import link name ≤1 个，`Concat` 位置表达式不足 2 个 → 详情必然 500；
    修复位于 data_manager/managers.py::annotate_storage_filename，本用例即其回归证据。
    """

    @pytest.mark.parametrize(
        'link_names',
        [
            [],
            ['io_storages_localfilesimportstoragelink'],
            ['io_storages_localfilesimportstoragelink', 'io_storages_localfilesimportstoragelink'],
        ],
    )
    def test_annotate_storage_filename_0_1_2_links(self, link_names):
        from data_manager.managers import annotate_storage_filename
        from django.test import override_settings
        from tasks.models import Task

        with override_settings(IO_STORAGES_IMPORT_LINK_NAMES=link_names):
            queryset = annotate_storage_filename(Task.objects.all())
            assert 'storage_filename' in queryset.query.annotations

    def test_task_detail_annotation_queryset_all_fields(self):
        """任务详情真实调用链：all_fields=True 不再抛 Concat ValueError。"""
        from data_manager.managers import PreparedTaskManager
        from tasks.models import Task

        PreparedTaskManager.annotate_queryset(Task.objects.all(), all_fields=True)

    def test_task_detail_api_returns_200(self, auth_client, test_user):
        from organizations.models import Organization
        from projects.models import Project
        from tasks.models import Task

        organization = Organization.objects.first()
        if organization is None:
            organization = Organization.create_organization(created_by=test_user, title='AOI Regression')
        test_user.active_organization = organization
        test_user.save(update_fields=['active_organization'])
        project = Project.objects.create(
            title='concat-regression',
            organization=organization,
            created_by=test_user,
            label_config='<View></View>',
        )
        task = Task.objects.create(project=project, data={'image': 'http://example.com/regression.jpg'})
        response = auth_client.get(f'/api/tasks/{task.id}/')
        assert response.status_code == 200, response.content[:500]


@pytest.mark.django_db
def _reset_review_workitem():
    """P1 起 finalize/claim 是真实状态机：每个写请求前重置一条 pending 工作项。

    注意：**不指定 pk**（显式写 pk 会让 Postgres 序列停在旧值，后续自增插入撞主键）。
    """
    from aoi.review.models import ReviewWorkitem

    ReviewWorkitem.objects.all().delete()
    return ReviewWorkitem.objects.create(
        fact_id=None,
        source=ReviewWorkitem.SOURCE_PRELABEL,
        dataset_version_id=1,
        model_ref='3-yolo@ds1',
        bucket=ReviewWorkitem.BUCKET_MEDIUM,
        verdict='recheck',
        forced=False,
        route=ReviewWorkitem.ROUTE_MANUAL,
        status=ReviewWorkitem.STATUS_PENDING,
    )


class TestAllStubs:
    @pytest.fixture(autouse=True)
    def _ingest_token(self, settings):
        # Django 测试环境强制 DEBUG=False（P0 fail closed 生效），显式配置测试令牌
        settings.INTERNAL_TOKEN = 'test-internal-token'

    @pytest.fixture(autouse=True)
    def _seed_training_model(self, db):
        """P1 起 approve/publish 走真实语义（40401 + 门禁 + lifecycle），需要真实 Model 行。"""
        from aoi.training.models import Model

        Model.objects.update_or_create(
            pk=1,
            defaults={
                'version': '1-yolo@ds1',
                'framework': 'yolo',
                'dataset_version': '1',
                'precision': 'fp32',
                'class_names': ['object_fault_type_01'],
                'cover_classes': ['object_fault_type_01'],
                'gate_status': Model.GATE_PASSED,
                'lifecycle': Model.LIFECYCLE_APPROVED,
            },
        )

    def test_all_aoi_endpoints_return_200(self, api_client, test_user, jpeg_bytes):
        baseline = load_json('aoi_api_paths.json')
        predict_request = ml_backend_sample()['endpoints']['predict']['request']
        client = APIClient()

        for entry in baseline['paths']:
            method, path, auth = entry['method'], entry['path'], entry.get('auth', 'jwt')
            url = materialize(path)
            if path == '/api/core/users/{id}/roles':
                # P1：分配角色要求用户真实存在，用当前测试用户
                url = f'/api/core/users/{test_user.id}/roles'
            expected_status = 200

            if path == '/api/ingest/findings':
                client.force_authenticate(user=None)
                meta = {
                    'kind': 'suspicious',
                    'instance_code': 'B01',
                    'station_code': 'ST01',
                    'seq': 1042,
                    'verdict': 'recheck',
                    'captured_at': '2026-09-08T08:31:00Z',
                }
                response = client.post(
                    url,
                    {
                        'meta': json.dumps(meta),
                        'file': SimpleUploadedFile('a.jpg', jpeg_bytes, content_type='image/jpeg'),
                    },
                    format='multipart',
                    HTTP_X_INTERNAL_TOKEN=get_internal_token(),
                )
                assert response.status_code == 200, (method, path, response.content[:200])
                assert_envelope(response)
                continue

            if path == '/api/auth/login':
                # 匿名端点：真实凭据换取令牌（凭证来自 conftest，与 test_user 同源）
                client.force_authenticate(user=None)
                response = client.post(
                    url,
                    {'email': TEST_USER_EMAIL, 'password': TEST_USER_PASSWORD},
                    format='json',
                )
                assert response.status_code == 200, (method, path, response.content[:200])
                assert_envelope(response)
                continue

            if path == '/api/core/roles/{id}' and method == 'DELETE':
                # P1：内置角色不可删除（id=1 是 operator）
                expected_status = 409
            if path.startswith('/api/review/workitems/') and method == 'POST':
                workitem = _reset_review_workitem()
                url = f'/api/review/workitems/{workitem.id}/{path.rsplit("/", 1)[-1]}'

            if auth == 'jwt':
                client.force_authenticate(user=test_user)
            else:
                client.force_authenticate(user=None)

            if path.endswith('/progress'):
                response = client.get(url)
                assert response.status_code == 200, (method, path)
                content = b''.join(response.streaming_content)
                assert b'"phase": "finished"' in content
                continue

            if auth == 'optional-internal-token':
                # ML backend 官方协议：顶层字段，不使用 aoi 信封
                call = getattr(client, METHOD_CALL[method])
                data = payload_for(entry, predict_request)
                response = call(url) if method == 'GET' else call(url, data, format='json')
                assert response.status_code == 200, (method, path, response.status_code)
                assert isinstance(response.json(), dict)
                continue

            call = getattr(client, METHOD_CALL[method])
            data = payload_for(entry, predict_request)
            if method == 'GET':
                response = call(url)
            elif method == 'DELETE':
                response = call(url)
            else:
                response = call(url, data, format='json')

            assert response.status_code == expected_status, (
                method,
                path,
                response.status_code,
                response.content[:300],
            )
            if expected_status == 200:
                body = assert_envelope(response)
                assert 'data' in body
            else:
                assert_envelope(response, code=40900)

    def test_review_finalize_requires_reason(self, auth_client):
        response = auth_client.post('/api/review/workitems/1/finalize', {}, format='json')
        assert response.status_code == 422
        body = assert_envelope(response, code=42200)
        assert 'final_reason' in body['data']['detail']['fields']


# ----------------------------------------------------------------------- label config
@pytest.mark.django_db
class TestLabelConfig:
    def test_golden_fixture(self):
        from aoi.datasets.label_config import render_label_config

        expected = load_text('label_config_expected.xml')
        assert render_label_config(label_config_sample_defects()) == expected
        assert expected.startswith('<View><Image name="image" value="$image"/><RectangleLabels name="defect"')
        assert 'object_fault_type_01' in expected
        assert 'object_fault_type_02' in expected

    def test_label_config_passes_ls_native_validator(self):
        """T2.2 产出的 label config 必须通过 LS 自身解析器（不是自定义格式）。"""
        from core.label_config import validate_label_config

        validate_label_config(load_text('label_config_expected.xml'))

    def test_publish_returns_golden_and_snapshot(self, auth_client):
        from aoi.datasets.models import DefectDictVersion

        response = auth_client.post(
            '/api/datasets/defects/publish', {'defects': label_config_sample_defects()}, format='json'
        )
        assert response.status_code == 200
        body = assert_envelope(response)
        assert body['data']['label_config'] == load_text('label_config_expected.xml')

        row = DefectDictVersion.objects.get(version=body['data']['version'])
        assert row.snapshot == {
            'labels': {
                'object_fault_type_01': {'index': 0, 'color': '#FF4D4F'},
                'object_fault_type_02': {'index': 1, 'color': '#FA8C16'},
            }
        }

    def test_invalid_code_42200(self, auth_client):
        response = auth_client.post(
            '/api/datasets/defects/publish', {'defects': [{'code': 'object_fault_type_1'}]}, format='json'
        )
        assert response.status_code == 422
        body = assert_envelope(response, code=42200)
        assert 'defects[0].code' in body['data']['detail']['fields']

    def test_duplicate_code_42200(self, auth_client):
        defects = [
            {'code': 'object_fault_type_01', 'index': 0},
            {'code': 'object_fault_type_01', 'index': 1},
        ]
        response = auth_client.post('/api/datasets/defects/publish', {'defects': defects}, format='json')
        assert response.status_code == 422
        assert_envelope(response, code=42200)


# ------------------------------------------------------------------------- model.yaml
class TestModelYaml:
    def test_fixture_roundtrip_and_validation(self):
        from aoi.training.model_yaml import validate_model_yaml
        from skillname import image_tag_from_model_ref, parse_model_ref

        doc = load_yaml('model_yaml_sample.yaml')
        assert validate_model_yaml(doc) == []
        assert doc['schema_version'] == 1
        assert parse_model_ref(doc['model_ref']).seq == 3
        assert image_tag_from_model_ref(doc['model_ref'], doc['precision']) == '3-yolo-ds1'
        for key in ('onnx', 'classes', 'postprocess', 'tiling', 'thresholds', 'metrics', 'requires'):
            assert key in doc
        assert doc['signature'] is None and doc['extensions'] == {}
        # P2：把契约 §2.3 的关键字面量钉死在测试里（fixture 由被测生成器再生成，
        # 只比较 fixture == build_* 会跟着实现一起错）
        assert doc['model_ref'] == '3-yolo@ds1'
        assert doc['skillname'] == 'ObjectDetection'
        assert doc['framework'] == 'yolo'
        assert doc['precision'] == 'fp32'
        assert doc['gate_status'] == 'passed'
        assert doc['onnx']['file'] == 'model.onnx'
        assert len(doc['onnx']['sha256']) == 64
        assert doc['onnx']['input']['name'] == 'images'
        assert doc['onnx']['output']['name'] == 'output0'
        assert doc['requires'] == {
            'skillname': '>=0.1.0',
            'pipeline_core': '>=0.1.0',
            'schema_version': '>=1',
            'onnxruntime': '>=1.18',
            'cuda': None,
            'vram_gb': 4,
        }
        assert [(entry['index'], entry['code']) for entry in doc['classes']] == [
            (0, 'object_fault_type_01'),
            (1, 'object_fault_type_02'),
        ]
        assert doc['classes'][0]['recommended'] == {'recheck_min': 0.6, 'auto_min': 0.9}
        assert doc['thresholds']['default'] == {'recheck_min': 0.5, 'auto_min': 0.9}
        assert doc['tiling']['recommended_tile_size'] == 1280

    def test_validation_catches_contract_errors(self):
        from aoi.training.model_yaml import validate_model_yaml

        doc = load_yaml('model_yaml_sample.yaml')
        broken = copy.deepcopy(doc)
        broken['onnx'].pop('sha256')
        broken['classes'][0]['recommended'] = {'recheck_min': 0.9, 'auto_min': 0.5}
        broken['classes'][1]['code'] = 'object_fault_type_01'
        errors = validate_model_yaml(broken)
        assert any('onnx.sha256' in error for error in errors)
        assert any('recommended' in error for error in errors)
        assert any('duplicated' in error for error in errors)

    @pytest.mark.parametrize('schema_version', [0, 2, '1', None, 'x'])
    def test_unknown_schema_version_rejected(self, schema_version):
        """契约 §2.3 规则 2 / §2.6：未知 ``schema_version`` 必须拒绝（A 侧子集）。"""
        from aoi.training.model_yaml import validate_model_yaml

        broken = load_yaml('model_yaml_sample.yaml')
        broken['schema_version'] = schema_version
        assert any('schema_version' in error for error in validate_model_yaml(broken))

    @pytest.mark.parametrize('skillname_value', ['Classification', 'ObjectDetectionV2', None])
    def test_unknown_skillname_rejected(self, skillname_value):
        """契约 §2.3 规则 3：``skillname`` 必须来自枚举。"""
        from aoi.training.model_yaml import validate_model_yaml

        broken = load_yaml('model_yaml_sample.yaml')
        broken['skillname'] = skillname_value
        assert any('skillname' in error for error in validate_model_yaml(broken))

    def test_output_shape_class_dim(self):
        from aoi.training.model_yaml import validate_model_yaml

        doc = load_yaml('model_yaml_sample.yaml')
        for shape in ([1, 6, 8400], [1, 7, 8400], [1, 2, 8400]):  # 4+nc / 5+nc / nc
            candidate = copy.deepcopy(doc)
            candidate['onnx']['output']['shape'] = shape
            assert not any('output.shape' in error for error in validate_model_yaml(candidate)), shape
        broken = copy.deepcopy(doc)
        broken['onnx']['output']['shape'] = [1, 9, 8400]
        assert any('output.shape' in error for error in validate_model_yaml(broken))

    def test_dump_is_stable_yaml(self):
        from aoi.training.model_yaml import dump_model_yaml, validate_model_yaml

        doc = build_model_yaml_sample()
        dumped = dump_model_yaml(doc)
        assert dumped.startswith('schema_version: 1\n')
        assert '门板表面缺陷检测 v3' in dumped
        assert yaml.safe_load(dumped) == doc
        assert validate_model_yaml(yaml.safe_load(dumped)) == []

    def test_manifest_fixture_consistent(self):
        from skillname import image_tag_from_model_ref

        manifest = load_json('model_manifest_sample.json')
        doc = load_yaml('model_yaml_sample.yaml')
        assert manifest['schemaVersion'] == 2
        assert manifest['annotations']['aoi.model_ref'] == doc['model_ref']
        assert manifest['annotations']['aoi.skillname'] == doc['skillname']
        assert manifest['annotations']['org.opencontainers.image.ref.name'] == image_tag_from_model_ref(
            doc['model_ref'], doc['precision']
        )
        import hashlib

        expected_yaml_sha = hashlib.sha256((FIXTURES / 'model_yaml_sample.yaml').read_bytes()).hexdigest()
        assert manifest['annotations']['aoi.model_yaml_sha256'] == expected_yaml_sha
        assert manifest['layers'][0]['digest'].startswith('sha256:')

    def test_training_models_task_type_default(self):
        from aoi.training.models import BaseModel, Model, Preset, TrainJob
        from skillname import SkillName

        for model_cls in (BaseModel, Preset, TrainJob, Model):
            assert model_cls._meta.get_field('task_type').default == SkillName.OBJECT_DETECTION.value

    def test_generator_matches_sample_inputs(self):
        inputs = model_yaml_sample_inputs()
        assert inputs['model']['class_names'] == ['object_fault_type_01', 'object_fault_type_02']
        assert len(inputs['onnx_meta']['sha256']) == 64
        assert model_manifest_sample()['annotations']['aoi.precision'] == inputs['model']['precision']


# ---------------------------------------------------------------------------- prelabel
@pytest.mark.django_db
class TestPrelabelProtocol:
    def test_protocol_responses_match_fixture(self, api_client):
        """P2：比对**磁盘上的 fixture 文件**（而不是与实现同源的 samples 常量），
        这样协议常量被改错时测试才会红。"""
        fixture = load_json('ml_backend_predict_sample.json')
        client = APIClient()

        response = client.get('/api/prelabel/1/health')
        assert response.status_code == 200
        assert response.json() == fixture['endpoints']['health']['response']

        response = client.post('/api/prelabel/1/setup', {}, format='json')
        assert response.status_code == 200
        assert response.json() == fixture['endpoints']['setup']['response']

        response = client.post('/api/prelabel/1/predict', fixture['endpoints']['predict']['request'], format='json')
        assert response.status_code == 200
        assert response.json() == fixture['endpoints']['predict']['response']

        response = client.post('/api/prelabel/1/validate', {}, format='json')
        assert response.status_code == 200
        assert response.json() == fixture['endpoints']['validate']['response']

    def test_fixture_matches_protocol_constants(self):
        """fixture 文件与 ``aoi.prelabel.protocol`` 常量必须一致（谁改错都会红）。"""
        from aoi.prelabel import protocol

        fixture = load_json('ml_backend_predict_sample.json')
        assert fixture['endpoints']['health']['response'] == protocol.HEALTH_RESPONSE
        assert fixture['endpoints']['setup']['response'] == protocol.SETUP_RESPONSE
        assert fixture['endpoints']['validate']['response'] == protocol.VALIDATE_RESPONSE
        expected_predict = protocol.build_predict_response(fixture['endpoints']['predict']['request']['tasks'])
        assert fixture['endpoints']['predict']['response'] == expected_predict

    def test_predict_batch_order_and_count(self, api_client):
        """批量预标：按请求顺序一一返回同数量 results（契约 §4.3）。"""
        payload = {
            'tasks': [
                {'id': 101, 'data': {'image': 'http://example.com/1.jpg'}},
                {'id': 102, 'data': {'image': 'http://example.com/2.jpg'}},
            ]
        }
        response = api_client.post('/api/prelabel/1/predict', payload, format='json')
        assert response.status_code == 200
        results = response.json()['results']
        assert [item['id'] for item in results] == [101, 102]

    def test_optional_internal_token(self, api_client):
        from django.test import override_settings

        # 默认：LS 不携带内部头 → 放行（D2 复用验证日实测：仅 User-Agent）
        assert api_client.get('/api/prelabel/1/health').status_code == 200

        with override_settings(AOI_PRELABEL_REQUIRE_INTERNAL_TOKEN=True, INTERNAL_TOKEN='secret-token'):
            assert api_client.get('/api/prelabel/1/health').status_code == 401
            assert api_client.get('/api/prelabel/1/health', HTTP_X_INTERNAL_TOKEN='wrong').status_code == 401
            response = api_client.get('/api/prelabel/1/health', HTTP_X_INTERNAL_TOKEN='secret-token')
            assert response.status_code == 200
            assert response.json()['status'] == 'UP'


# ------------------------------------------------------------------------------ ingest
@pytest.mark.django_db
class TestReviewFlowContract:
    """D2 三桶复审确认：高绿自动 / 中黄建议 / 低红强制；phase/scope/阈值样例。"""

    def test_fixture_shape(self):
        sample = load_json('review_flow_sample.json')
        assert sample['scope'] == 'unlabeled_only'
        assert sample['thresholds_priority'] == ['model.yaml.recommended', 'prelabel_task.route_config']
        assert sample['bucket_colors'] == {'high': '#52C41A', 'medium': '#FAAD14', 'low': '#FF4D4F'}
        buckets = {item['bucket']: item for item in sample['workitems']}
        assert buckets['high']['verdict'] == 'auto_pass' and buckets['high']['forced'] is False
        assert buckets['medium']['verdict'] == 'recheck' and buckets['medium']['forced'] is False
        assert buckets['low']['verdict'] == 'manual' and buckets['low']['forced'] is True

    def test_workitem_list_exposes_bucket_fields(self, auth_client):
        """P2：空队列必须返回空列表；真实行的 bucket/颜色由 verdict 派生。"""
        from aoi.review.models import ReviewWorkitem

        empty = auth_client.get('/api/review/workitems')
        assert empty.status_code == 200
        assert assert_envelope(empty)['data']['items'] == []

        ReviewWorkitem.objects.create(
            source=ReviewWorkitem.SOURCE_PRELABEL,
            dataset_version_id=1,
            model_ref='3-yolo@ds1',
            verdict='manual',
            bucket=None,  # 由 verdict 派生（不允许前端硬编码映射）
            forced=True,
            route=ReviewWorkitem.ROUTE_MANUAL,
            status=ReviewWorkitem.STATUS_PENDING,
        )
        response = auth_client.get('/api/review/workitems')
        assert response.status_code == 200
        body = assert_envelope(response)
        assert body['data']['total'] == 1
        item = body['data']['items'][0]
        for field in ('source', 'bucket', 'bucket_color', 'verdict', 'forced', 'ls_task_id'):
            assert field in item
        assert item['bucket'] == ReviewWorkitem.BUCKET_LOW
        assert item['bucket_color'] == '#FF4D4F'
        assert item['forced'] is True

    def test_forced_low_bucket_requires_action_or_annotation(self, auth_client):
        from aoi.review.models import ReviewWorkitem

        workitem = ReviewWorkitem.objects.create(
            fact_id=None,
            source=ReviewWorkitem.SOURCE_PRELABEL,
            bucket=ReviewWorkitem.BUCKET_LOW,
            verdict='manual',
            forced=True,
            route='manual',
        )
        missing = auth_client.post(
            f'/api/review/workitems/{workitem.id}/finalize', {'final_reason': 'annotation_issue'}, format='json'
        )
        assert missing.status_code == 422
        body = assert_envelope(missing, code=42200)
        assert 'action' in body['data']['detail']['fields']

        ok = auth_client.post(
            f'/api/review/workitems/{workitem.id}/finalize',
            {'final_reason': 'annotation_issue', 'action': 'relabeled', 'annotation': {'result': []}},
            format='json',
        )
        assert ok.status_code == 200
        assert_envelope(ok)
        workitem.refresh_from_db()
        assert workitem.status == 'finalized'

    def test_dataset_version_phase_default(self, auth_client):
        response = auth_client.post('/api/datasets/1/versions', {'version': '1.0.0'}, format='json')
        assert response.status_code == 200
        data = assert_envelope(response)['data']
        assert data['phase'] == 'draft'

    def test_prelabel_scope_fixed_to_unlabeled_only(self, auth_client):
        bad = auth_client.post(
            '/api/prelabel/tasks', {'dataset_id': 1, 'model_ref': '3-yolo@ds1', 'scope': 'all'}, format='json'
        )
        assert bad.status_code == 422
        assert_envelope(bad, code=42200)

        ok = auth_client.post('/api/prelabel/tasks', {'dataset_id': 1, 'model_ref': '3-yolo@ds1'}, format='json')
        assert ok.status_code == 200
        data = assert_envelope(ok)['data']
        assert data['scope'] == 'unlabeled_only'


@pytest.mark.django_db
class TestIngestFindings:
    @pytest.fixture(autouse=True)
    def _ingest_token(self, settings):
        settings.INTERNAL_TOKEN = 'secret-internal-token'

    def _meta(self, **overrides):
        meta = {
            'kind': 'suspicious',
            'instance_code': 'B01',
            'station_code': 'ST01',
            'station_name': '1号线-左门板',
            'seq': 1042,
            'captured_at': '2026-09-08T08:31:00Z',
            'received_at': '2026-09-08T08:31:02Z',
            'template_version': 3,
            'model_refs': ['3-yolo@ds1'],
            'verdict': 'recheck',
            'verdict_reasons': ['mid_score'],
            'boxes': [
                {
                    'object_code': 'object_fault_type_01',
                    'score': 0.72,
                    'model_ref': '3-yolo@ds1',
                    'xyxy': [100, 200, 180, 260],
                }
            ],
            'tiling_meta': {'tile_size': 1280, 'overlap': 0.2, 'tiles': 12, 'ms': 1400},
            'latency_ms': 1400,
            'image': {'md5': 'ab12cd', 'ext': 'jpg', 'width': 32, 'height': 24, 'size_bytes': 512},
            'error_code': None,
        }
        meta.update(overrides)
        return meta

    def _post(self, client, meta, *, file=None, token='secret-internal-token'):
        data = {'meta': json.dumps(meta)}
        if file is not None:
            data['file'] = file
        return client.post(
            '/api/ingest/findings',
            data,
            format='multipart',
            HTTP_X_INTERNAL_TOKEN=token,
        )

    def test_auth_40100(self, api_client):
        response = api_client.post('/api/ingest/findings', {'meta': json.dumps(self._meta())}, format='multipart')
        assert response.status_code == 401
        assert_envelope(response, code=40100)
        response = api_client.post(
            '/api/ingest/findings', {'meta': json.dumps(self._meta())}, format='multipart', HTTP_X_INTERNAL_TOKEN='bad'
        )
        assert response.status_code == 401
        assert_envelope(response, code=40100)

    def test_suspicious_idempotency_and_conflict(self, api_client, jpeg_bytes):
        client = APIClient()
        file = SimpleUploadedFile('ST01_1042.jpg', jpeg_bytes, content_type='image/jpeg')
        response = self._post(client, self._meta(), file=file)
        assert response.status_code == 200, response.content[:300]
        body = assert_envelope(response)
        first = body['data']
        assert first['duplicated'] is False
        assert first['fact_id'] and first['workitem_id'] and first['image_id']
        assert first['bad_image_id'] is None

        from aoi.review.models import ReviewWorkitem

        workitem = ReviewWorkitem.objects.get(pk=first['workitem_id'])
        assert workitem.source == ReviewWorkitem.SOURCE_INGEST
        assert workitem.bucket == ReviewWorkitem.BUCKET_MEDIUM  # verdict=recheck
        assert workitem.forced is False

        duplicate = self._post(
            client, self._meta(), file=SimpleUploadedFile('again.jpg', jpeg_bytes, content_type='image/jpeg')
        )
        assert duplicate.status_code == 200
        duplicate_body = assert_envelope(duplicate)['data']
        assert duplicate_body['duplicated'] is True
        assert duplicate_body['fact_id'] == first['fact_id']
        assert duplicate_body['workitem_id'] == first['workitem_id']

        conflict = self._post(
            client,
            self._meta(verdict='manual'),
            file=SimpleUploadedFile('again.jpg', jpeg_bytes, content_type='image/jpeg'),
        )
        assert conflict.status_code == 409
        assert_envelope(conflict, code=40900)

    def test_bad_branch_without_image(self, api_client):
        client = APIClient()
        meta = self._meta(kind='bad', error_code='capture_failed', verdict=None, boxes=[])
        response = self._post(client, meta)
        assert response.status_code == 200, response.content[:300]
        first = assert_envelope(response)['data']
        assert first['bad_image_id'] and first['duplicated'] is False
        assert first['fact_id'] is None and first['image_id'] is None

        duplicate = self._post(client, meta)
        assert duplicate.status_code == 200
        duplicate_data = assert_envelope(duplicate)['data']
        assert duplicate_data['duplicated'] is True
        assert duplicate_data['bad_image_id'] == first['bad_image_id']

        conflict = self._post(client, self._meta(kind='bad', error_code='timeout'))
        assert conflict.status_code == 409
        assert_envelope(conflict, code=40900)

    def test_suspicious_decode_failure_40010(self, api_client):
        client = APIClient()
        bad_file = SimpleUploadedFile('bad.jpg', b'not-an-image', content_type='image/jpeg')
        response = self._post(client, self._meta(seq=9999), file=bad_file)
        assert response.status_code == 400
        assert_envelope(response, code=40010)

    def test_kind_validation_42200(self, api_client):
        client = APIClient()
        response = self._post(client, self._meta(kind='other', seq=7777))
        assert response.status_code == 422
        assert_envelope(response, code=42200)


@pytest.mark.django_db
class TestIngestFindingsFixtureContract:
    """C 侧 ``fixtures/findings_ingest_sample.json`` 锁死 B→A 回传契约（A 侧应答形状与幂等）。

    该 fixture 是双端共同数据源（tests/contracts/README.md）：B 侧 outbox 按它发，A 侧按它答，
    任何一侧漂移都会在这里红。
    """

    @pytest.fixture(autouse=True)
    def _ingest_token(self, settings):
        settings.INTERNAL_TOKEN = 'fixture-internal-token'

    def _samples(self) -> list[dict]:
        return load_json('findings_ingest_sample.json')

    def _post(self, meta: dict, *, file=None):
        data = {'meta': json.dumps(meta)}
        if file is not None:
            data['file'] = file
        return APIClient().post(
            '/api/ingest/findings',
            data,
            format='multipart',
            HTTP_X_INTERNAL_TOKEN='fixture-internal-token',
        )

    def test_suspicious_sample_roundtrip_and_idempotency(self, jpeg_bytes):
        suspicious = next(item for item in self._samples() if item['kind'] == 'suspicious')
        response = self._post(suspicious, file=SimpleUploadedFile('sample.jpg', jpeg_bytes, content_type='image/jpeg'))
        assert response.status_code == 200, response.content[:300]
        data = assert_envelope(response)['data']
        assert set(data) == {'fact_id', 'workitem_id', 'image_id', 'bad_image_id', 'duplicated'}
        assert data['duplicated'] is False
        assert data['fact_id'] and data['workitem_id'] and data['image_id']
        assert data['bad_image_id'] is None

        from aoi.review.models import ReviewWorkitem

        workitem = ReviewWorkitem.objects.get(pk=data['workitem_id'])
        assert workitem.source == ReviewWorkitem.SOURCE_INGEST
        assert workitem.bucket == ReviewWorkitem.BUCKET_MEDIUM  # fixture verdict=recheck
        assert workitem.forced is False

        duplicate = self._post(
            suspicious, file=SimpleUploadedFile('sample-again.jpg', jpeg_bytes, content_type='image/jpeg')
        )
        duplicate_data = assert_envelope(duplicate)['data']
        assert duplicate_data['duplicated'] is True
        assert duplicate_data['fact_id'] == data['fact_id']
        assert duplicate_data['workitem_id'] == data['workitem_id']

    def test_bad_sample_without_image(self):
        bad = next(item for item in self._samples() if item['kind'] == 'bad')
        response = self._post(bad)
        assert response.status_code == 200, response.content[:300]
        data = assert_envelope(response)['data']
        assert data['duplicated'] is False
        assert data['bad_image_id']
        assert data['fact_id'] is None and data['workitem_id'] is None and data['image_id'] is None

        from aoi.review.models import BadImage

        row = BadImage.objects.get(pk=data['bad_image_id'])
        assert row.station_code == bad['station_code']
        assert row.seq == bad['seq']
        assert row.error_code == bad['error_code']

        duplicate = assert_envelope(self._post(bad))['data']
        assert duplicate['duplicated'] is True and duplicate['bad_image_id'] == data['bad_image_id']


# ============================================================ P0/P1 修复回归测试
@pytest.mark.django_db
class TestInternalTokenFailClosed:
    """P0：错图回传凭据未配置时必须 fail closed，不能回落到公开默认值。"""

    def test_dev_default_only_when_debug(self, settings):
        from aoi.common.settings import get_internal_token

        settings.DEBUG = True
        settings.INTERNAL_TOKEN = ''
        assert get_internal_token() == 'dev-internal-token'

    def test_missing_token_fails_closed_outside_debug(self, settings, api_client):
        from aoi.common.settings import get_internal_token
        from django.core.exceptions import ImproperlyConfigured

        settings.DEBUG = False
        settings.INTERNAL_TOKEN = ''
        with pytest.raises(ImproperlyConfigured):
            get_internal_token()

        meta = {'kind': 'suspicious', 'station_code': 'ST01', 'seq': 1, 'verdict': 'recheck'}
        response = api_client.post(
            '/api/ingest/findings',
            {'meta': json.dumps(meta)},
            format='multipart',
            HTTP_X_INTERNAL_TOKEN='dev-internal-token',
        )
        assert response.status_code == 401
        assert_envelope(response, code=40100)

    def test_non_ascii_token_is_401_not_500(self, settings, api_client):
        settings.INTERNAL_TOKEN = 'secret-internal-token'
        meta = {'kind': 'suspicious', 'station_code': 'ST01', 'seq': 2, 'verdict': 'recheck'}
        response = api_client.post(
            '/api/ingest/findings',
            {'meta': json.dumps(meta)},
            format='multipart',
            HTTP_X_INTERNAL_TOKEN='tökén',
        )
        assert response.status_code == 401
        assert_envelope(response, code=40100)


@pytest.mark.django_db
class TestIngestHardening:
    """P1：ingest 元数据校验（42200）与半写自愈。"""

    @pytest.fixture(autouse=True)
    def _ingest_token(self, settings):
        settings.INTERNAL_TOKEN = 'secret-internal-token'

    def _meta(self, **overrides):
        meta = {
            'kind': 'suspicious',
            'station_code': 'ST01',
            'seq': 2001,
            'verdict': 'recheck',
            'captured_at': '2026-09-08T08:31:00Z',
            'latency_ms': 1400,
        }
        meta.update(overrides)
        return meta

    def _post(self, client, meta, *, file=None):
        data = {'meta': json.dumps(meta)}
        if file is not None:
            data['file'] = file
        return client.post(
            '/api/ingest/findings', data, format='multipart', HTTP_X_INTERNAL_TOKEN='secret-internal-token'
        )

    @pytest.mark.parametrize(
        ('override', 'field'),
        [
            ({'latency_ms': 'fast'}, 'latency_ms'),
            ({'channel_id': 'left'}, 'channel_id'),
            ({'station_name': 'x' * 65}, 'station_name'),
            ({'instance_code': 'y' * 33}, 'instance_code'),
            ({'captured_at': 'not-a-date'}, 'captured_at'),
            ({'verdict': 'auto_pass'}, 'verdict'),
            ({'boxes': 'nope'}, 'boxes'),
            ({'image': 'nope'}, 'image'),
            ({'image': {'width': 'wide'}}, 'image.width'),
        ],
    )
    def test_malformed_meta_42200_with_fields(self, api_client, override, field):
        response = self._post(APIClient(), self._meta(**override))
        assert response.status_code == 422, (override, response.content[:200])
        body = assert_envelope(response, code=42200)
        assert field in body['data']['detail']['fields']

    def test_bad_error_code_enum_42200(self, api_client):
        response = self._post(APIClient(), self._meta(kind='bad', verdict=None, error_code='weird'))
        assert response.status_code == 422
        body = assert_envelope(response, code=42200)
        assert 'error_code' in body['data']['detail']['fields']

    def test_oversize_image_40010(self, api_client, jpeg_bytes, monkeypatch):
        from aoi.review import ingest

        monkeypatch.setattr(ingest, 'MAX_INGEST_BYTES', 10)
        response = self._post(
            APIClient(),
            self._meta(seq=2002),
            file=SimpleUploadedFile('big.jpg', jpeg_bytes, content_type='image/jpeg'),
        )
        assert response.status_code == 400
        assert_envelope(response, code=40010)

    def test_duplicate_backfills_missing_workitem(self, api_client, jpeg_bytes):
        """P0：fact 存在但 workitem 缺失（半写/崩溃）时，重复请求必须补建而不是返回 null。"""
        from aoi.review.models import ReviewWorkitem

        client = APIClient()
        file = SimpleUploadedFile('a.jpg', jpeg_bytes, content_type='image/jpeg')
        first = assert_envelope(self._post(client, self._meta(seq=2003), file=file))['data']
        assert first['workitem_id']

        ReviewWorkitem.objects.filter(fact_id=first['fact_id']).delete()

        again = self._post(
            client, self._meta(seq=2003), file=SimpleUploadedFile('a.jpg', jpeg_bytes, content_type='image/jpeg')
        )
        assert again.status_code == 200
        body = assert_envelope(again)['data']
        assert body['duplicated'] is True
        assert body['fact_id'] == first['fact_id']
        assert body['workitem_id'], 'half-written fact must get its workitem backfilled'


@pytest.mark.django_db
class TestTrainingPublishGuards:
    """P1：publish/approve 的 40401、门禁与 (model_ref, tag) 唯一性。"""

    def _model(self, **overrides):
        from aoi.training.models import Model

        defaults = {
            'version': '7-yolo@ds9',
            'framework': 'yolo',
            'dataset_version': '9',
            'precision': 'fp32',
            'class_names': ['object_fault_type_01'],
            'cover_classes': ['object_fault_type_01'],
            'gate_status': Model.GATE_PASSED,
            'lifecycle': Model.LIFECYCLE_APPROVED,
        }
        defaults.update(overrides)
        return Model.objects.create(**defaults)

    def test_publish_unknown_model_40401(self, auth_client):
        response = auth_client.post('/api/train/models/999/publish', {}, format='json')
        assert response.status_code == 404
        assert_envelope(response, code=40401)

    def test_publish_requires_approved(self, auth_client):
        from aoi.training.models import Model

        model = self._model(lifecycle=Model.LIFECYCLE_CANDIDATE)
        response = auth_client.post(f'/api/train/models/{model.id}/publish', {}, format='json')
        assert response.status_code == 409
        body = assert_envelope(response, code=40900)
        assert 'lifecycle' in body['data']['detail']['fields']

    def test_publish_then_conflict_on_same_tag(self, auth_client):

        model = self._model()
        first = auth_client.post(f'/api/train/models/{model.id}/publish', {}, format='json')
        assert first.status_code == 200
        payload = assert_envelope(first)['data']
        assert payload['stub'] is True  # fake 模式：仓库里没有镜像（占位权重）
        assert payload['tag'] == '7-yolo-ds9'
        # D3 发布服务 stub：同步跑完假 build + 假 push，状态推进到 published 并落 digest
        assert payload['status'] == 'published'
        assert payload['mode'] == 'fake'
        assert re.fullmatch(r'sha256:[0-9a-f]{64}', payload['digest'])

        from aoi.training.models import Model, ModelPublish

        row = ModelPublish.objects.get(model_ref='7-yolo@ds9', tag='7-yolo-ds9')
        assert row.status == ModelPublish.STATUS_PUBLISHED
        assert row.digest == payload['digest']
        assert row.published_at is not None and row.error_message is None
        model.refresh_from_db()
        assert model.lifecycle == Model.LIFECYCLE_PUBLISHED
        assert (model.config_snapshot or {}).get('model_yaml', {}).get('model_ref') == '7-yolo@ds9'

        second = auth_client.post(f'/api/train/models/{model.id}/publish', {}, format='json')
        assert second.status_code == 409
        assert_envelope(second, code=40900)

        # GET 未发布过的 model 也返回 40401（此前返回伪造的 queued）
        other = self._model(version='8-yolo@ds9')
        missing = auth_client.get(f'/api/train/models/{other.id}/publish')
        assert missing.status_code == 404
        assert_envelope(missing, code=40401)

    def test_fp16_second_tag_allowed_by_unique_constraint(self, auth_client):
        """P1：唯一性按 (model_ref, tag)，同 model_ref 的 `-fp16` tag 必须能共存。

        注：``aoi_training.model.version`` 本身仍唯一（一个 model_ref 一行），
        fp32/fp16 两个 tag 由 D7 发布器从同一次导出产出，因此这里直接验证约束语义。
        """
        from aoi.training.models import ModelPublish
        from django.db import IntegrityError, transaction

        model = self._model(version='9-yolo@ds9', precision='fp32')
        assert auth_client.post(f'/api/train/models/{model.id}/publish', {}, format='json').status_code == 200
        assert ModelPublish.objects.filter(model_ref='9-yolo@ds9', tag='9-yolo-ds9').count() == 1

        # 同 model_ref 的第二个 tag：允许
        ModelPublish.objects.create(
            model_ref='9-yolo@ds9',
            registry='docker.io',
            image='aoi/aoi-model',
            tag='9-yolo-ds9-fp16',
            status=ModelPublish.STATUS_QUEUED,
        )
        assert ModelPublish.objects.filter(model_ref='9-yolo@ds9').count() == 2

        # 同 (model_ref, tag) 再插一条：唯一约束拒绝
        with pytest.raises(IntegrityError), transaction.atomic():
            ModelPublish.objects.create(
                model_ref='9-yolo@ds9',
                registry='docker.io',
                image='aoi/aoi-model',
                tag='9-yolo-ds9-fp16',
                status=ModelPublish.STATUS_QUEUED,
            )

    def test_invalid_model_ref_version_42200(self, auth_client):
        model = self._model(version='not-a-model-ref')
        response = auth_client.post(f'/api/train/models/{model.id}/publish', {}, format='json')
        assert response.status_code == 422
        body = assert_envelope(response, code=42200)
        assert 'version' in body['data']['detail']['fields']

    def test_approve_invalid_decision_42200(self, auth_client):
        model = self._model(version='10-yolo@ds9')
        response = auth_client.post(f'/api/train/models/{model.id}/approve', {'decision': 'maybe'}, format='json')
        assert response.status_code == 422
        body = assert_envelope(response, code=42200)
        assert 'decision' in body['data']['detail']['fields']

    def test_approve_requires_gate_passed(self, auth_client):
        from aoi.training.models import Model

        model = self._model(version='11-yolo@ds9', gate_status=Model.GATE_FAILED, lifecycle=Model.LIFECYCLE_CANDIDATE)
        response = auth_client.post(f'/api/train/models/{model.id}/approve', {'decision': 'approve'}, format='json')
        assert response.status_code == 409
        body = assert_envelope(response, code=40900)
        assert body['data']['detail']['fields']['gate_status'] == 'failed'

        model.refresh_from_db()
        assert model.lifecycle == Model.LIFECYCLE_CANDIDATE

    def test_approve_unknown_model_40401(self, auth_client):
        response = auth_client.post('/api/train/models/999/approve', {'decision': 'approve'}, format='json')
        assert response.status_code == 404
        assert_envelope(response, code=40401)


# ============================================================ D3 发布服务 stub
@pytest.mark.django_db
class TestPublishFakePipeline:
    """D3 发布服务 stub：假 build 产物自洽/确定性、状态机与落盘、失败后人工重推。"""

    def _model(self, **overrides):
        from aoi.training.models import Model

        defaults = {
            'version': '21-yolo@ds9',
            'framework': 'yolo',
            'dataset_version': '9',
            'precision': 'fp32',
            'class_names': ['object_fault_type_01'],
            'cover_classes': ['object_fault_type_01'],
            'gate_status': Model.GATE_PASSED,
            'lifecycle': Model.LIFECYCLE_APPROVED,
        }
        defaults.update(overrides)
        return Model.objects.create(**defaults)

    def test_artifacts_are_docker_schema2_and_self_consistent(self):
        """产物结构对齐 ``FROM scratch + COPY model/ /model/``（B 侧按此解包）。"""
        from aoi.training import publish as publish_service
        from aoi.training.model_yaml import validate_model_yaml

        model = self._model()
        onnx_bytes, doc, yaml_text = publish_service.build_model_files(model)
        artifacts = publish_service.build_image_artifacts(onnx_bytes, yaml_text)

        uncompressed = gzip.decompress(artifacts.layer_bytes)
        with tarfile.open(fileobj=io.BytesIO(uncompressed), mode='r:') as tar:
            assert sorted(tar.getnames()) == ['model/model.onnx', 'model/model.onnx.sha256', 'model/model.yaml']
            assert tar.getmember('model/model.onnx').mtime == 0
            assert tar.extractfile('model/model.onnx').read() == onnx_bytes
            assert tar.extractfile('model/model.onnx.sha256').read() == f'{artifacts.onnx_sha256}\n'.encode()
            assert tar.extractfile('model/model.yaml').read() == yaml_text.encode()

        # digest 链自洽：diff_id = 未压缩 tar 的 sha256；manifest 引用 config/layer 真实 digest
        assert artifacts.diff_id == f'sha256:{hashlib.sha256(uncompressed).hexdigest()}'
        assert artifacts.layer_digest == f'sha256:{hashlib.sha256(artifacts.layer_bytes).hexdigest()}'
        assert artifacts.config_digest == f'sha256:{hashlib.sha256(artifacts.config_bytes).hexdigest()}'
        assert artifacts.digest == f'sha256:{hashlib.sha256(artifacts.manifest_bytes).hexdigest()}'

        config = json.loads(artifacts.config_bytes)
        manifest = json.loads(artifacts.manifest_bytes)
        assert config['rootfs']['diff_ids'] == [artifacts.diff_id]
        assert manifest['schemaVersion'] == 2
        assert manifest['config']['digest'] == artifacts.config_digest
        assert manifest['config']['size'] == len(artifacts.config_bytes)
        assert manifest['layers'][0]['digest'] == artifacts.layer_digest
        assert manifest['layers'][0]['size'] == len(artifacts.layer_bytes)

        # model.yaml 与权重一致且通过 A 侧校验
        assert validate_model_yaml(doc) == []
        assert doc['onnx']['sha256'] == artifacts.onnx_sha256
        assert doc['onnx']['size_bytes'] == len(onnx_bytes)
        assert doc['model_ref'] == '21-yolo@ds9'

    def test_same_inputs_build_identical_bytes(self):
        """确定性：同输入两次构建字节一致（tar mtime=0 / gzip mtime=0 / config 时间戳固定）。"""
        from aoi.training import publish as publish_service

        model = self._model(version='22-yolo@ds9')
        onnx_bytes, _doc, yaml_text = publish_service.build_model_files(model)
        first = publish_service.build_image_artifacts(onnx_bytes, yaml_text)
        second = publish_service.build_image_artifacts(onnx_bytes, yaml_text)
        assert first.layer_bytes == second.layer_bytes
        assert first.config_bytes == second.config_bytes
        assert first.manifest_bytes == second.manifest_bytes
        assert first.digest == second.digest
        # 占位权重按 model_ref 确定（同模型恒定、异模型不同）
        assert publish_service.build_fake_onnx(model) == onnx_bytes
        assert publish_service.build_fake_onnx(self._model(version='25-yolo@ds9')) != onnx_bytes

    def test_artifacts_dir_resolution_and_disable_switch(self, settings):
        """落盘目录按**仓库根**解析；显式空串=关闭（conftest 默认关闭，测试不写仓库工作区）。"""
        from aoi.training.publish import REPO_ROOT, resolve_publish_artifacts_dir

        settings.AOI_PUBLISH_ARTIFACTS_DIR = ''
        assert resolve_publish_artifacts_dir() is None

        settings.AOI_PUBLISH_ARTIFACTS_DIR = 'tmp/publish'
        assert resolve_publish_artifacts_dir() == REPO_ROOT / 'tmp' / 'publish'

        absolute = REPO_ROOT / 'tmp' / 'abs-publish'
        settings.AOI_PUBLISH_ARTIFACTS_DIR = str(absolute)
        assert resolve_publish_artifacts_dir() == absolute

    def test_publish_api_materializes_artifacts_and_audits(self, auth_client, settings, tmp_path):
        from aoi.audit.models import AuditLog
        from aoi.training.models import ModelPublish

        settings.AOI_PUBLISH_ARTIFACTS_DIR = str(tmp_path / 'publish')
        model = self._model(version='23-yolo@ds9')
        response = auth_client.post(f'/api/train/models/{model.id}/publish', {}, format='json')
        data = assert_envelope(response)['data']
        assert data['status'] == 'published' and data['stub'] is True and data['mode'] == 'fake'
        assert data['image'] and '/' in data['image']

        row = ModelPublish.objects.get(model_ref='23-yolo@ds9')
        assert row.status == ModelPublish.STATUS_PUBLISHED

        tag_dir = tmp_path / 'publish' / data['tag']
        for rel in (
            'model/model.onnx',
            'model/model.onnx.sha256',
            'model/model.yaml',
            'artifacts/layer.tar.gz',
            'artifacts/config.json',
            'artifacts/manifest.json',
            'artifacts/digest.txt',
            'Dockerfile',
            'push.sh',
        ):
            assert (tag_dir / rel).is_file(), rel
        assert (tag_dir / 'push.sh').stat().st_mode & 0o111  # 可执行（手工直推通道）
        summary = json.loads((tag_dir / 'artifacts' / 'digest.txt').read_text(encoding='utf-8'))
        assert summary['digest'] == data['digest']
        assert summary['mode'] == 'fake'
        assert (tag_dir / 'model' / 'model.onnx.sha256').read_text(encoding='utf-8').strip() == summary['model.onnx'][
            'sha256'
        ]

        assert AuditLog.objects.filter(action='model.published', object_id=str(model.id)).exists()

        # GET 反映发布结果（同一记录）
        got = assert_envelope(auth_client.get(f'/api/train/models/{model.id}/publish'))['data']
        assert got['status'] == 'published' and got['digest'] == data['digest']
        assert got['published_at']

    def test_build_failure_marks_failed_then_manual_retry(self, auth_client):
        from aoi.training.models import Model, ModelPublish

        model = self._model(version='24-yolo@ds9', class_names=[], cover_classes=[])
        response = auth_client.post(f'/api/train/models/{model.id}/publish', {}, format='json')
        assert response.status_code == 422
        assert_envelope(response, code=42200)

        row = ModelPublish.objects.get(model_ref='24-yolo@ds9')
        assert row.status == ModelPublish.STATUS_FAILED
        assert row.error_message and 'build failed' in row.error_message
        model.refresh_from_db()
        assert model.lifecycle == Model.LIFECYCLE_APPROVED  # 失败不推进生命周期

        # 补齐字典/类别后人工重推：复用同一条记录，attempts 递增
        model.class_names = ['object_fault_type_01']
        model.cover_classes = ['object_fault_type_01']
        model.save(update_fields=['class_names', 'cover_classes'])
        retry = auth_client.post(f'/api/train/models/{model.id}/publish', {}, format='json')
        assert assert_envelope(retry)['data']['status'] == 'published'

        row.refresh_from_db()
        assert row.attempts == 1
        assert row.status == ModelPublish.STATUS_PUBLISHED and row.error_message is None
        model.refresh_from_db()
        assert model.lifecycle == Model.LIFECYCLE_PUBLISHED


class TestRegistryPushClient:
    """registry 模式推送客户端：HTTP 全 mock，不联网（Docker Hub 直连不通的机房走代理）。"""

    def _artifacts(self):
        from aoi.training import publish as publish_service

        return publish_service.build_image_artifacts(b'fake-onnx-bytes', 'schema_version: 1\n')

    def _client(self, **overrides):
        from aoi.training.publish import RegistryPushClient

        params = {
            'registry': 'docker.io',
            'repository': 'rekal1018/aoi-model',
            'username': 'rekal1018',
            'password': 'pat',
            'proxy': REGISTRY_PROXY_FOR_TESTS,
        }
        params.update(overrides)
        return RegistryPushClient(**params)

    def _mock_hub(
        self, mock, artifacts, *, manifest_digest=None, blob_receipt=True, manifest_receipt=True, readback=None
    ):
        """搭一个最小 Registry v2 假仓库。

        ``blob_receipt`` / ``manifest_receipt`` 控制仓库**是否回 ``Docker-Content-Digest`` 回执**：
        真仓库（Docker Hub）会回；缺失回执是要被拒绝的异常路径（``DIGEST_POLICY_STRICT``）。
        """

        def _blob_put(request, context):
            # 仓库按上传字节回 digest（与真实 registry 语义一致）
            context.status_code = 201
            if blob_receipt:
                context.headers['Docker-Content-Digest'] = request.url.split('digest=')[-1]
            return ''

        mock.get(
            'https://registry-1.docker.io/v2/',
            status_code=401,
            headers={'WWW-Authenticate': 'Bearer realm="https://auth.docker.io/token",service="registry.docker.io"'},
        )
        mock.get('https://auth.docker.io/token', json={'token': 'test-token'})
        mock.post(
            'https://registry-1.docker.io/v2/rekal1018/aoi-model/blobs/uploads/',
            status_code=202,
            headers={'Location': '/v2/rekal1018/aoi-model/blobs/uploads/uuid-1'},
        )
        mock.put(
            re.compile(r'https://registry-1\.docker\.io/v2/rekal1018/aoi-model/blobs/uploads/uuid-1\?digest=.*'),
            json=_blob_put,
        )
        manifest_headers = {'Docker-Content-Digest': manifest_digest or artifacts.digest} if manifest_receipt else {}
        if readback is not None:
            mock.get(
                'https://registry-1.docker.io/v2/rekal1018/aoi-model/manifests/21-yolo-ds9',
                content=readback,
                headers={'Content-Type': 'application/vnd.docker.distribution.manifest.v2+json'},
            )
        return mock.put(
            'https://registry-1.docker.io/v2/rekal1018/aoi-model/manifests/21-yolo-ds9',
            status_code=201,
            headers=manifest_headers,
        )

    def test_push_uploads_blobs_and_verifies_registry_digest(self):
        from aoi.training.publish import RegistryPushError  # noqa: F401  (契约错误类型可导入)

        artifacts = self._artifacts()
        client = self._client()
        with requests_mock.Mocker() as mock:
            manifest_put = self._mock_hub(mock, artifacts)
            assert client.push(artifacts, tag='21-yolo-ds9') == artifacts.digest
            history = list(mock.request_history)

        # 代理只挂在发布客户端自己的会话上
        assert client.session.proxies.get('https') == REGISTRY_PROXY_FOR_TESTS
        # token 请求带上 push scope 与凭据
        token_calls = [req for req in history if req.hostname == 'auth.docker.io']
        assert len(token_calls) == 1
        assert parse_qs(urlparse(token_calls[0].url).query)['scope'] == ['repository:rekal1018/aoi-model:pull,push']
        assert token_calls[0].headers['Authorization'].startswith('Basic ')
        # layer + config 各推一次；manifest 带正确 media type 与字节
        blob_puts = [req for req in history if req.method == 'PUT' and '/blobs/uploads/' in req.url]
        assert {req.url.split('digest=')[-1] for req in blob_puts} == {artifacts.layer_digest, artifacts.config_digest}
        assert manifest_put.last_request.headers['Content-Type'] == (
            'application/vnd.docker.distribution.manifest.v2+json'
        )
        assert manifest_put.last_request.body == artifacts.manifest_bytes

    def test_digest_mismatch_is_rejected(self):
        from aoi.training.publish import RegistryPushError

        artifacts = self._artifacts()
        with requests_mock.Mocker() as mock:
            self._mock_hub(mock, artifacts, manifest_digest=f'sha256:{"0" * 64}')
            with pytest.raises(RegistryPushError, match='digest mismatch'):
                self._client().push(artifacts, tag='21-yolo-ds9')

    def test_blob_receipt_mismatch_is_rejected(self):
        """blob 回执与上传 digest 不一致 → 拒绝（防篡改）。"""
        from aoi.training.publish import RegistryPushError

        artifacts = self._artifacts()
        with requests_mock.Mocker() as mock:
            self._mock_hub(mock, artifacts)
            mock.put(
                re.compile(r'https://registry-1\.docker\.io/v2/rekal1018/aoi-model/blobs/uploads/uuid-1\?digest=.*'),
                status_code=201,
                headers={'Docker-Content-Digest': f'sha256:{"1" * 64}'},
            )
            with pytest.raises(RegistryPushError, match='blob digest mismatch'):
                self._client().push(artifacts, tag='21-yolo-ds9')

    def test_missing_blob_receipt_is_rejected(self):
        """仓库不对 blob 回 ``Docker-Content-Digest`` → strict 策略下拒绝，不拿本地值兜底。"""
        from aoi.training.publish import RegistryPushError

        artifacts = self._artifacts()
        with requests_mock.Mocker() as mock:
            self._mock_hub(mock, artifacts, blob_receipt=False)
            with pytest.raises(RegistryPushError, match='blob upload receipt missing'):
                self._client().push(artifacts, tag='21-yolo-ds9')

    def test_missing_manifest_receipt_is_rejected_by_default(self):
        """默认 strict：manifest PUT 不回回执 → 失败，绝不 ``registry_digest or local`` 悄悄兜底。"""
        from aoi.training.publish import RegistryPushError

        artifacts = self._artifacts()
        with requests_mock.Mocker() as mock:
            self._mock_hub(mock, artifacts, manifest_receipt=False)
            with pytest.raises(RegistryPushError, match='manifest push receipt missing'):
                self._client().push(artifacts, tag='21-yolo-ds9')

    def test_missing_manifest_receipt_readback_policy_verifies_bytes(self):
        """显式选 ``readback``：PUT 后 GET 回读，字节一致才认；返回的仍是本地 digest（已被仓库内容证明）。"""
        from aoi.training.publish import DIGEST_POLICY_READBACK

        artifacts = self._artifacts()
        with requests_mock.Mocker() as mock:
            self._mock_hub(mock, artifacts, manifest_receipt=False, readback=artifacts.manifest_bytes)
            client = self._client(missing_digest_policy=DIGEST_POLICY_READBACK)
            assert client.push(artifacts, tag='21-yolo-ds9') == artifacts.digest

    def test_missing_manifest_receipt_readback_mismatch_is_rejected(self):
        """``readback`` 策略下回读字节不一致 → 仍然拒绝（仓库被换内容 / 存错东西）。"""
        from aoi.training.publish import DIGEST_POLICY_READBACK, RegistryPushError

        artifacts = self._artifacts()
        with requests_mock.Mocker() as mock:
            self._mock_hub(mock, artifacts, manifest_receipt=False, readback=b'{"schemaVersion":2,"tampered":true}')
            client = self._client(missing_digest_policy=DIGEST_POLICY_READBACK)
            with pytest.raises(RegistryPushError, match='manifest readback mismatch'):
                client.push(artifacts, tag='21-yolo-ds9')

    def test_blob_put_without_location_receipt_only_when_digest_matches(self):
        """仓库认为 blob 已存在 → 201 且不给 Location：按层/配置顺序回对应回执 digest 才算成功。"""
        artifacts = self._artifacts()
        expected = [artifacts.layer_digest, artifacts.config_digest]
        seen: list[int] = []

        def _already_exists(request, context):
            context.status_code = 201
            context.headers['Docker-Content-Digest'] = expected[len(seen)]
            seen.append(1)
            return ''

        with requests_mock.Mocker() as mock:
            self._mock_hub(mock, artifacts)
            mock.post(
                'https://registry-1.docker.io/v2/rekal1018/aoi-model/blobs/uploads/',
                json=_already_exists,
            )
            assert self._client().push(artifacts, tag='21-yolo-ds9') == artifacts.digest
        assert len(seen) == 2  # layer + config 两次 POST 都走了「已存在」分支

    def test_unknown_digest_policy_rejected(self):
        from aoi.training.publish import RegistryPushError

        with pytest.raises(RegistryPushError, match='unknown missing_digest_policy'):
            self._client(missing_digest_policy='whatever')

    def test_network_error_is_wrapped(self):
        from aoi.training.publish import RegistryPushError

        artifacts = self._artifacts()
        with requests_mock.Mocker() as mock:
            mock.get('https://registry-1.docker.io/v2/', exc=requests.ConnectionError('proxy unreachable'))
            with pytest.raises(RegistryPushError):
                self._client().push(artifacts, tag='21-yolo-ds9')

    def test_missing_credentials_rejected(self):
        from aoi.training.publish import RegistryPushError

        with pytest.raises(RegistryPushError, match='MODEL_REGISTRY_USER'):
            self._client(username='').push(self._artifacts(), tag='21-yolo-ds9')


@pytest.mark.django_db
class TestPublishRegistryMode:
    """registry 模式端到端（HTTP 全 mock）：视图把仓库返回的 digest 落库、应答 stub=false。"""

    def _settings(self, settings):
        settings.AOI_PUBLISH_MODE = 'registry'
        settings.MODEL_REGISTRY = 'docker.io'
        settings.MODEL_IMAGE_REPO = 'rekal1018/aoi-model'
        settings.MODEL_REGISTRY_USER = 'rekal1018'
        settings.MODEL_REGISTRY_PASSWORD = 'pat'
        settings.AOI_REGISTRY_PROXY = REGISTRY_PROXY_FOR_TESTS
        settings.AOI_PUBLISH_ARTIFACTS_DIR = ''
        return settings

    def _model(self, version='31-yolo@ds9'):
        from aoi.training.models import Model

        return Model.objects.create(
            version=version,
            framework='yolo',
            dataset_version='9',
            precision='fp32',
            class_names=['object_fault_type_01'],
            cover_classes=['object_fault_type_01'],
            gate_status=Model.GATE_PASSED,
            lifecycle=Model.LIFECYCLE_APPROVED,
        )

    def _mock_registry(self, mock, tag='31-yolo-ds9', *, manifest_receipt=True):
        """假仓库：blob/manifest 按上传字节回 digest 回执；``manifest_receipt=False`` 模拟仓库不回执。"""

        def _manifest_response(request, context):
            context.status_code = 201
            if manifest_receipt:
                context.headers['Docker-Content-Digest'] = f'sha256:{hashlib.sha256(request.body).hexdigest()}'
            return ''

        def _blob_put(request, context):
            context.status_code = 201
            context.headers['Docker-Content-Digest'] = request.url.split('digest=')[-1]
            return ''

        mock.get(
            'https://registry-1.docker.io/v2/',
            status_code=401,
            headers={'WWW-Authenticate': 'Bearer realm="https://auth.docker.io/token",service="registry.docker.io"'},
        )
        mock.get('https://auth.docker.io/token', json={'token': 'test-token'})
        mock.post(
            'https://registry-1.docker.io/v2/rekal1018/aoi-model/blobs/uploads/',
            status_code=202,
            headers={'Location': '/v2/rekal1018/aoi-model/blobs/uploads/uuid-9'},
        )
        mock.put(
            re.compile(r'https://registry-1\.docker\.io/v2/rekal1018/aoi-model/blobs/uploads/uuid-9\?digest=.*'),
            json=_blob_put,
        )
        return mock.put(
            f'https://registry-1.docker.io/v2/rekal1018/aoi-model/manifests/{tag}',
            text=_manifest_response,
        )

    def test_publish_api_uses_registry_digest(self, auth_client, settings):
        self._settings(settings)
        model = self._model()

        with requests_mock.Mocker() as mock:
            manifest_put = self._mock_registry(mock)
            response = auth_client.post(f'/api/train/models/{model.id}/publish', {}, format='json')

        data = assert_envelope(response)['data']
        assert data['status'] == 'published'
        assert data['mode'] == 'registry'
        assert data['stub'] is False  # 真推成功后 B 可拉取
        uploaded = manifest_put.last_request.body
        assert data['digest'] == f'sha256:{hashlib.sha256(uploaded).hexdigest()}'

        from aoi.training.models import ModelPublish

        row = ModelPublish.objects.get(model_ref='31-yolo@ds9', tag='31-yolo-ds9')
        assert row.status == ModelPublish.STATUS_PUBLISHED
        assert row.digest == data['digest']

    def test_same_model_rebuilt_later_yields_different_digest(self, auth_client, settings, monkeypatch):
        """**D7 待修事实锁定**：同一个 model_ref 在**不同时刻**重建 → digest 不同。

        根因：``model.yaml`` 里写了 ``created_at``（``model_yaml._utcnow()``，秒级）与发布器传入的
        ``published_at``，二者都参与 manifest 字节 → 影响跨平台契约 §2.2「同 tag 不同 digest → 禁止覆盖」的判定。
        修法见 ``docs/MVP开发计划.md`` §5 D7「digest 可复现」；修好后本用例应改成断言两次相等。

        这里显式把两次构建钉在**不同秒**（而非依赖真实时钟）：同一秒内重建产物本来就可复现，
        真正不可复现的是「换个时刻重建」。
        """
        from aoi.training.models import Model, ModelPublish

        self._settings(settings)
        model = self._model()

        digests = []
        for stamp in ('2026-09-11T02:25:00Z', '2026-09-11T02:29:00Z'):
            monkeypatch.setattr('aoi.training.model_yaml._utcnow', lambda stamp=stamp: stamp)
            monkeypatch.setattr('aoi.training.publish._utcnow_iso', lambda stamp=stamp: stamp)
            model.lifecycle = Model.LIFECYCLE_APPROVED
            model.save(update_fields=['lifecycle'])
            ModelPublish.objects.filter(model_ref=model.version).delete()
            with requests_mock.Mocker() as mock:
                self._mock_registry(mock)
                response = auth_client.post(f'/api/train/models/{model.id}/publish', {}, format='json')
            digests.append(assert_envelope(response)['data']['digest'])

        assert digests[0] != digests[1], '若相等说明 model.yaml 已不再带时间戳 —— 请更新本用例与 D7 计划项'

    def test_registry_without_receipt_fails_publish(self, auth_client, settings):
        """仓库不回 ``Docker-Content-Digest`` → 发布失败 50300、状态 failed，绝不落「本地自算 digest」。"""
        from aoi.training.models import ModelPublish

        self._settings(settings)
        model = self._model()

        with requests_mock.Mocker() as mock:
            self._mock_registry(mock, manifest_receipt=False)
            response = auth_client.post(f'/api/train/models/{model.id}/publish', {}, format='json')

        assert response.status_code == 503
        body = assert_envelope(response, code=50300)
        assert body['data']['detail']['fields']['tag'] == '31-yolo-ds9'

        row = ModelPublish.objects.get(model_ref='31-yolo@ds9', tag='31-yolo-ds9')
        assert row.status == ModelPublish.STATUS_FAILED
        assert row.digest in (None, '')  # 不落「本地自算值」当仓库确认值
        assert 'receipt missing' in (row.error_message or '')


@pytest.mark.django_db
class TestReviewStateMachine:
    """P1：claim/finalize 的状态机、低桶强制与终裁落库。"""

    def _workitem(self, **overrides):
        from aoi.review.models import ReviewWorkitem

        defaults = {
            'source': ReviewWorkitem.SOURCE_PRELABEL,
            'dataset_version_id': 1,
            'model_ref': '3-yolo@ds1',
            'verdict': 'recheck',
            'bucket': ReviewWorkitem.BUCKET_MEDIUM,
            'forced': False,
            'route': ReviewWorkitem.ROUTE_MANUAL,
            'status': ReviewWorkitem.STATUS_PENDING,
        }
        defaults.update(overrides)
        return ReviewWorkitem.objects.create(**defaults)

    def test_claim_twice_conflict(self, auth_client):
        workitem = self._workitem()
        first = auth_client.post(f'/api/review/workitems/{workitem.id}/claim', {}, format='json')
        assert first.status_code == 200
        assert assert_envelope(first)['data']['status'] == 'processing'

        second = auth_client.post(f'/api/review/workitems/{workitem.id}/claim', {}, format='json')
        assert second.status_code == 409
        assert_envelope(second, code=40900)

    def test_claim_unknown_40401(self, auth_client):
        response = auth_client.post('/api/review/workitems/424242/claim', {}, format='json')
        assert response.status_code == 404
        assert_envelope(response, code=40401)

    def test_finalize_twice_conflict(self, auth_client):
        workitem = self._workitem()
        body = {'final_reason': 'misdetection', 'verdict': 'false_alarm'}
        assert (
            auth_client.post(f'/api/review/workitems/{workitem.id}/finalize', body, format='json').status_code == 200
        )
        again = auth_client.post(f'/api/review/workitems/{workitem.id}/finalize', body, format='json')
        assert again.status_code == 409
        assert_envelope(again, code=40900)

        from aoi.review.models import FinalFact

        assert FinalFact.objects.filter(workitem_id=workitem.id).count() == 1

    def test_finalize_invalid_reason_42200(self, auth_client):
        workitem = self._workitem()
        response = auth_client.post(
            f'/api/review/workitems/{workitem.id}/finalize', {'final_reason': 'whatever'}, format='json'
        )
        assert response.status_code == 422
        body = assert_envelope(response, code=42200)
        assert 'final_reason' in body['data']['detail']['fields']

    def test_finalize_unknown_40401(self, auth_client):
        response = auth_client.post(
            '/api/review/workitems/424242/finalize',
            {'final_reason': 'misdetection'},
            format='json',
        )
        assert response.status_code == 404
        assert_envelope(response, code=40401)

    def test_low_bucket_without_action_rejected(self, auth_client):
        from aoi.review.models import ReviewWorkitem

        # forced=False 但 bucket=low：仍然必须重标（P1 修复：不能只看 forced）
        workitem = self._workitem(bucket=ReviewWorkitem.BUCKET_LOW, forced=False, verdict='manual')
        response = auth_client.post(
            f'/api/review/workitems/{workitem.id}/finalize',
            {'final_reason': 'new_defect', 'action': 'accepted_prediction'},
            format='json',
        )
        assert response.status_code == 422
        assert_envelope(response, code=42200)

    def test_finalize_persists_annotation_metadata(self, auth_client):
        from aoi.review.models import FinalFact, ReviewWorkitem

        workitem = self._workitem(bucket=ReviewWorkitem.BUCKET_LOW, forced=True, verdict='manual')
        response = auth_client.post(
            f'/api/review/workitems/{workitem.id}/finalize',
            {
                'final_reason': 'new_defect',
                'verdict': 'defect_confirmed',
                'action': 'relabeled',
                'annotation': {'id': 555, 'result': []},
                'class_id': 0,
                'boxes': [{'xyxy': [1, 2, 3, 4], 'object_code': 'object_fault_type_01'}],
                'note': '人工补框',
            },
            format='json',
        )
        assert response.status_code == 200, response.content[:300]
        fact = FinalFact.objects.get(workitem_id=workitem.id)
        assert fact.annotation_id == 555
        assert fact.action == 'relabeled'
        assert fact.class_id == 0
        assert fact.boxes and fact.note == '人工补框'
        workitem.refresh_from_db()
        assert workitem.status == ReviewWorkitem.STATUS_FINALIZED


@pytest.mark.django_db
class TestStateMachineInjection:
    """P1：客户端不能直接注入 phase/status/route_bucket。"""

    def test_dataset_version_phase_and_status_are_server_controlled(self, auth_client):
        response = auth_client.post(
            '/api/datasets/1/versions',
            {'version': '2.0.0', 'phase': 'published', 'status': 'published'},
            format='json',
        )
        assert response.status_code == 422
        body = assert_envelope(response, code=42200)
        assert {'phase', 'status'} <= set(body['data']['detail']['fields'])

    def test_prelabel_create_forces_queued_and_validates_model_ref(self, auth_client):
        bad_ref = auth_client.post('/api/prelabel/tasks', {'dataset_id': 1, 'model_ref': 'whatever'}, format='json')
        assert bad_ref.status_code == 422
        body = assert_envelope(bad_ref, code=42200)
        assert 'model_ref' in body['data']['detail']['fields']

        created = auth_client.post(
            '/api/prelabel/tasks',
            {'dataset_id': 1, 'model_ref': '3-yolo@ds1', 'status': 'succeeded'},
            format='json',
        )
        assert created.status_code == 422  # status 不能由客户端指定

        ok = auth_client.post('/api/prelabel/tasks', {'dataset_id': 1, 'model_ref': '3-yolo@ds1'}, format='json')
        assert ok.status_code == 200
        assert assert_envelope(ok)['data']['status'] == 'queued'

    def test_prelabel_route_config_validated(self, auth_client):
        response = auth_client.post(
            '/api/prelabel/tasks',
            {
                'dataset_id': 1,
                'model_ref': '3-yolo@ds1',
                'route_config': {'default': {'recheck_min': 0.9, 'auto_min': 0.5}},
            },
            format='json',
        )
        assert response.status_code == 422
        body = assert_envelope(response, code=42200)
        assert 'default' in body['data']['detail']['fields']

        unknown_key = auth_client.post(
            '/api/prelabel/tasks',
            {'dataset_id': 1, 'model_ref': '3-yolo@ds1', 'route_config': {'whatever': 1}},
            format='json',
        )
        assert unknown_key.status_code == 422
        assert_envelope(unknown_key, code=42200)

    def test_prelabel_route_bucket_read_only_and_transitions(self, auth_client):
        created = assert_envelope(
            auth_client.post('/api/prelabel/tasks', {'dataset_id': 1, 'model_ref': '3-yolo@ds1'}, format='json')
        )['data']
        task_id = created['id']

        read_only = auth_client.put(f'/api/prelabel/tasks/{task_id}', {'route_bucket': {'high': 3}}, format='json')
        assert read_only.status_code == 422
        body = assert_envelope(read_only, code=42200)
        assert 'route_bucket' in body['data']['detail']['fields']

        skipped = auth_client.put(f'/api/prelabel/tasks/{task_id}', {'status': 'succeeded'}, format='json')
        assert skipped.status_code == 422  # queued → succeeded 不是合法迁移

        running = auth_client.put(f'/api/prelabel/tasks/{task_id}', {'status': 'running'}, format='json')
        assert running.status_code == 200
        assert assert_envelope(running)['data']['status'] == 'running'

        succeeded = auth_client.put(f'/api/prelabel/tasks/{task_id}', {'status': 'succeeded'}, format='json')
        assert succeeded.status_code == 200

    def test_defect_requires_risk_level(self, auth_client):
        response = auth_client.post(
            '/api/datasets/defects', {'code': 'object_fault_type_05', 'name_cn': '污渍'}, format='json'
        )
        assert response.status_code == 422
        body = assert_envelope(response, code=42200)
        assert 'risk_level' in body['data']['detail']['fields']

    def test_defect_invalid_code_rejected(self, auth_client):
        response = auth_client.post(
            '/api/datasets/defects',
            {'code': 'object_fault_type_00', 'name_cn': '非法', 'risk_level': 1},
            format='json',
        )
        assert response.status_code == 422
        body = assert_envelope(response, code=42200)
        assert 'code' in body['data']['detail']['fields']


@pytest.mark.django_db
class TestLabelConfigIndexConsistency:
    """P1：字典快照 index == classes.txt 顺序 == model.yaml.classes[].index。"""

    def test_non_contiguous_codes_get_positional_indexes(self):
        from types import SimpleNamespace

        from aoi.datasets.label_config import render_label_config, snapshot_from_defects
        from aoi.training.model_yaml import build_model_yaml

        defects = [
            {'code': 'object_fault_type_01', 'name_cn': '划伤', 'risk_level': 3},
            {'code': 'object_fault_type_03', 'name_cn': '压痕', 'risk_level': 2},
        ]
        snapshot = snapshot_from_defects(defects)
        assert snapshot['labels']['object_fault_type_01']['index'] == 0
        assert snapshot['labels']['object_fault_type_03']['index'] == 1

        xml = render_label_config(defects)
        assert xml.index('object_fault_type_01') < xml.index('object_fault_type_03')

        model = SimpleNamespace(
            class_names=['object_fault_type_01', 'object_fault_type_03'],
            precision='fp32',
            version='1-yolo@ds1',
        )
        doc = build_model_yaml(model, defect_classes=defects)
        assert [(entry['index'], entry['code']) for entry in doc['classes']] == [
            (0, 'object_fault_type_01'),
            (1, 'object_fault_type_03'),
        ]

    def test_explicit_non_contiguous_index_rejected(self):
        from aoi.common.errors import AoiError
        from aoi.datasets.label_config import snapshot_from_defects

        with pytest.raises(AoiError) as excinfo:
            snapshot_from_defects(
                [
                    {'code': 'object_fault_type_01', 'index': 0},
                    {'code': 'object_fault_type_03', 'index': 2},
                ]
            )
        assert excinfo.value.code == 42200


@pytest.mark.django_db
class TestRolesHardening:
    """P1：角色 stub 的写校验与审计。"""

    def test_duplicate_role_code_conflict(self, auth_client):
        response = auth_client.post('/api/core/roles', {'code': 'operator', 'name_cn': '重复'}, format='json')
        assert response.status_code == 409
        assert_envelope(response, code=40900)

    def test_builtin_role_cannot_be_deleted(self, auth_client):
        response = auth_client.delete('/api/core/roles/1')
        assert response.status_code == 409
        assert_envelope(response, code=40900)

    def test_unknown_role_assignment_42200(self, auth_client, test_user):
        response = auth_client.post(f'/api/core/users/{test_user.id}/roles', {'roles': ['nope']}, format='json')
        assert response.status_code == 422
        body = assert_envelope(response, code=42200)
        assert 'roles' in body['data']['detail']['fields']

    def test_unknown_user_40401(self, auth_client):
        response = auth_client.post('/api/core/users/999999/roles', {'roles': ['admin']}, format='json')
        assert response.status_code == 404
        assert_envelope(response, code=40401)

    def test_role_changes_are_audited(self, auth_client, test_user):
        from aoi.audit.models import AuditLog

        created = auth_client.post('/api/core/roles', {'code': 'qa_reviewer', 'name_cn': 'QA'}, format='json')
        assert created.status_code == 200
        auth_client.post(f'/api/core/users/{test_user.id}/roles', {'roles': ['qa_reviewer']}, format='json')
        assert AuditLog.objects.filter(action='role.create').exists()
        assert AuditLog.objects.filter(action='user.roles.assign').exists()


class TestErrorCodeMapping:
    """P1：异常 → 契约错误码（Django Http404 / DRF 限流 / 405）。"""

    def test_exception_mapping(self):
        from aoi.common.views import AoiAPIView
        from django.http import Http404
        from rest_framework.exceptions import MethodNotAllowed, Throttled

        view = AoiAPIView()
        assert view._to_aoi_error(Http404()).code == 40401
        assert view._to_aoi_error(Http404()).http_status == 404
        throttled = view._to_aoi_error(Throttled())
        assert throttled.code == 42900
        assert throttled.http_status == 429
        method = view._to_aoi_error(MethodNotAllowed('GET'))
        assert (method.code, method.http_status) == (40010, 405)


class TestPermissionAnchors:
    """P1：每个 aoi 视图显式声明契约权限点（D4 只改判定实现）。"""

    SANCTIONED_NO_PERM = {
        # LS 官方 ML backend 协议：默认放行（契约 §2.4）
        'PrelabelProtocolView',
        'PrelabelHealthView',
        'PrelabelSetupView',
        'PrelabelPredictView',
        'PrelabelValidateView',
        'PrelabelWebhookView',
        # 仅需登录：返回调用者自己的角色/权限
        'PermissionsView',
    }

    def test_all_views_declare_aoi_perm(self):
        import inspect

        from aoi.audit import views as audit_views
        from aoi.common.views import AoiAPIView
        from aoi.core import views as core_views
        from aoi.datasets import views as datasets_views
        from aoi.prelabel import views as prelabel_views
        from aoi.review import views as review_views
        from aoi.training import views as training_views

        modules = [core_views, datasets_views, audit_views, prelabel_views, review_views, training_views]
        missing = []
        for module in modules:
            for name, obj in vars(module).items():
                if not inspect.isclass(obj) or not issubclass(obj, AoiAPIView) or obj is AoiAPIView:
                    continue
                if inspect.isabstract(obj):
                    continue
                if name in self.SANCTIONED_NO_PERM:
                    continue
                if not obj.aoi_perm:
                    missing.append(f'{module.__name__}.{name}')
        assert not missing, f'views without aoi_perm: {missing}'

    def test_aoi_permission_factory_is_drf_compatible(self):
        from aoi.common.permissions import aoi_permission

        cls = aoi_permission('training.publish')
        instance = cls()  # DRF get_permissions() 会这样实例化
        assert instance.perm_code == 'training.publish'
        with pytest.raises(ValueError):
            aoi_permission('')

    def test_views_use_the_documented_perm_codes(self):
        from aoi.datasets.views import DatasetExportView, DefectPublishView
        from aoi.review.views import WorkitemFinalizeView
        from aoi.training.views import ModelPublishView

        assert ModelPublishView.aoi_perm == 'training.publish'
        assert WorkitemFinalizeView.aoi_perm == 'review.finalize'
        assert DatasetExportView.aoi_perm == 'datasets.export'
        assert DefectPublishView.aoi_perm == 'datasets.publish'

        class _Request:
            method = 'POST'
            user = None

        view = ModelPublishView()
        view.request = _Request()
        permission = view.get_permissions()[0]
        assert permission.perm_code == 'training.publish'
        assert permission.has_permission(_Request(), view) is False  # 匿名（user=None）不放行


class TestRBACDeferral:
    """契约 §13.1 的 RBAC（三角色矩阵/40300/缓存失效）在 D4 落地；D2 只能冻结现状。"""

    @pytest.mark.django_db
    def test_anonymous_is_40100(self, api_client):
        response = api_client.get('/api/datasets')
        assert response.status_code == 401
        assert_envelope(response, code=40100)


# --------------------------------------------------------------------------- RBAC（D4，契约 §3.1）
#: 38 码全表（**硬编码**：锁定契约本身，不读实现常量，避免测试与实现同源互相掩护）
ALL_PERMISSION_CODES = """
datasets.view datasets.create datasets.update datasets.cancel datasets.approve datasets.publish
datasets.export datasets.delete datasets.config
training.view training.create training.update training.cancel training.approve training.publish
review.view review.create review.update review.cancel review.approve review.publish review.finalize
prelabel.view prelabel.create prelabel.update
system.view system.create system.update system.cancel system.approve system.publish
system.roles system.users system.audit system.storage system.ml system.webhook system.labels
""".split()

#: 三角色默认矩阵（硬编码）
OPERATOR_CODES = {
    'datasets.view',
    'datasets.create',
    'datasets.update',
    'training.view',
    'review.view',
    'review.update',
    'review.finalize',
}

ADMIN_CODES = OPERATOR_CODES | {
    'datasets.publish',
    'datasets.export',
    'datasets.delete',
    'datasets.config',
    'prelabel.view',
    'prelabel.create',
    'prelabel.update',
    'training.create',
    'training.cancel',
    'training.approve',
    'training.publish',
}


@pytest.fixture
def grant_roles(db):
    """给用户授予角色（全量覆盖），并 bump 授权版本号。"""
    from aoi.core import authz
    from aoi.core.models import Role, UserRole

    def _grant(user, *role_codes: str):
        role_ids = dict(Role.objects.filter(code__in=role_codes).values_list('code', 'id'))
        UserRole.objects.filter(user_id=user.id).delete()
        for code in sorted(set(role_codes)):
            UserRole.objects.create(user_id=user.id, role_id=role_ids[code])
        authz.bump_version()
        return user

    return _grant


@pytest.fixture
def make_user(db):
    """建 LS 账号（RBAC 用例专用，不复用 ``test_user``）。"""
    import itertools

    from django.contrib.auth import get_user_model

    counter = itertools.count(1)

    def _make(role_code: str | None = None, *, email: str | None = None):
        user = get_user_model().objects.create_user(
            email=email or f'rbac-{next(counter)}@example.com',
            password='rbac-pass-123',
        )
        return user

    return _make


@pytest.fixture
def client_for(make_user, grant_roles):
    """``client_for('operator')`` → 已认证的 APIClient（每次新建，互不串号）。"""

    def _client_for(*role_codes: str, user=None):
        user = user or make_user()
        if role_codes:
            grant_roles(user, *role_codes)
        client = APIClient()
        client.force_authenticate(user=user)
        return client

    return _client_for


class TestPermissionCodeRegistry:
    """权限码表与视图锚点（契约 §3.1）。"""

    def test_code_table_is_the_frozen_38(self):
        from aoi.core.permissions import PERMISSION_CODES

        assert len(ALL_PERMISSION_CODES) == 38
        assert len(set(ALL_PERMISSION_CODES)) == 38
        assert sorted(PERMISSION_CODES) == sorted(ALL_PERMISSION_CODES)

    def test_every_view_anchor_is_a_known_code(self):
        import inspect

        from aoi.audit import views as audit_views
        from aoi.common.views import AoiAPIView
        from aoi.core import views as core_views
        from aoi.core.permissions import PERMISSION_CODES
        from aoi.datasets import views as datasets_views
        from aoi.prelabel import views as prelabel_views
        from aoi.review import views as review_views
        from aoi.training import views as training_views

        modules = [core_views, datasets_views, audit_views, prelabel_views, review_views, training_views]
        bad = []
        for module in modules:
            for name, obj in vars(module).items():
                if not inspect.isclass(obj) or not issubclass(obj, AoiAPIView) or obj is AoiAPIView:
                    continue
                declared = [obj.aoi_perm, *obj.aoi_perm_by_method.values()]
                bad += [
                    f'{module.__name__}.{name}:{code}' for code in declared if code and code not in PERMISSION_CODES
                ]
        assert not bad, f'unknown permission codes on views: {bad}'

    def test_role_matrix_codes_are_all_known(self):
        from aoi.core.permissions import DEFAULT_ROLE_MATRIX, PERMISSION_CODES

        for role_code, codes in DEFAULT_ROLE_MATRIX.items():
            unknown = sorted(set(codes) - set(PERMISSION_CODES))
            assert not unknown, f'{role_code} has unknown codes: {unknown}'
        # super_admin 覆盖全码（播种的「只加不减」补授以此为前提）
        assert set(DEFAULT_ROLE_MATRIX['super_admin']) == set(PERMISSION_CODES)
        # 管理员是操作员的超集
        assert set(DEFAULT_ROLE_MATRIX['operator']) <= set(DEFAULT_ROLE_MATRIX['admin'])


@pytest.mark.django_db
class TestRbacMatrix:
    """三角色矩阵在库里逐码生效（契约 §3.1）。"""

    def _seeded_matrix(self) -> dict[str, set[str]]:
        from aoi.core.models import Permission, Role, RolePermission

        codes = dict(Permission.objects.values_list('id', 'code'))
        result: dict[str, set[str]] = {}
        for role in Role.objects.all():
            perm_ids = RolePermission.objects.filter(role_id=role.id).values_list('permission_id', flat=True)
            result[role.code] = {codes[pid] for pid in perm_ids}
        return result

    def test_seeded_permissions_are_the_frozen_38(self):
        from aoi.core.models import Permission

        assert sorted(Permission.objects.values_list('code', flat=True)) == sorted(ALL_PERMISSION_CODES)

    def test_operator_matrix(self):
        assert self._seeded_matrix()['operator'] == OPERATOR_CODES

    def test_admin_matrix(self):
        assert self._seeded_matrix()['admin'] == ADMIN_CODES

    def test_super_admin_matrix(self):
        assert self._seeded_matrix()['super_admin'] == set(ALL_PERMISSION_CODES)

    def test_operator_can_view_datasets(self, client_for):
        assert client_for('operator').get('/api/datasets/images').status_code == 200

    def test_admin_can_export_but_operator_cannot(self, client_for):
        operator = client_for('operator').get('/api/datasets/1/versions/1.0.0/export')
        assert operator.status_code == 403
        assert_envelope(operator, code=40300)

        admin = client_for('admin').get('/api/datasets/1/versions/1.0.0/export')
        assert admin.status_code == 200


@pytest.mark.django_db
class TestRbacForbidden40300:
    """越权一律 40300（契约 §3.1）。"""

    OVER_PERMISSION_CALLS = (
        ('POST', '/api/datasets/defects/publish', 'datasets.publish'),
        ('GET', '/api/datasets/1/versions/1.0.0/export', 'datasets.export'),
        ('POST', '/api/train/jobs', 'training.create'),
        ('GET', '/api/core/roles', 'system.roles'),
    )

    @pytest.mark.parametrize('method,path,perm', OVER_PERMISSION_CALLS)
    def test_operator_denied(self, client_for, method, path, perm):
        client = client_for('operator')
        response = (
            getattr(client, METHOD_CALL[method])(path, {}, format='json')
            if method == 'POST'
            else getattr(client, METHOD_CALL[method])(path)
        )
        assert response.status_code == 403, (perm, response.content[:200])
        assert_envelope(response, code=40300)

    def test_user_without_role_is_denied_everywhere(self, client_for):
        client = client_for()  # 无角色
        response = client.get('/api/datasets/images')
        assert response.status_code == 403
        assert_envelope(response, code=40300)

        perms = client.get('/api/core/permissions')
        assert perms.status_code == 200  # 豁免：无角色也应能拿到自己的权限集
        assert perms.json()['data'] == {'user_id': perms.json()['data']['user_id'], 'roles': [], 'perms': []}

    def test_anonymous_is_40100_not_40300(self, api_client):
        response = api_client.get('/api/datasets/images')
        assert response.status_code == 401
        assert_envelope(response, code=40100)


@pytest.mark.django_db
class TestPermCacheInvalidation:
    """授权变更**零延迟**生效（契约 §3.1：版本号每请求读一次）。"""

    def test_grant_and_revoke_take_effect_immediately(self, make_user, grant_roles):
        from aoi.core.models import AuthzState, UserRole

        user = make_user()
        client = APIClient()
        client.force_authenticate(user=user)
        assert client.get('/api/datasets/images').status_code == 403

        before = AuthzState.objects.get(pk=1).version
        grant_roles(user, 'operator')
        assert AuthzState.objects.get(pk=1).version > before
        assert client.get('/api/datasets/images').status_code == 200  # 同进程立即生效

        UserRole.objects.filter(user_id=user.id).delete()
        from aoi.core import authz

        authz.bump_version()
        assert client.get('/api/datasets/images').status_code == 403  # 撤销同样立即生效

    def test_deleted_user_loses_roles_without_cleanup(self, make_user, grant_roles):
        from django.contrib.auth import get_user_model

        user = make_user()
        grant_roles(user, 'operator')
        client = APIClient()
        client.force_authenticate(user=user)
        assert client.get('/api/datasets/images').status_code == 200

        user_id = user.id
        get_user_model().objects.filter(pk=user_id).delete()  # user_role 残留（不建外键）
        from aoi.core import authz

        authz.bump_version()
        from aoi.core.models import UserRole

        assert UserRole.objects.filter(user_id=user_id).exists()  # 确实残留
        assert authz.resolve_user_perms(user_id) == frozenset()  # 但读时校验 → 无权限


@pytest.mark.django_db
class TestRoleAdminApi:
    """角色与授权端点语义（契约 §4.0）。"""

    def test_get_role_returns_permissions(self, client_for):
        body = assert_envelope(client_for('super_admin').get('/api/core/roles'))
        roles = {item['code']: item for item in body['data']['items']}
        assert set(roles['operator']['permissions']) == OPERATOR_CODES
        assert 'permissions' in roles['admin']

    def test_put_role_replaces_permissions(self, client_for):
        client = client_for('super_admin')
        response = client.put('/api/core/roles/2', {'permissions': ['datasets.view']}, format='json')
        body = assert_envelope(response)
        assert body['data']['permissions'] == ['datasets.view']

        # 清空
        response = client.put('/api/core/roles/2', {'permissions': []}, format='json')
        assert assert_envelope(response)['data']['permissions'] == []

    def test_put_role_unknown_code_is_42200(self, client_for):
        response = client_for('super_admin').put('/api/core/roles/2', {'permissions': ['nope.nope']}, format='json')
        assert response.status_code == 422
        assert_envelope(response, code=42200)

    def test_builtin_role_cannot_be_deleted(self, client_for):
        response = client_for('super_admin').delete('/api/core/roles/1')
        assert response.status_code == 409
        assert_envelope(response, code=40900)

    def test_custom_role_delete_cascades_user_role(self, client_for, grant_roles, make_user):
        from aoi.core.models import Role, UserRole

        client = client_for('super_admin')
        created = assert_envelope(client.post('/api/core/roles', {'code': 'qa', 'name_cn': 'QA'}, format='json'))
        role_id = created['data']['id']

        user = make_user()
        grant_roles(user, 'qa')
        assert UserRole.objects.filter(user_id=user.id, role_id=role_id).exists()

        assert client.delete(f'/api/core/roles/{role_id}').status_code == 200
        assert not UserRole.objects.filter(role_id=role_id).exists()
        assert not Role.objects.filter(id=role_id).exists()

    def test_assign_roles_is_full_overwrite(self, client_for):
        created = assert_envelope(
            client_for('super_admin').post('/api/core/roles', {'code': 'qa2', 'name_cn': 'QA2'}, format='json')
        )
        assert created['data']['code'] == 'qa2'

        user_client = client_for('operator')
        user_id = user_client.get('/api/core/permissions').json()['data']['user_id']
        admin = client_for('super_admin')
        assert admin.post(f'/api/core/users/{user_id}/roles', {'roles': ['qa2']}, format='json').status_code == 200
        assert user_client.get('/api/core/permissions').json()['data']['roles'] == ['qa2']

        assert admin.post(f'/api/core/users/{user_id}/roles', {'roles': []}, format='json').status_code == 200
        assert user_client.get('/api/core/permissions').json()['data']['roles'] == []

    def test_assign_unknown_role_is_42200(self, client_for):
        response = client_for('super_admin').post('/api/core/users/1/roles', {'roles': ['nope']}, format='json')
        assert response.status_code == 422
        assert_envelope(response, code=42200)

    def test_assign_to_missing_user_is_40401(self, client_for):
        response = client_for('super_admin').post(
            '/api/core/users/999999/roles', {'roles': ['operator']}, format='json'
        )
        assert response.status_code == 404
        assert_envelope(response, code=40401)


@pytest.mark.django_db
class TestGrantRoleCommand:
    """``aoi_grant_role``（首个超管引导，契约 §3.1）。"""

    def test_grant_is_full_overwrite_and_audited(self, make_user, capsys):
        from aoi.audit.models import AuditLog
        from aoi.core.models import UserRole
        from django.core.management import call_command

        user = make_user(email='ops@nbhx.com')
        call_command('aoi_grant_role', 'ops@nbhx.com', 'operator')
        assert UserRole.objects.filter(user_id=user.id).count() == 1
        assert AuditLog.objects.filter(action='user.roles.assign', object_id=str(user.id)).exists()

        call_command('aoi_grant_role', 'ops@nbhx.com', 'admin', 'super_admin')
        assert UserRole.objects.filter(user_id=user.id).count() == 2

        call_command('aoi_grant_role', 'ops@nbhx.com', '--clear')
        assert UserRole.objects.filter(user_id=user.id).count() == 0

    def test_list_outputs_mapping(self, make_user, grant_roles, capsys):
        from django.core.management import call_command

        user = make_user(email='listed@nbhx.com')
        grant_roles(user, 'operator')
        call_command('aoi_grant_role', '--list')
        out = capsys.readouterr().out
        assert 'listed@nbhx.com' in out
        assert 'operator' in out

    def test_unknown_role_fails(self, make_user):
        from django.core.management import call_command
        from django.core.management.base import CommandError

        make_user(email='ops2@nbhx.com')
        with pytest.raises(CommandError):
            call_command('aoi_grant_role', 'ops2@nbhx.com', 'nope')

    def test_unknown_email_fails(self):
        from django.core.management import call_command
        from django.core.management.base import CommandError

        with pytest.raises(CommandError):
            call_command('aoi_grant_role', 'ghost@nbhx.com', 'operator')


@pytest.mark.django_db
class TestSeedRbac:
    """播种语义（契约 §3.1）：幂等 + 内置角色不覆盖 + super_admin 只加不减。"""

    def test_seed_is_idempotent(self):
        from aoi.core.models import Permission, Role, RolePermission
        from aoi.core.permissions import seed_rbac

        before = (Permission.objects.count(), Role.objects.count(), RolePermission.objects.count())
        stats = seed_rbac()
        assert stats == {'permissions_created': 0, 'permissions_updated': 0, 'roles_created': 0, 'grants_created': 0}
        assert (Permission.objects.count(), Role.objects.count(), RolePermission.objects.count()) == before

    def test_builtin_role_grants_are_not_reapplied(self):
        from aoi.core.models import Permission, Role, RolePermission
        from aoi.core.permissions import seed_rbac

        admin = Role.objects.get(code='admin')
        target = Permission.objects.get(code='datasets.export')
        RolePermission.objects.filter(role_id=admin.id, permission_id=target.id).delete()

        seed_rbac()
        # 人工调整（这里是撤销）不被重启回滚
        assert not RolePermission.objects.filter(role_id=admin.id, permission_id=target.id).exists()

    def test_super_admin_grants_are_backfilled(self):
        from aoi.core.models import Permission, Role, RolePermission
        from aoi.core.permissions import PERMISSION_CODES, seed_rbac

        super_admin = Role.objects.get(code='super_admin')
        target = Permission.objects.get(code='system.labels')
        RolePermission.objects.filter(role_id=super_admin.id, permission_id=target.id).delete()

        stats = seed_rbac()
        assert stats['grants_created'] == 1
        granted = set(
            Permission.objects.filter(
                id__in=RolePermission.objects.filter(role_id=super_admin.id).values_list('permission_id', flat=True)
            ).values_list('code', flat=True)
        )
        assert granted == set(PERMISSION_CODES)


@pytest.mark.django_db
class TestUserAdminApi:
    """组织管理端点语义（契约 §4.0，D5）。"""

    def test_non_super_admin_is_40300(self, client_for, make_user):
        target = make_user()
        operator = client_for('operator')
        for method, url in [
            ('get', '/api/core/users'),
            ('post', f'/api/core/users/{target.id}/deactivate'),
            ('post', f'/api/core/users/{target.id}/activate'),
        ]:
            response = getattr(operator, method)(url)
            assert response.status_code == 403, url
            assert_envelope(response, code=40300)
        # 无角色用户同样拒绝
        assert client_for().get('/api/core/users').status_code == 403

    def test_list_users_includes_aoi_roles(self, client_for, make_user, grant_roles):
        user = make_user()
        grant_roles(user, 'operator')
        body = assert_envelope(client_for('super_admin').get('/api/core/users'))
        items = {item['id']: item for item in body['data']['items']}
        assert items[user.id] == {'id': user.id, 'email': user.email, 'is_active': True, 'roles': ['operator']}

    def test_admin_and_operator_toggle_take_effect_immediately(self, client_for):
        """前端任免语义：读取现有角色 → 独立增删 admin/operator → 全量覆盖提交。"""
        user_client = client_for('operator')
        user_id = user_client.get('/api/core/permissions').json()['data']['user_id']
        admin = client_for('super_admin')

        ok = admin.post(f'/api/core/users/{user_id}/roles', {'roles': ['admin', 'operator']}, format='json')
        assert ok.status_code == 200
        assert sorted(user_client.get('/api/core/permissions').json()['data']['roles']) == ['admin', 'operator']

        ok = admin.post(f'/api/core/users/{user_id}/roles', {'roles': ['operator']}, format='json')
        assert ok.status_code == 200
        assert user_client.get('/api/core/permissions').json()['data']['roles'] == ['operator']

    def test_deactivate_combo_and_jwt_rejected(self, client_for, make_user, grant_roles):
        """停用组合拳：is_active=False + 清角色 + 软移除组织成员；已签发 JWT 立即失效。"""
        from aoi.audit.models import AuditLog
        from aoi.core.models import UserRole
        from organizations.models import Organization, OrganizationMember

        user = make_user()
        grant_roles(user, 'admin')
        login = APIClient().post('/api/auth/login', {'email': user.email, 'password': 'rbac-pass-123'}, format='json')
        access = assert_envelope(login)['data']['access']
        Organization.create_organization(created_by=user, title='deactivate-combo')
        assert OrganizationMember.objects.filter(user=user, deleted_at__isnull=True).exists()

        response = client_for('super_admin').post(f'/api/core/users/{user.id}/deactivate')
        assert response.status_code == 200
        assert assert_envelope(response)['data'] == {'user_id': user.id, 'is_active': False}

        user.refresh_from_db()
        assert user.is_active is False
        assert user.active_organization_id is None
        assert UserRole.objects.filter(user_id=user.id).count() == 0
        assert not OrganizationMember.objects.filter(user=user, deleted_at__isnull=True).exists()

        rejected = APIClient().get('/api/core/permissions', HTTP_AUTHORIZATION=f'Bearer {access}')
        assert rejected.status_code == 401
        assert_envelope(rejected, code=40100)

        assert AuditLog.objects.filter(action='user.deactivate', object_id=str(user.id)).exists()

    def test_activate_restores_access_but_not_roles(self, client_for, make_user, grant_roles):
        from aoi.audit.models import AuditLog
        from aoi.core.models import UserRole
        from organizations.models import Organization, OrganizationMember

        user = make_user()
        grant_roles(user, 'admin')
        Organization.create_organization(created_by=user, title='activate-restore')
        admin = client_for('super_admin')
        assert admin.post(f'/api/core/users/{user.id}/deactivate').status_code == 200

        login = APIClient().post('/api/auth/login', {'email': user.email, 'password': 'rbac-pass-123'}, format='json')
        assert login.status_code == 401

        assert admin.post(f'/api/core/users/{user.id}/activate').status_code == 200
        user.refresh_from_db()
        assert user.is_active is True
        assert OrganizationMember.objects.filter(user=user, deleted_at__isnull=True).exists()
        assert user.active_organization_id is not None
        assert UserRole.objects.filter(user_id=user.id).count() == 0  # 角色不回补，需重新任命
        assert AuditLog.objects.filter(action='user.activate', object_id=str(user.id)).exists()

        login = APIClient().post('/api/auth/login', {'email': user.email, 'password': 'rbac-pass-123'}, format='json')
        assert login.status_code == 200

    def test_deactivate_missing_user_is_40401(self, client_for):
        response = client_for('super_admin').post('/api/core/users/999999/deactivate')
        assert response.status_code == 404
        assert_envelope(response, code=40401)


@pytest.mark.django_db
class TestLastSuperAdminGuard:
    """最后超管守卫（契约 §3.1，D5）：活跃超管不可归零。

    注意：``client_for('super_admin')`` 每次调用都会**新建**一个超管，
    会改变"最后一个超管"的前提——守卫用例一律以既有账号身份行动。
    """

    @staticmethod
    def _bootstrap_user():
        from aoi.core.bootstrap import BOOTSTRAP_SUPER_ADMIN_EMAIL
        from django.contrib.auth import get_user_model

        return get_user_model().objects.get(email__iexact=BOOTSTRAP_SUPER_ADMIN_EMAIL)

    def test_cannot_deactivate_last_super_admin(self, client_for):
        target = self._bootstrap_user()
        response = client_for(user=target).post(f'/api/core/users/{target.id}/deactivate')
        assert response.status_code == 409
        assert_envelope(response, code=40900)

    def test_cannot_clear_roles_of_last_super_admin(self, client_for):
        target = self._bootstrap_user()
        response = client_for(user=target).post(f'/api/core/users/{target.id}/roles', {'roles': []}, format='json')
        assert response.status_code == 409
        assert_envelope(response, code=40900)

        # 自保持 super_admin 的重授不受守卫影响
        response = client_for(user=target).post(
            f'/api/core/users/{target.id}/roles', {'roles': ['super_admin']}, format='json'
        )
        assert response.status_code == 200

    def test_second_super_admin_allows_demote_then_blocks_last(self, client_for, make_user, grant_roles):
        other = make_user()
        grant_roles(other, 'super_admin')
        acting = client_for(user=other)
        target = self._bootstrap_user()

        # 仍有 other 在位：降级 bootstrap 允许
        assert acting.post(f'/api/core/users/{target.id}/roles', {'roles': []}, format='json').status_code == 200

        # other 成为最后一个活跃超管：停用被拒
        response = acting.post(f'/api/core/users/{other.id}/deactivate')
        assert response.status_code == 409
        assert_envelope(response, code=40900)


@pytest.mark.django_db
class TestBootstrapSuperAdmin:
    """固定超管播种（契约 §3.1 超管引导，D5）。"""

    @staticmethod
    def _user():
        from aoi.core.bootstrap import BOOTSTRAP_SUPER_ADMIN_EMAIL
        from django.contrib.auth import get_user_model

        return get_user_model().objects.get(email__iexact=BOOTSTRAP_SUPER_ADMIN_EMAIL)

    def test_seeded_with_org_wiring_and_role(self):
        from aoi.core.bootstrap import ensure_bootstrap_super_admin
        from aoi.core.models import Role, UserRole
        from organizations.models import OrganizationMember

        # post_migrate 已播种；重跑幂等
        assert ensure_bootstrap_super_admin() is False
        user = self._user()
        assert user.is_active
        assert user.username == user.email.split('@')[0]
        assert OrganizationMember.objects.filter(user=user, deleted_at__isnull=True).exists()
        assert user.active_organization_id is not None
        super_admin = Role.objects.get(code='super_admin')
        assert UserRole.objects.filter(user_id=user.id, role_id=super_admin.id).exists()

    def test_rerun_does_not_reset_password(self):
        from aoi.core.bootstrap import ensure_bootstrap_super_admin

        user = self._user()
        user.set_password('changed-by-admin-999')
        user.save()
        ensure_bootstrap_super_admin()
        user.refresh_from_db()
        assert user.check_password('changed-by-admin-999')

    def test_recreates_when_missing(self):
        from aoi.core.bootstrap import BOOTSTRAP_SUPER_ADMIN_PASSWORD, ensure_bootstrap_super_admin
        from django.contrib.auth import get_user_model
        from organizations.models import OrganizationMember

        get_user_model().objects.filter(email__iexact='superadmin@nbhx.com').delete()
        assert ensure_bootstrap_super_admin() is True
        user = self._user()
        assert user.check_password(BOOTSTRAP_SUPER_ADMIN_PASSWORD)
        assert OrganizationMember.objects.filter(user=user, deleted_at__isnull=True).exists()
        assert user.active_organization_id is not None


@pytest.mark.django_db
class TestAoiSpaPages:
    """aoi SPA 页面路由（契约 §2.2，H22 结项）。"""

    @staticmethod
    def _session_client(client, user):
        """带 ``last_login`` 的会话客户端。

        LS 登录包装（``users/functions/common.py::login``）会写 ``session['last_login']``；
        不写会被 ``InactivitySessionTimeoutMiddleWare`` 当成长时间未活动登出。
        会话引擎为 signed-cookie：``save()`` 把数据编码进新 session key，
        必须回写 cookie，否则客户端仍发送旧值。
        """
        import time

        from django.conf import settings

        client.force_login(user)
        session = client.session
        session['last_login'] = time.time()
        session.save()
        client.cookies[settings.SESSION_COOKIE_NAME] = session.session_key
        return client

    @pytest.mark.parametrize(
        'path',
        ['/datasets', '/datasets/', '/training', '/review', '/system', '/organization-admin', '/organization-admin/'],
    )
    def test_page_routes_render_shell(self, client, test_user, path):
        response = self._session_client(client, test_user).get(path)
        assert response.status_code == 200, (path, response.content[:200])

    def test_anonymous_redirects_to_login(self, client):
        response = client.get('/organization-admin')
        assert response.status_code == 302
        assert '/user/login/' in response['Location']

    def test_spa_routes_do_not_shadow_upstream(self):
        """点名路由而非泛 catch-all：上游路由不受影响（aoi.urls 无前缀 include 优先级最高）。"""
        from django.urls import resolve

        assert resolve('/admin/').view_name == 'admin:index'
        assert resolve('/docs/').view_name == 'docs-redirect'
        assert resolve('/heidi-tips/').view_name == 'aoi-heidi-tips'
        assert resolve('/api/auth/export/').view_name == 'data_export:project-export-files-auth-check'
        assert resolve('/api/core/users/1/roles/').view_name == 'aoi-slash-fallback'


@pytest.mark.django_db
class TestNativeGate:
    """LS 原生闸门（契约 §3.1.1）：deny-list 4 类高危 + 前缀陷阱。"""

    DENIED_FOR_OPERATOR = (
        ('delete', '/api/projects/1/'),
        ('patch', '/api/projects/1/'),
        ('post', '/api/projects/1/summary/reset/'),
        ('post', '/api/projects/1/exports/'),
        ('get', '/api/auth/export/'),
        ('post', '/api/storages/localfiles/'),
        ('post', '/api/ml/'),
        ('post', '/api/users/'),
    )

    def test_operator_is_blocked(self, client_for):
        client = client_for('operator')
        for method, path in self.DENIED_FOR_OPERATOR:
            response = (
                getattr(client, method)(path, {}, format='json') if method == 'post' else getattr(client, method)(path)
            )
            assert response.status_code == 403, (method, path, response.content[:200])
            # LS 方言错误体（非 aoi 信封）
            assert 'detail' in response.json()

    def test_admin_can_delete_project_but_not_touch_infra(self, client_for):
        admin = client_for('admin')
        assert admin.delete('/api/projects/1/').status_code != 403  # datasets.delete ✅
        assert admin.post('/api/ml/', {}, format='json').status_code == 403  # system.ml ❌
        assert admin.post('/api/storages/localfiles/', {}, format='json').status_code == 403

    def test_super_admin_passes_the_gate(self, client_for):
        client = client_for('super_admin')
        for method, path in self.DENIED_FOR_OPERATOR:
            response = (
                getattr(client, method)(path, {}, format='json') if method == 'post' else getattr(client, method)(path)
            )
            assert response.status_code != 403, (method, path, response.content[:200])

    def test_reads_are_not_gated(self, client_for):
        client = client_for('operator')
        assert client.get('/api/projects/').status_code != 403
        assert client.get('/api/projects/1/').status_code != 403
        assert client.get('/api/organizations/').status_code != 403
        assert client.get('/api/storages/').status_code != 403

    def test_auth_prefix_trap(self, client_for):
        """aoi 的 /api/auth/login|logout 放行，上游 /api/auth/export/ 拦截。"""
        client = client_for('operator')
        assert client.post('/api/auth/login', {'email': 'x@y.z', 'password': 'nope'}, format='json').status_code != 403
        assert client.post('/api/auth/logout', {}, format='json').status_code != 403
        assert client.get('/api/auth/export/').status_code == 403

    def test_readonly_import_retrieval_is_not_gated(self, client_for):
        """`ProjectImportAPI`/`ProjectReimportAPI` 是 RetrieveAPIView（只读），不得拦。"""
        client = client_for('operator')
        assert client.get('/api/projects/1/imports/1/').status_code != 403
        assert client.get('/api/projects/1/reimports/1/').status_code != 403

    def test_project_create_is_an_anchor_not_a_block(self, client_for):
        assert client_for('operator').post('/api/projects/', {'title': 't'}, format='json').status_code != 403


@pytest.mark.django_db
class TestNativeGateAnnotationFlow:
    """标注主流程绝不能被闸门误拦（最高优先级回归，契约 §3.1.1）。"""

    EXEMPT_CALLS = (
        ('post', '/api/token/', True),
        ('get', '/api/current-user/whoami', False),
        ('post', '/api/tasks/1/annotations/', True),
        ('patch', '/api/tasks/1', True),
        ('post', '/api/dm/views/', True),
        ('get', '/api/projects/1/next/', False),
        ('post', '/api/prelabel/1/health', True),
        ('post', '/api/ingest/findings', True),
    )

    @pytest.mark.parametrize('method,path,with_body', EXEMPT_CALLS)
    def test_exempt_paths_are_never_403(self, client_for, method, path, with_body):
        client = client_for('operator')
        call = getattr(client, method)
        response = call(path, {}, format='json') if with_body else call(path)
        assert response.status_code != 403, (method, path, response.content[:200])

    def test_annotations_post_reaches_the_view(self, client_for):
        """POST 任务标注不被闸门拦：应落到视图（无该 task → 404），而不是 403。"""
        response = client_for('operator').post('/api/tasks/1/annotations/', {}, format='json')
        assert response.status_code == 404


# --------------------------------------------------------------------------- 前端素材（D4）
@pytest.mark.django_db
class TestHeidiTipsRoute:
    """遮蔽上游 ``/heidi-tips``：返回平台自有集合，链接为绝对地址。"""

    def test_returns_platform_collections(self, api_client):
        response = api_client.get('/heidi-tips/')
        assert response.status_code == 200
        body = response.json()
        assert set(body) == {'projectCreation', 'projectSettings', 'organizationPage'}
        for collection, tips in body.items():
            # 空集合会让前端 getRandomTip 返回 null（tips 全部消失），必须非空
            assert tips, collection
            for tip in tips:
                assert tip['title'] and tip['content']
                assert tip['link']['url'].startswith('http'), tip['link']['url']

    def test_contains_no_upstream_marketing_copy(self, api_client):
        raw = api_client.get('/heidi-tips/').content.decode('utf-8')
        for banned in ('Enterprise', 'Starter Cloud', 'humansignal', 'labelstud.io'):
            assert banned not in raw, banned


@pytest.mark.django_db
class TestLoginPageBranding:
    """登录页品牌覆盖（仓库根 templates/ 遮蔽上游模板，D4）。"""

    def test_login_page_is_rebranded(self, client):
        response = client.get('/user/login/')
        assert response.status_code == 200
        html = response.content.decode('utf-8')
        assert '宁波华翔' in html
        assert 'AOI 数智检测' in html
        assert '<title>AOI 数智检测</title>' in html
        assert 'Human Signal' not in html
        assert 'Label Studio' not in html
        # 不再加载外站追踪/分析
        assert 'googletagmanager' not in html
        assert 'labelstud.io' not in html

    def test_login_page_serves_the_brand_logo(self, client):
        html = client.get('/user/login/').content.decode('utf-8')
        # 断言 alt 与 staticfiles 可发现性：manifest 存储下 DEBUG=False 时 URL 需 collectstatic 后才有哈希名
        assert re.search(r'<img[^>]*alt="宁波华翔 NBHX"', html), html[:2000]

        from django.contrib.staticfiles import finders

        assert finders.find('aoi/NBHX.png')


class TestLsProjectTemplate:
    """AOI 标注项目模板（契约 §4.1，D4 只交模板，真实创建在 D6）。"""

    DATASET = '门板-A线'
    VERSION = '1.0.0'
    DICT_VERSION = 'd1'

    def _kwargs(self):
        from aoi.datasets.ls_project import build_project_kwargs

        return build_project_kwargs(
            dataset_name=self.DATASET,
            version=self.VERSION,
            dict_version=self.DICT_VERSION,
            defects=label_config_sample_defects(),
        )

    def test_keys_are_exactly_the_pinned_set(self):
        from aoi.datasets.ls_project import AOI_PROJECT_DEFAULTS

        kwargs = self._kwargs()
        expected = set(AOI_PROJECT_DEFAULTS) | {'title', 'description', 'label_config'}
        assert set(kwargs) == expected

    def test_every_key_exists_on_ls_project_model(self):
        """防上游改字段名：模板里的键必须都能落在 LS ``Project`` 上。"""
        from projects.models import Project

        missing = [key for key in self._kwargs() if not hasattr(Project, key)]
        assert not missing, f'unknown LS Project fields: {missing}'

    def test_label_config_passes_ls_native_validator(self):
        from core.label_config import validate_label_config

        validate_label_config(self._kwargs()['label_config'])

    def test_template_has_no_review_settings(self):
        """LS OSS 无 Review 流（契约 §10.1）：模板不得出现任何 review 设置。"""
        kwargs = self._kwargs()
        assert not [key for key in kwargs if 'review' in key.lower()]
        assert not [key for key in kwargs if 'require_comment' in key.lower()]

    def test_pinned_defaults(self):
        kwargs = self._kwargs()
        assert kwargs['maximum_annotations'] == 1
        assert kwargs['enable_empty_annotation'] is True  # OK 图必须能提交空标注
        assert kwargs['color'] == '#FFFFFF'  # 不使用品牌色
        assert kwargs['title'] == self.DATASET
        assert self.VERSION in kwargs['description'] and self.DICT_VERSION in kwargs['description']
        assert kwargs['expert_instruction']
