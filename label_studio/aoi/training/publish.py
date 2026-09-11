"""模型发布服务（D3 stub：假 build + 双模式 push）。

契约依据：跨平台契约 §2.4（发布 8 步）/ §2.2（tag 规范）；平台A §3.3 / §4.2；
计划 D3「发布服务 stub（假 build/push）」。

D3 语义
-------
1. **假 build**：不依赖 docker daemon，用 Python 直接构造与 ``FROM scratch + COPY model/ /model/``
   等价的 docker schema2 单层镜像产物（``layer.tar.gz`` / ``config.json`` / ``manifest.json``）；
   权重是确定性占位 ONNX（**不是**真实训练权重），``model.yaml`` 由 ``aoi.training.model_yaml`` 生成。
2. **push 双模式**（``AOI_PUBLISH_MODE``）：
   - ``fake``（默认）：不联网，digest 取本地 manifest 的 sha256，供离线开发与契约测试；
   - ``registry``：走 Registry v2 HTTP API 真推送（token → blob 单块上传 → manifest PUT），
     经 ``AOI_REGISTRY_PROXY`` 代理出网；digest **以仓库返回的 ``Docker-Content-Digest`` 回执为准**并核对，
     仓库不回回执即视为「无法证明推上去的是什么」→ 失败（``missing_digest_policy='strict'``，默认；
     ``'readback'`` 允许退化为「PUT 后 GET 回读逐字节比对」）；回执与本地不一致即视为仓库异常
     （跨平台契约 §2.4：防篡改）。
3. **状态机**：``queued → building → pushing → published``，每步落库（GET 可观察）；
   失败 → ``failed`` + ``error_message``，可人工重推（``attempts`` 递增，见 ``ModelPublishView``）。
4. **成功副作用**：``model_publish{digest, published_at}`` + ``model.lifecycle=published`` +
   ``model.config_snapshot['model_yaml']`` 快照 + 审计 ``model.published``（平台A §5.1）。
5. **产物落盘**（``AOI_PUBLISH_ARTIFACTS_DIR``，默认 ``tmp/publish/<tag>/``）：供人工核查与
   「有网机器手工直推」临时通道（``push.sh``）；``tmp/`` 已在 ``.gitignore``，不会进版本库。

D7 出界（本模块预留的接缝）
---------------------------
真实权重导出、Celery ``publish`` 队列异步化、指数退避重试（30s/2m/10m，``PUBLISH_RETRY``）、
镜像物理清理。``run_publish()`` 即未来 worker 的调用入口，发布器与状态机逻辑不必重写。
"""

from __future__ import annotations

import base64
import gzip
import hashlib
import io
import json
import logging
import re
import tarfile
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import quote

import requests
from aoi.common.audit import write_audit
from aoi.common.errors import (
    CODE_CONFLICT,
    CODE_NOT_FOUND,
    CODE_UNAVAILABLE,
    CODE_UNPROCESSABLE,
    AoiError,
)
from aoi.common.settings import (
    get_model_registry_password,
    get_model_registry_user,
    get_publish_artifacts_dir,
    get_publish_mode,
    get_registry_proxy,
)
from aoi.datasets.models import DefectClass
from aoi.training.model_yaml import build_model_yaml, dump_model_yaml, validate_model_yaml
from aoi.training.models import Model, ModelPublish
from django.utils import timezone as django_timezone

logger = logging.getLogger(__name__)

__all__ = [
    'PublishArtifacts',
    'PublishBuildError',
    'RegistryPushClient',
    'RegistryPushError',
    'build_fake_onnx',
    'build_image_artifacts',
    'build_model_files',
    'materialize_artifacts',
    'resolve_publish_artifacts_dir',
    'run_publish',
]

#: 仓库根（``<repo>/label_studio/aoi/training/publish.py`` 上溯 3 层）：
#: 相对产物目录按此解析（``settings.BASE_DIR`` 指向 ``label_studio/core``，不能用）
REPO_ROOT = Path(__file__).resolve().parents[3]

#: 镜像内固定布局（跨平台契约 §2.1）：/model/{model.onnx, model.onnx.sha256, model.yaml}
MODEL_DIR_IN_IMAGE = 'model'
LAYER_FILE_ORDER = ('model.onnx', 'model.onnx.sha256', 'model.yaml')

