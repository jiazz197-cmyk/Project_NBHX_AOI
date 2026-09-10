"""T2.7 LS 原生复用验证 smoke（默认 skip；需设置 LS_REUSE_BASE_URL 等环境变量）。

用法示例（**凭据从环境变量/密钥管理读取，不要写进仓库**）：

```bash
export LS_REUSE_BASE_URL=http://127.0.0.1:8080
export LS_REUSE_EMAIL='<测试账号邮箱>'
export LS_REUSE_PASSWORD='<测试账号密码>'
# 明确允许写操作（会新建 project/标注/MLBackend，结束后自动清理）
export LS_REUSE_ALLOW_MUTATION=1
PYTHONPATH=label_studio .venv/bin/python -m pytest tests/contracts/test_ls_reuse_smoke.py -q
```

- 未设置 ``LS_REUSE_BASE_URL`` → 整文件 skip；
- 设置了 URL 但凭据缺失/被拒 → **fail（不 skip）**，避免"零覆盖但绿灯"；
- 会写数据的用例要求 ``LS_REUSE_ALLOW_MUTATION=1``，并在模块结束时删除自己创建的 project/MLBackend；
- UI 项 4/5 为人工清单（见 ``docs/复用验证_D2.md``）。
"""

from __future__ import annotations

import base64
import io
import json
import os
import re
import time
import zipfile
from pathlib import Path

import pytest
import requests

pytestmark = pytest.mark.reuse

BASE_URL = os.environ.get('LS_REUSE_BASE_URL', '').rstrip('/')
EMAIL = os.environ.get('LS_REUSE_EMAIL')
PASSWORD = os.environ.get('LS_REUSE_PASSWORD')
TOKEN_ENV = os.environ.get('LS_REUSE_TOKEN')
ALLOW_MUTATION = os.environ.get('LS_REUSE_ALLOW_MUTATION', '').strip().lower() in {'1', 'true', 'yes', 'on'}
FIXTURES = Path(__file__).parent / 'fixtures'


def _skip_if_no_server():
    if not BASE_URL:
        pytest.skip('LS_REUSE_BASE_URL not set')


def _require_mutation_allowed():
    """写操作显式开关：防止把 smoke 指向共享/生产实例时静默改数据。"""
    if not ALLOW_MUTATION:
        pytest.skip('LS_REUSE_ALLOW_MUTATION not set (write smoke test)')


def _decode_claims(token: str) -> dict:
    payload = token.split('.')[1]
    payload += '=' * (-len(payload) % 4)
    return json.loads(base64.urlsafe_b64decode(payload))


def _access_from_refresh(session: requests.Session, refresh: str) -> str:
    response = session.post(f'{BASE_URL}/api/token/refresh/', json={'refresh': refresh}, timeout=20)
    assert response.status_code == 200, response.text[:300]
    return response.json()['access']


@pytest.fixture(scope='module')
def ls():
    """返回带 Bearer access token 的 requests.Session。"""
    _skip_if_no_server()
    session = requests.Session()

    if TOKEN_ENV:
        claims = _decode_claims(TOKEN_ENV)
        if claims.get('token_type') == 'access':
            session.headers.update({'Authorization': f'Bearer {TOKEN_ENV}'})
            session.refresh_token = None  # type: ignore[attr-defined]
        else:
            access = _access_from_refresh(session, TOKEN_ENV)
            session.headers.update({'Authorization': f'Bearer {access}'})
            session.refresh_token = TOKEN_ENV  # type: ignore[attr-defined]
        return session

    if not (EMAIL and PASSWORD):
        pytest.skip('LS_REUSE_EMAIL/LS_REUSE_PASSWORD or LS_REUSE_TOKEN not set')

    response = session.get(f'{BASE_URL}/user/login/', timeout=20)
    assert response.status_code == 200, response.text[:300]
    match = re.search(r'name="csrfmiddlewaretoken" value="([^"]+)"', response.text)
    assert match, 'csrf token not found on login page'
    login = session.post(
        f'{BASE_URL}/user/login/',
        data={
            'email': EMAIL,
            'password': PASSWORD,
            'csrfmiddlewaretoken': match.group(1),
        },
        headers={'Referer': f'{BASE_URL}/user/login/'},
        timeout=20,
    )
    assert login.status_code in (200, 302), login.text[:300]

    token_response = session.post(
        f'{BASE_URL}/api/token/',
        headers={'X-CSRFToken': session.cookies.get('csrftoken'), 'Referer': BASE_URL},
        timeout=20,
    )
    # 凭据已配置却被拒绝 → 直接失败（不再 skip 成"零覆盖绿灯"）
    assert token_response.status_code in (200, 201), (
        f'POST /api/token/ failed ({token_response.status_code}); '
        f'检查 LS_REUSE_EMAIL/LS_REUSE_PASSWORD（或提供 LS_REUSE_TOKEN）: {token_response.text[:200]}'
    )
    refresh = token_response.json()['token']
    access = _access_from_refresh(session, refresh)
    session.headers.update({'Authorization': f'Bearer {access}'})
    session.refresh_token = refresh  # type: ignore[attr-defined]
    return session