#: 占位权重大小与填充（与 ``tmp/fake_publish`` 人工验证产物同量级：512 × 21B）
FAKE_ONNX_SIZE = 10752
FAKE_ONNX_FILLER = b'AOI-FAKE-ONNX-WEIGHTS'

#: model.yaml 的输入形状缺省（YOLOv8 默认 1280 门板检测）
DEFAULT_INPUT_SHAPE = [1, 3, 1280, 1280]

MANIFEST_MEDIA_TYPE = 'application/vnd.docker.distribution.manifest.v2+json'
CONFIG_MEDIA_TYPE = 'application/vnd.docker.container.image.v1+json'
LAYER_MEDIA_TYPE = 'application/vnd.docker.image.rootfs.diff.tar.gzip'

#: docker.io 的 Registry v2 API 与鉴权域名（``MODEL_REGISTRY=docker.io`` 时的映射）
REGISTRY_HOST_ALIASES = {
    'docker.io': 'registry-1.docker.io',
    'index.docker.io': 'registry-1.docker.io',
}
DOCKER_HUB_REGISTRIES = frozenset(REGISTRY_HOST_ALIASES)

#: 网络超时（连接, 读取）秒；blob 很小（KB 级），60s 足够且不会把请求挂死
REGISTRY_TIMEOUT = (10.0, 60.0)

#: 仓库未返回 ``Docker-Content-Digest`` 回执时的策略（``RegistryPushClient(missing_digest_policy=...)``）：
#: - ``strict``（默认）：视为失败——宁可发布失败，也不把「本地自算值」当「仓库确认值」落库；
#: - ``readback``：PUT 后按 tag GET 回读 manifest，与本地字节逐字节比对通过才认（多一次往返换可用性）。
DIGEST_POLICY_STRICT = 'strict'
DIGEST_POLICY_READBACK = 'readback'
DIGEST_POLICIES = (DIGEST_POLICY_STRICT, DIGEST_POLICY_READBACK)

#: manifest 的 config.history 固定时间戳：保证同输入构建产物字节可复现（mtime/diff_id 稳定）
FIXED_BUILD_CREATED = '1970-01-01T00:00:00Z'
BUILD_CREATED_BY = 'AOI publish stub (D3: python-built FROM-scratch layer, no docker; real pipeline at D7)'

_BEARER_PARAM_RE = re.compile(r'(\w+)="([^"]*)"')

DOCKERFILE_TEXT = """# AOI 模型镜像（跨平台契约 §2.1/§2.4）：单层 FROM scratch，仅含 /model/*
# 真实流水线（D7）为 `docker build -t <registry>/<repo>:<tag> .` + `docker push`
FROM scratch
COPY model/ /model/
"""

PUSH_SH_TEMPLATE = """#!/usr/bin/env bash
# AOI 发布产物「手工直推」临时通道（D3~D7 之间；D7 起由发布服务 registry 模式 / docker 流水线取代）
#
# 用途：本机/机房与外网隔离时，把落盘产物拷到有网机器上直接推仓库（无需 docker daemon）。
# 仅覆盖 Docker Hub（registry-1.docker.io / auth.docker.io）；其它 registry 请用平台 registry 模式。
#
# 用法：
#   MODEL_REGISTRY_USER=rekal1018 MODEL_REGISTRY_PASSWORD=<PAT> \\
#   AOI_REGISTRY_PROXY=http://127.0.0.1:<proxy-port> ./push.sh
set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO="${MODEL_IMAGE_REPO:-%(repository)s}"
TAG="${TAG:-%(tag)s}"
USER_NAME="${MODEL_REGISTRY_USER:?请设置 MODEL_REGISTRY_USER}"
PASSWORD="${MODEL_REGISTRY_PASSWORD:?请设置 MODEL_REGISTRY_PASSWORD}"
PROXY="${AOI_REGISTRY_PROXY:-}"

CURL=(curl -fsS --retry 2)
[[ -n "$PROXY" ]] && CURL+=(-x "$PROXY")

API_HOST="registry-1.docker.io"
LAYER_DIGEST="sha256:$(sha256sum "$HERE/artifacts/layer.tar.gz" | cut -d' ' -f1)"
CONFIG_DIGEST="sha256:$(sha256sum "$HERE/artifacts/config.json" | cut -d' ' -f1)"

TOKEN="$("${CURL[@]}" -u "$USER_NAME:$PASSWORD" \\
  "https://auth.docker.io/token?service=registry.docker.io&scope=repository:${REPO}:pull,push" \\
  | sed -n 's/.*"token":"\\([^"]*\\)".*/\\1/p')"
[[ -n "$TOKEN" ]] || { echo "拿 registry token 失败（检查凭据/代理）" >&2; exit 3; }

upload_blob() { # $1=文件 $2=digest
  local location
  location="$("${CURL[@]}" -X POST -H "Authorization: Bearer $TOKEN" \\
    "https://${API_HOST}/v2/${REPO}/blobs/uploads/" -D - -o /dev/null \\
    | tr -d '\\r' | sed -n 's/^[Ll]ocation: //p')"
  "${CURL[@]}" -X PUT -H "Authorization: Bearer $TOKEN" \\
    -H 'Content-Type: application/octet-stream' \\
    --data-binary "@$1" "${location}?digest=$2" -o /dev/null
}

upload_blob "$HERE/artifacts/layer.tar.gz" "$LAYER_DIGEST"
upload_blob "$HERE/artifacts/config.json" "$CONFIG_DIGEST"

PUSHED_DIGEST="$("${CURL[@]}" -X PUT -H "Authorization: Bearer $TOKEN" \\
  -H 'Content-Type: %(manifest_media_type)s' \\
  --data-binary "@$HERE/artifacts/manifest.json" \\
  "https://${API_HOST}/v2/${REPO}/manifests/${TAG}" -D - -o /dev/null \\
  | tr -d '\\r' | sed -n 's/^[Dd]ocker-[Cc]ontent-[Dd]igest: //p')"

echo "pushed ${REPO}:${TAG} digest=${PUSHED_DIGEST:-<仓库未返回>}"
"""


class PublishBuildError(Exception):
    """构建阶段失败（模型数据不完整 / ``model.yaml`` 校验不过）→ 视图映射 42200。"""


class RegistryPushError(Exception):
    """推送阶段失败（网络 / 鉴权 / 仓库拒绝 / digest 不一致）→ 视图映射 50300。"""


@dataclass(frozen=True)
class PublishArtifacts:
    """一次发布的镜像产物（docker schema2 单层，全部为最终字节）。"""

    onnx_bytes: bytes
    onnx_sha256: str
    model_yaml_text: str
    layer_bytes: bytes
    config_bytes: bytes
    manifest_bytes: bytes
    # 全量 digest（``sha256:<hex>``），直接对应 config/manifest 字段
    diff_id: str
    layer_digest: str
    config_digest: str
    manifest_digest: str

    @property
    def digest(self) -> str:
        """镜像 digest = manifest 的 sha256（与 ``docker inspect RepoDigests`` 同源）。"""
        return self.manifest_digest

    def summary(self, *, image: str = '', tag: str = '', model_ref: str = '', mode: str = '') -> dict[str, Any]:
        return {
            'model_ref': model_ref,
            'image': image,
            'tag': tag,
            'mode': mode,
            'digest': self.digest,
            'diff_id(uncompressed tar)': self.diff_id,
            'model.onnx': {'size': len(self.onnx_bytes), 'sha256': self.onnx_sha256},
            'layer.tar.gz': {'size': len(self.layer_bytes), 'digest': self.layer_digest},
            'config.json': {'size': len(self.config_bytes), 'digest': self.config_digest},
            'manifest.json': {'size': len(self.manifest_bytes), 'digest': self.manifest_digest},
        }


# --------------------------------------------------------------------------- build
def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _utcnow_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace('+00:00', 'Z')


def build_fake_onnx(model: Any) -> bytes:
    """确定性占位权重（**非**真实 ONNX，仅供 B 侧拉取/校验链路与镜像产物验证）。

    同一 ``model_ref`` + ``precision`` 恒定输出同一份字节，便于回归与 digest 复核。
    """
    header = f'AOI-FAKE-ONNX-WEIGHTS\nmodel_ref={model.version}\nprecision={model.precision}\n'.encode()
    if len(header) >= FAKE_ONNX_SIZE:
        return header[:FAKE_ONNX_SIZE]
    repeats = FAKE_ONNX_SIZE // len(FAKE_ONNX_FILLER) + 1
    filler = FAKE_ONNX_FILLER * repeats
    return header + filler[: FAKE_ONNX_SIZE - len(header)]