@pytest.fixture(scope='module')
def created_objects():
    """本模块创建的 LS 资源登记表，模块结束时尽力清理。"""
    registry: dict[str, list] = {'projects': [], 'ml_backends': []}
    yield registry

    session = registry.get('session')
    if session is None:
        return
    for project_id in registry['projects']:
        try:
            session.delete(f'{BASE_URL}/api/projects/{project_id}/', timeout=30)
        except Exception as exc:  # pragma: no cover - 清理失败不应掩盖测试结果
            print(f'cleanup: failed to delete project {project_id}: {exc}')
    for backend_id in registry['ml_backends']:
        try:
            session.delete(f'{BASE_URL}/api/ml/{backend_id}/', timeout=30)
        except Exception as exc:  # pragma: no cover
            print(f'cleanup: failed to delete ML backend {backend_id}: {exc}')


@pytest.fixture(scope='module')
def project(ls, created_objects):
    """新建一个带 T2.2 label config 的项目（模块内复用；模块结束删除）。"""
    _require_mutation_allowed()
    label_config = (FIXTURES / 'label_config_expected.xml').read_text(encoding='utf-8')
    response = ls.post(
        f'{BASE_URL}/api/projects/',
        json={'title': f'AOI 复用验证 smoke {int(time.time())}', 'label_config': label_config},
        timeout=30,
    )
    assert response.status_code == 201, response.text[:400]
    data = response.json()
    assert data['label_config'] == label_config
    created_objects['session'] = ls
    created_objects['projects'].append(data['id'])
    return data


@pytest.fixture(scope='module')
def imported_task(ls, project, jpeg_bytes):
    response = ls.post(
        f'{BASE_URL}/api/projects/{project["id"]}/import',
        files={'file': ('reuse_smoke.jpg', jpeg_bytes, 'image/jpeg')},
        timeout=120,
    )
    assert response.status_code == 201, response.text[:400]
    response = ls.get(f'{BASE_URL}/api/projects/{project["id"]}/tasks/', timeout=30)
    assert response.status_code == 200, response.text[:300]
    tasks = response.json()
    assert tasks, 'no tasks imported'
    return tasks[0]