def build_model_files(model: Model) -> tuple[bytes, dict[str, Any], str]:
    """生成 ``(占位权重, model.yaml dict, model.yaml 文本)``；校验不过抛 ``PublishBuildError``。"""
    onnx_bytes = build_fake_onnx(model)
    defect_classes = list(DefectClass.objects.filter(active=True).order_by('id'))
    tensor_names = model.tensor_names or {}
    input_shape = list(model.input_shape or DEFAULT_INPUT_SHAPE)
    onnx_meta = {
        'file': 'model.onnx',
        'sha256': _sha256(onnx_bytes),
        'size_bytes': len(onnx_bytes),
        'opset': 17,
        'producer': 'aoi-publish-stub',
        'input_shape': input_shape,
        'input': {
            'name': tensor_names.get('input') or 'images',
            'shape': input_shape,
            'dtype': 'float32',
            'layout': 'NCHW',
        },
        'output': {
            'name': tensor_names.get('output') or 'output0',
            'format': 'yolo_v8_xywh_conf_cls',
        },
    }
    doc = build_model_yaml(
        model,
        defect_classes=defect_classes,
        onnx_meta=onnx_meta,
        source={
            'published_at': _utcnow_iso(),
            'tags': ['publish-stub'],
            'description': 'D3 发布 stub 产物：占位权重，非真实训练权重（D7 起换成真实导出）',
        },
    )
    errors = validate_model_yaml(doc)
    if errors:
        raise PublishBuildError('model.yaml validation failed: ' + '; '.join(errors))
    return onnx_bytes, doc, dump_model_yaml(doc)


def build_image_artifacts(onnx_bytes: bytes, model_yaml_text: str) -> PublishArtifacts:
    """把 ``模型文件`` 打成 docker schema2 单层镜像产物（与 ``FROM scratch`` 构建等价）。

    确定性：tar 成员 ``mtime=0``、顺序固定、``gzip(mtime=0)``、config 时间戳固定，
    **同一份 ``model_yaml_text`` 输入**恒定输出同字节 → 同 digest。

    注意（D7 待修）：``model.yaml`` 本身带 ``created_at``/``published_at``（秒级时间戳），
    因此**换时刻重建**同一模型会得到不同 digest。修法见 ``docs/MVP开发计划.md`` §5 D7「验收附加项」。
    """
    onnx_sha256 = _sha256(onnx_bytes)
    payloads = {
        'model.onnx': onnx_bytes,
        'model.onnx.sha256': f'{onnx_sha256}\n'.encode(),
        'model.yaml': model_yaml_text.encode(),
    }

    buffer = io.BytesIO()
    with tarfile.open(fileobj=buffer, mode='w') as tar:
        for name in LAYER_FILE_ORDER:
            data = payloads[name]
            info = tarfile.TarInfo(f'{MODEL_DIR_IN_IMAGE}/{name}')
            info.size = len(data)
            info.mtime = 0
            tar.addfile(info, io.BytesIO(data))
    tar_bytes = buffer.getvalue()
    layer_bytes = gzip.compress(tar_bytes, mtime=0)

    diff_id = f'sha256:{_sha256(tar_bytes)}'
    layer_digest = f'sha256:{_sha256(layer_bytes)}'

    config_bytes = json.dumps(
        {
            'architecture': 'amd64',
            'os': 'linux',
            'config': {},
            'rootfs': {'type': 'layers', 'diff_ids': [diff_id]},
            'history': [{'created': FIXED_BUILD_CREATED, 'created_by': BUILD_CREATED_BY}],
        },
        separators=(',', ':'),
    ).encode()
    config_digest = f'sha256:{_sha256(config_bytes)}'

    manifest_bytes = json.dumps(
        {
            'schemaVersion': 2,
            'mediaType': MANIFEST_MEDIA_TYPE,
            'config': {'mediaType': CONFIG_MEDIA_TYPE, 'size': len(config_bytes), 'digest': config_digest},
            'layers': [{'mediaType': LAYER_MEDIA_TYPE, 'size': len(layer_bytes), 'digest': layer_digest}],
        },
        separators=(',', ':'),
    ).encode()
    manifest_digest = f'sha256:{_sha256(manifest_bytes)}'

    return PublishArtifacts(
        onnx_bytes=onnx_bytes,
        onnx_sha256=onnx_sha256,
        model_yaml_text=model_yaml_text,
        layer_bytes=layer_bytes,
        config_bytes=config_bytes,
        manifest_bytes=manifest_bytes,
        diff_id=diff_id,
        layer_digest=layer_digest,
        config_digest=config_digest,
        manifest_digest=manifest_digest,
    )


# ---------------------------------------------------------------------- materialize
def resolve_publish_artifacts_dir() -> Path | None:
    """解析产物落盘根目录；未配置/显式关闭返回 ``None``。相对路径按**仓库根**解析。

    Django ``settings.BASE_DIR`` 指向 ``label_studio/core``（不是仓库根），故这里以本文件位置
    上溯定位仓库根（``<repo>/label_studio/aoi/training/publish.py``）。
    """
    raw = get_publish_artifacts_dir()
    if not raw:
        return None
    path = Path(raw).expanduser()
    if not path.is_absolute():
        path = REPO_ROOT / path
    return path


def materialize_artifacts(
    artifacts: PublishArtifacts,
    target_dir: Path,
    *,
    image: str = '',
    tag: str = '',
    model_ref: str = '',
    mode: str = '',
) -> Path:
    """把产物写盘（``model/`` + ``artifacts/`` + ``Dockerfile`` + ``push.sh``），返回目录。"""
    target_dir = Path(target_dir)
    model_dir = target_dir / MODEL_DIR_IN_IMAGE
    artifacts_dir = target_dir / 'artifacts'
    model_dir.mkdir(parents=True, exist_ok=True)
    artifacts_dir.mkdir(parents=True, exist_ok=True)

    (model_dir / 'model.onnx').write_bytes(artifacts.onnx_bytes)
    (model_dir / 'model.onnx.sha256').write_text(f'{artifacts.onnx_sha256}\n', encoding='utf-8')
    (model_dir / 'model.yaml').write_text(artifacts.model_yaml_text, encoding='utf-8')

    (artifacts_dir / 'layer.tar.gz').write_bytes(artifacts.layer_bytes)
    (artifacts_dir / 'config.json').write_bytes(artifacts.config_bytes)
    (artifacts_dir / 'manifest.json').write_bytes(artifacts.manifest_bytes)
    (artifacts_dir / 'digest.txt').write_text(
        json.dumps(artifacts.summary(image=image, tag=tag, model_ref=model_ref, mode=mode), indent=2, ensure_ascii=False),
        encoding='utf-8',
    )

    (target_dir / 'Dockerfile').write_text(DOCKERFILE_TEXT, encoding='utf-8')
    push_sh = target_dir / 'push.sh'
    repository = _repository_from_image(image)
    push_sh.write_text(
        PUSH_SH_TEMPLATE
        % {
            'repository': repository or 'rekal1018/aoi-model',
            'tag': tag,
            'manifest_media_type': MANIFEST_MEDIA_TYPE,
        },
        encoding='utf-8',
    )
    push_sh.chmod(0o755)
    return target_dir


def _repository_from_image(image: str) -> str:
    """``docker.io/rekal1018/aoi-model`` → ``rekal1018/aoi-model``。"""
    if not image:
        return ''
    for registry in sorted(REGISTRY_HOST_ALIASES, key=len, reverse=True):
        prefix = f'{registry}/'
        if image.startswith(prefix):
            return image[len(prefix) :]
    if '/' in image:
        head, rest = image.split('/', 1)
        if '.' in head or ':' in head:  # 其它 registry 域名/端口前缀
            return rest
    return image


# --------------------------------------------------------------------- registry push
def _parse_bearer_challenge(header: str) -> dict[str, str]:
    """解析 ``WWW-Authenticate: Bearer realm="...",service="..."``（非 Bearer 返回空）。"""
    if not header or not header.lower().startswith('bearer'):
        return {}
    return {match.group(1): match.group(2) for match in _BEARER_PARAM_RE.finditer(header)}