class TestLsReuseSmoke:
    def test_01_login_token_whoami(self, ls):
        """① 登录 + token（HS256 JWT，claims 含 user_id）+ whoami + refresh。"""
        whoami = ls.get(f'{BASE_URL}/api/current-user/whoami', timeout=20)
        assert whoami.status_code == 200, whoami.text[:300]
        assert whoami.json()['email']

        access = ls.headers['Authorization'].split()[1]
        access_claims = _decode_claims(access)
        assert access_claims['token_type'] == 'access'
        assert 'user_id' in access_claims and access_claims['user_id']

        refresh = getattr(ls, 'refresh_token', None)
        if refresh:
            refresh_claims = _decode_claims(refresh)
            assert refresh_claims['token_type'] == 'refresh'
            assert refresh_claims['user_id'] == access_claims['user_id']
            refreshed = ls.post(f'{BASE_URL}/api/token/refresh/', json={'refresh': refresh}, timeout=20)
            assert refreshed.status_code == 200 and 'access' in refreshed.json()

    def test_02_project_label_config(self, ls, project):
        """② 新建项目 + label config 注入（RectangleLabels / object_fault_type_XX）。"""
        response = ls.get(f'{BASE_URL}/api/projects/{project["id"]}', timeout=20)
        assert response.status_code == 200, response.text[:300]
        label_config = response.json()['label_config']
        assert 'RectangleLabels' in label_config
        assert 'name="defect"' in label_config
        assert 'object_fault_type_01' in label_config and 'object_fault_type_02' in label_config

    def test_03_upload_and_download(self, ls, project, imported_task):
        """③ 上传 + 下载：MinIO 落库 + `/data/...` 鉴权下载（无服务端缩略图/默认预签名）。"""
        image = imported_task['data']['image']
        assert image.startswith('http') or image.startswith('upload/'), image
        url = image if image.startswith('http') else f'{BASE_URL}/data/{image.lstrip("/")}'
        anonymous = requests.get(url, timeout=30)
        assert anonymous.status_code == 401, 'LS /data/ 默认需要鉴权'
        authorized = ls.get(url, timeout=30)
        assert authorized.status_code == 200, authorized.text[:200]
        assert authorized.headers.get('Content-Type', '').startswith('image/')
        # 实测：label_studio 代码库无 thumbnail 端点；预签名由 aoi 侧补（见 docs/复用验证_D2.md §3）

    def test_04_annotation_rectanglelabels_api(self, ls, imported_task):
        """④ 框标注 API 基线（UI 人工清单见复用验证文档）。"""
        result = {
            'result': [
                {
                    'from_name': 'defect',
                    'to_name': 'image',
                    'type': 'rectanglelabels',
                    'score': 0.9,
                    'value': {
                        'x': 10.5,
                        'y': 12.3,
                        'width': 20.0,
                        'height': 15.0,
                        'rotation': 0,
                        'rectanglelabels': ['object_fault_type_01'],
                    },
                }
            ]
        }
        response = ls.post(f'{BASE_URL}/api/tasks/{imported_task["id"]}/annotations/', json=result, timeout=30)
        assert response.status_code == 201, response.text[:400]
        annotation = response.json()
        assert annotation['result'][0]['value']['rectanglelabels'] == ['object_fault_type_01']

    def test_05_review_flow_manual(self):
        """⑤ LS OSS 无 Review 流：实测 grep 无 review 端点/模型 → 降级 aoi 自研复审接口。"""
        pytest.skip('LS 1.24.0.dev0 OSS 无 Review 流（人工/静态证据见 docs/复用验证_D2.md §5）')

    def test_06_yolo_export(self, ls, project, imported_task):
        """⑥ data_export YOLO：zip 布局与 classes 顺序（实测无 data.yaml）。"""
        formats = ls.get(f'{BASE_URL}/api/projects/{project["id"]}/export/formats', timeout=30)
        assert formats.status_code == 200, formats.text[:300]
        names = [item.get('name') for item in formats.json() if isinstance(item, dict)]
        assert 'YOLO' in names

        export = ls.get(
            f'{BASE_URL}/api/projects/{project["id"]}/export',
            params={'export_type': 'YOLO', 'download_all_tasks': 'true', 'download_resources': 'true'},
            timeout=120,
        )
        assert export.status_code == 200, export.text[:300]
        assert export.content[:2] == b'PK'
        archive = zipfile.ZipFile(io.BytesIO(export.content))
        archive_names = archive.namelist()
        assert 'images/' in archive_names and 'labels/' in archive_names
        assert 'classes.txt' in archive_names
        # 实测：LS 1.24 输出 classes.txt + notes.json，无 data.yaml；aoi 包裹需补 data.yaml（契约语义不变）
        assert 'data.yaml' not in archive_names
        classes = archive.read('classes.txt').decode('utf-8').splitlines()
        assert classes[:2] == ['object_fault_type_01', 'object_fault_type_02']

    def test_07_ml_backend_connectivity(self, ls, project, imported_task, created_objects):
        """⑦ ML backend 连通：登记 A 自实现端点 → predict/test。"""
        _require_mutation_allowed()
        response = ls.post(
            f'{BASE_URL}/api/ml/',
            json={
                'project': project['id'],
                'url': f'{BASE_URL}/api/prelabel/{imported_task["id"]}',
                'title': f'aoi-prelabel-smoke-{int(time.time())}',
            },
            timeout=60,
        )
        if response.status_code == 403 and 'reserved network address' in response.text:
            pytest.skip('LS SSRF 保护阻止本机 URL；需 ML_BLOCK_LOCAL_IP=false + USE_DEFAULT_BANNED_SUBNETS=false')
        assert response.status_code == 201, response.text[:400]
        ml_backend_id = response.json()['id']
        created_objects['session'] = ls
        created_objects['ml_backends'].append(ml_backend_id)

        predict = ls.post(f'{BASE_URL}/api/ml/{ml_backend_id}/predict/test', params={'random': 'true'}, timeout=60)
        assert predict.status_code == 200, predict.text[:400]
        body = predict.json()
        assert body.get('response'), body
        # 实测：LS 调用只带 User-Agent（heartex/...），不携带 X-Internal-Token（见复用验证 §7）
        # 故 aoi.prelabel 默认放行；置 AOI_PRELABEL_REQUIRE_INTERNAL_TOKEN=true 可强制 40100。

    def test_08_batch_predictions_protocol(self, ls, imported_task):
        """⑧ Batch predictions：多任务批量协议（LS 侧单请求多任务，见复用验证 §8）。"""
        payload = {
            'tasks': [
                {'id': 9001, 'data': {'image': 'http://example.com/1.jpg'}},
                {'id': 9002, 'data': {'image': 'http://example.com/2.jpg'}},
            ]
        }
        response = requests.post(f'{BASE_URL}/api/prelabel/{imported_task["id"]}/predict', json=payload, timeout=30)
        assert response.status_code == 200, response.text[:300]
        body = response.json()
        assert [item['id'] for item in body['results']] == [9001, 9002]
        # LS `MLBackend.predict_tasks` 一次请求发送全部任务；同 model_version 已预测任务跳过（幂等）