def _content_digest(response: requests.Response) -> str:
    """取仓库回执头 ``Docker-Content-Digest``（requests 头名大小写不敏感，实测 Docker Hub 回小写）。"""
    return (response.headers.get('Docker-Content-Digest') or '').strip()


class RegistryPushClient:
    """按 Docker Registry HTTP API v2 推送镜像（token → blob 单块上传 → manifest PUT）。

    - ``proxy`` 只作用于本客户端的 ``requests.Session``，不影响平台其它出网流量；
    - **digest 必须由仓库确认**：blob / manifest 的应答都要带 ``Docker-Content-Digest`` 回执，且与本地
      sha256 一致；不回回执按 ``missing_digest_policy`` 处理（``strict`` 失败 / ``readback`` 回读比对），
      回执不一致直接失败（跨平台契约 §2.4：digest 用于校验仓库内容未被篡改）。
    - 实测：Docker Hub 的 blob/manifest PUT 均回 ``docker-content-digest``（**小写**头名），本实现按
      大小写不敏感读取；仍保留「仓库没给收据」的显式策略，避免任何情况下悄悄用本地值兜底。
    """

    def __init__(
        self,
        *,
        registry: str,
        repository: str,
        username: str = '',
        password: str = '',
        proxy: str = '',
        timeout: tuple[float, float] = REGISTRY_TIMEOUT,
        missing_digest_policy: str = DIGEST_POLICY_STRICT,
    ) -> None:
        if not repository:
            raise RegistryPushError('empty image repository')
        if missing_digest_policy not in DIGEST_POLICIES:
            raise RegistryPushError(f'unknown missing_digest_policy: {missing_digest_policy!r}')
        self.registry = registry
        self.repository = repository
        self.username = username
        self.password = password
        self.timeout = timeout
        self.missing_digest_policy = missing_digest_policy
        self.session = requests.Session()
        if proxy:
            self.session.proxies.update({'http': proxy, 'https': proxy})

    @property
    def api_base(self) -> str:
        return f'https://{REGISTRY_HOST_ALIASES.get(self.registry, self.registry)}'

    # ------------------------------------------------------------------ internals
    def _request(self, method: str, url: str, **kwargs: Any) -> requests.Response:
        try:
            return self.session.request(method, url, timeout=self.timeout, **kwargs)
        except requests.RequestException as exc:
            raise RegistryPushError(f'{method} {url} failed: {exc}') from exc

    def _auth_headers(self) -> dict[str, str]:
        if not self.username:
            raise RegistryPushError('MODEL_REGISTRY_USER / MODEL_REGISTRY_PASSWORD not configured')
        challenge = _parse_bearer_challenge(self._request('GET', f'{self.api_base}/v2/').headers.get('WWW-Authenticate', ''))
        realm = challenge.get('realm')
        if not realm:
            # 无 Bearer challenge 的仓库（basic auth）：直接带 Basic 头
            basic = base64.b64encode(f'{self.username}:{self.password}'.encode()).decode()
            return {'Authorization': f'Basic {basic}'}
        response = self._request(
            'GET',
            realm,
            params={
                'service': challenge.get('service', ''),
                'scope': f'repository:{self.repository}:pull,push',
            },
            auth=(self.username, self.password),
        )
        if response.status_code != 200:
            raise RegistryPushError(f'auth failed: HTTP {response.status_code} {response.text[:200]}')
        try:
            payload = response.json()
        except ValueError as exc:
            raise RegistryPushError('auth response is not JSON') from exc
        token = payload.get('token') or payload.get('access_token')
        if not token:
            raise RegistryPushError('auth response missing token')
        return {'Authorization': f'Bearer {token}'}

    def _upload_blob(self, data: bytes, digest: str, headers: dict[str, str]) -> None:
        response = self._request(
            'POST', f'{self.api_base}/v2/{self.repository}/blobs/uploads/', headers=headers
        )
        if response.status_code not in (201, 202):
            raise RegistryPushError(f'blob upload init failed: HTTP {response.status_code} {response.text[:200]}')
        # 若仓库认为该 blob 已存在，可能直接 201 返回且不带 Location（Registry v2 允许）：
        # 此时用回执头确认「仓库已有这份字节」，确认不了就当作异常
        location = (response.headers.get('Location') or '').strip()
        if not location:
            received = _content_digest(response)
            if received == digest:
                return
            raise RegistryPushError(
                f'blob upload init returned no Location and no matching digest receipt '
                f'(local={digest} registry={received or "<missing>"})'
            )
        if location.startswith('/'):
            location = f'{self.api_base}{location}'
        separator = '&' if '?' in location else '?'
        put_headers = dict(headers)
        put_headers['Content-Type'] = 'application/octet-stream'
        response = self._request(
            'PUT',
            f'{location}{separator}digest={quote(digest, safe=":")}',
            data=data,
            headers=put_headers,
        )
        if response.status_code not in (201, 202):
            raise RegistryPushError(f'blob upload failed ({digest}): HTTP {response.status_code} {response.text[:200]}')
        received = _content_digest(response)
        if received and received != digest:
            raise RegistryPushError(
                f'blob digest mismatch ({digest}): registry={received} local={digest}（仓库内容与本地不一致）'
            )
        if not received:
            raise RegistryPushError(
                f'blob upload receipt missing: repository did not return Docker-Content-Digest for {digest} '
                f'（无法证明仓库收到的字节与本地一致，按 missing_digest_policy={self.missing_digest_policy} 处理）'
            )

    def _verify_by_readback(self, artifacts: PublishArtifacts, *, tag: str, headers: dict[str, str]) -> str:
        """仓库未回回执时的退化校验：PUT 后按 tag GET 回读 manifest，逐字节比对通过才认。

        用调用方已换到的 token（不重复换票）；比对的是**字节**，比「仓库自报 digest」更硬。
        """
        read_headers = dict(headers)
        read_headers['Accept'] = MANIFEST_MEDIA_TYPE
        response = self._request(
            'GET',
            f'{self.api_base}/v2/{self.repository}/manifests/{quote(tag, safe="")}',
            headers=read_headers,
        )
        if response.status_code != 200:
            raise RegistryPushError(
                f'manifest readback failed (tag={tag}): HTTP {response.status_code} {response.text[:200]}'
            )
        if response.content != artifacts.manifest_bytes:
            raise RegistryPushError(
                f'manifest readback mismatch (tag={tag}): registry bytes sha256={_sha256(response.content)} '
                f'local={artifacts.digest}（回读内容与本地不一致）'
            )
        return artifacts.digest

    # ----------------------------------------------------------------------- push
    def push(self, artifacts: PublishArtifacts, *, tag: str) -> str:
        """推送 layer/config/manifest，**返回仓库确认的 digest**（核对不过一律抛错）。"""
        headers = self._auth_headers()
        self._upload_blob(artifacts.layer_bytes, artifacts.layer_digest, headers)
        self._upload_blob(artifacts.config_bytes, artifacts.config_digest, headers)

        manifest_headers = dict(headers)
        manifest_headers['Content-Type'] = MANIFEST_MEDIA_TYPE
        response = self._request(
            'PUT',
            f'{self.api_base}/v2/{self.repository}/manifests/{quote(tag, safe="")}',
            data=artifacts.manifest_bytes,
            headers=manifest_headers,
        )
        if response.status_code not in (200, 201, 202):
            raise RegistryPushError(
                f'manifest push failed (tag={tag}): HTTP {response.status_code} {response.text[:200]}'
            )
        registry_digest = _content_digest(response)
        if registry_digest and registry_digest != artifacts.digest:
            raise RegistryPushError(
                f'digest mismatch: registry={registry_digest} local={artifacts.digest}（仓库内容与本地不一致）'
            )
        if not registry_digest:
            if self.missing_digest_policy == DIGEST_POLICY_READBACK:
                logger.warning(
                    'registry returned no Docker-Content-Digest for %s/%s:%s; falling back to readback verification',
                    self.registry,
                    self.repository,
                    tag,
                )
                return self._verify_by_readback(artifacts, tag=tag, headers=headers)
            raise RegistryPushError(
                f'manifest push receipt missing (tag={tag}): repository did not return '
                f'Docker-Content-Digest（无法证明仓库收到的内容；如需以回读校验兜底，'
                f'请设 missing_digest_policy="{DIGEST_POLICY_READBACK}"）'
            )
        return registry_digest


# --------------------------------------------------------------------------- orchestrate
def _set_status(publish: ModelPublish, status: str) -> None:
    publish.status = status
    publish.save(update_fields=['status'])


def _mark_failed(publish: ModelPublish, message: str) -> None:
    publish.status = ModelPublish.STATUS_FAILED
    publish.error_message = message
    publish.save(update_fields=['status', 'error_message'])


def _push_artifacts(publish: ModelPublish, artifacts: PublishArtifacts, mode: str) -> str:
    """按模式推送：``fake`` 本地取 digest；``registry`` 真推并核对 digest。"""
    if mode != 'registry':
        return artifacts.digest
    client = RegistryPushClient(
        registry=publish.registry,
        repository=_repository_from_image(publish.image),
        username=get_model_registry_user(),
        password=get_model_registry_password(),
        proxy=get_registry_proxy(),
    )
    return client.push(artifacts, tag=publish.tag)


def run_publish(
    publish: ModelPublish,
    *,
    actor_id: int | None = None,
    request_id: str | None = None,
) -> ModelPublish:
    """执行一次发布：构建 → 落盘 → 推送 → 落状态/审计（D7 worker 的调用入口）。

    失败时先把记录置 ``failed`` + ``error_message`` 再抛 ``AoiError``：
    ``PublishBuildError`` → 42200（模型数据问题）；``RegistryPushError`` → 50300（仓库/网络问题）。
    """
    model = Model.objects.filter(version=publish.model_ref).first()
    if model is None:
        raise AoiError(CODE_NOT_FOUND, 'model not found for publish record', fields={'model_ref': publish.model_ref})
    if model.lifecycle != Model.LIFECYCLE_APPROVED:
        raise AoiError(
            CODE_CONFLICT,
            'model must be approved before publishing',
            fields={'lifecycle': model.lifecycle},
        )

    mode = get_publish_mode()
    _set_status(publish, ModelPublish.STATUS_BUILDING)
    try:
        onnx_bytes, doc, yaml_text = build_model_files(model)
        artifacts = build_image_artifacts(onnx_bytes, yaml_text)
    except PublishBuildError as exc:
        _mark_failed(publish, f'build failed: {exc}')
        raise AoiError(CODE_UNPROCESSABLE, 'model build failed', fields={'model.yaml': str(exc)}) from exc

    target_root = resolve_publish_artifacts_dir()
    if target_root is not None:
        try:
            materialize_artifacts(
                artifacts,
                target_root / publish.tag,
                image=publish.image,
                tag=publish.tag,
                model_ref=publish.model_ref,
                mode=mode,
            )
        except OSError as exc:  # 落盘只是留档/手工通道，失败不阻断发布
            logger.warning('materialize publish artifacts failed: %s', exc)

    _set_status(publish, ModelPublish.STATUS_PUSHING)
    try:
        digest = _push_artifacts(publish, artifacts, mode)
    except RegistryPushError as exc:
        _mark_failed(publish, f'push failed: {exc}')
        raise AoiError(
            CODE_UNAVAILABLE,
            'registry push failed',
            fields={'registry': publish.registry, 'image': publish.image, 'tag': publish.tag},
            detail=str(exc),
        ) from exc

    publish.digest = digest
    publish.status = ModelPublish.STATUS_PUBLISHED
    publish.published_at = django_timezone.now()
    publish.error_message = None
    publish.save(update_fields=['digest', 'status', 'published_at', 'error_message'])

    snapshot = dict(model.config_snapshot or {})
    snapshot['model_yaml'] = doc
    model.config_snapshot = snapshot
    model.lifecycle = Model.LIFECYCLE_PUBLISHED
    model.save(update_fields=['config_snapshot', 'lifecycle'])

    write_audit(
        actor_id=actor_id,
        action='model.published',
        object_type='aoi_training.model',
        object_id=str(model.id),
        detail={
            'model_ref': publish.model_ref,
            'image': publish.image,
            'tag': publish.tag,
            'digest': digest,
            'mode': mode,
        },
        request_id=request_id,
    )
    return publish
