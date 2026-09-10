"""B→A 错图回传：``POST /api/ingest/findings``（契约 §4.6 / 跨平台契约 §3；T1.5 + T2.1）。

- 鉴权：``X-Internal-Token`` 缺失/错误/未配置统一 40100（**fail closed**，不回落默认凭据）；
- 幂等键 ``(station_code, seq)``，按 ``kind`` 落不同表；命中返回既有 id + ``duplicated=true``；
  同键内容不一致 → 40900；
- **事务**：每个分支的 image/fact/workitem（或 image/bad_image）在同一 ``transaction.atomic()`` 内写入；
  并发重复请求撞唯一约束时按幂等返回；``fact`` 已落库但 ``workitem`` 缺失时**补建**（P0 修复）；
- ``suspicious`` 必须带可解码图片（否则 40010），``verdict ∈ {recheck, manual}``（``auto_pass`` 不回传）；
- ``bad`` 无图仍成功；单图超过 ``MAX_INGEST_BYTES`` → 40010（不读入内存）。
"""

from __future__ import annotations

import hashlib
import json
import logging
from datetime import datetime, timezone
from typing import Any

from aoi.common.errors import (
    CODE_BAD_REQUEST,
    CODE_CONFLICT,
    CODE_UNPROCESSABLE,
    AoiError,
)
from aoi.common.settings import internal_token_matches
from aoi.common.views import AoiAPIView
from aoi.datasets.models import Image
from aoi.review.models import BadImage, InspectionFact, ReviewWorkitem
from django.contrib.auth.models import AnonymousUser
from django.db import IntegrityError, transaction
from django.utils.dateparse import parse_datetime
from drf_spectacular.utils import extend_schema
from rest_framework.authentication import BaseAuthentication
from rest_framework.exceptions import AuthenticationFailed
from rest_framework.permissions import AllowAny

logger = logging.getLogger(__name__)

KINDS = {'suspicious', 'bad'}
#: 跨平台契约 §1.1：单条回传图片 ≤ 100MB；超出直接拒绝，不读入内存
MAX_INGEST_BYTES = 100 * 1024 * 1024
#: 跨平台契约 §3.1：``auto_pass`` 只存在于 A 侧三桶，不回传
INGEST_VERDICTS = {'recheck', 'manual'}
#: 跨平台契约 §3.2 坏图错误枚举
INGEST_ERROR_CODES = {'capture_failed', 'decode_failed', 'timeout', 'model_error', 'disk_error'}
_FP_PREFIX = '__ingest_fp__:'
_FP_FIELDS = (
    'kind',
    'instance_code',
    'station_code',
    'station_name',
    'seq',
    'channel_id',
    'captured_at',
    'template_version',
    'model_refs',
    'verdict',
    'verdict_reasons',
    'boxes',
    'tiling_meta',
    'latency_ms',
    'image',
    'error_code',
)
_STR_LIMITS = {'instance_code': 32, 'station_name': 64}
_INT_FIELDS = ('channel_id', 'template_version', 'latency_ms')
_IMAGE_INT_FIELDS = ('width', 'height', 'size_bytes')


class InternalTokenAuthentication(BaseAuthentication):
    """``X-Internal-Token`` 校验（缺失/错误/未配置 → 40100，fail closed）。"""

    def authenticate(self, request):
        if not internal_token_matches(request.headers.get('X-Internal-Token')):
            raise AuthenticationFailed('invalid or missing X-Internal-Token')
        return (AnonymousUser(), None)


def _parse_meta(request) -> dict[str, Any]:
    raw = request.data.get('meta') if hasattr(request.data, 'get') else None
    if isinstance(raw, str):
        try:
            raw = json.loads(raw)
        except (TypeError, ValueError) as exc:
            raise AoiError(CODE_UNPROCESSABLE, 'meta must be valid JSON', fields={'meta': 'invalid JSON'}) from exc
    if raw is None and isinstance(request.data, dict):
        # application/json 直接以 meta 字段形式提交
        raw = request.data
    if not isinstance(raw, dict):
        raise AoiError(CODE_UNPROCESSABLE, 'meta is required', fields={'meta': 'required'})
    return raw


def _is_bad_int(value: Any) -> bool:
    return isinstance(value, bool) or not isinstance(value, int)


def _validate_meta(meta: dict[str, Any]) -> None:
    """完整元数据校验（契约 §3.4 / 跨平台契约 §3.2）：类型/枚举/长度不符 → 42200 + ``detail.fields``。"""
    fields: dict[str, str] = {}

    kind = meta.get('kind')
    if kind not in KINDS:
        fields['kind'] = f'must be one of {sorted(KINDS)}'

    station_code = meta.get('station_code')
    if not station_code or not isinstance(station_code, str) or len(station_code) > 32:
        fields['station_code'] = 'required, non-empty, <=32 chars'

    seq = meta.get('seq')
    if _is_bad_int(seq) or seq < 0:
        fields['seq'] = 'required int >= 0'

    for key, limit in _STR_LIMITS.items():
        value = meta.get(key)
        if value is not None and (not isinstance(value, str) or len(value) > limit):
            fields[key] = f'must be a string <= {limit} chars'

    for key in _INT_FIELDS:
        value = meta.get(key)
        if value is not None and (_is_bad_int(value) or value < 0):
            fields[key] = 'must be an int >= 0'

    for key in ('captured_at', 'received_at'):
        value = meta.get(key)
        if value is not None and _parse_dt(value) is None:
            fields[key] = 'must be an ISO-8601 datetime'

    image_meta = meta.get('image')
    if image_meta is not None and not isinstance(image_meta, dict):
        fields['image'] = 'must be an object'
    elif isinstance(image_meta, dict):
        for key in _IMAGE_INT_FIELDS:
            value = image_meta.get(key)
            if value is not None and (_is_bad_int(value) or value < 0):
                fields[f'image.{key}'] = 'must be a non-negative int'

    if kind == 'suspicious':
        verdict = meta.get('verdict')
        if verdict not in INGEST_VERDICTS:
            fields['verdict'] = f'must be one of {sorted(INGEST_VERDICTS)} (auto_pass is never reported back)'
        for key in ('verdict_reasons', 'boxes', 'model_refs'):
            value = meta.get(key)
            if value is not None and not isinstance(value, list):
                fields[key] = 'must be a list'
        tiling_meta = meta.get('tiling_meta')
        if tiling_meta is not None and not isinstance(tiling_meta, dict):
            fields['tiling_meta'] = 'must be an object'
    elif kind == 'bad':
        error_code = meta.get('error_code')
        if error_code is not None and error_code not in INGEST_ERROR_CODES:
            fields['error_code'] = f'must be one of {sorted(INGEST_ERROR_CODES)}'

    if fields:
        raise AoiError(CODE_UNPROCESSABLE, 'invalid meta', fields=fields)


def _fingerprint(meta: dict[str, Any]) -> str:
    payload = {key: meta.get(key) for key in _FP_FIELDS}
    canonical = json.dumps(payload, sort_keys=True, ensure_ascii=False, default=str, separators=(',', ':'))
    return hashlib.sha256(canonical.encode('utf-8')).hexdigest()


def _parse_dt(value: Any) -> datetime | None:
    if not value:
        return None
    if isinstance(value, datetime):
        return value
    parsed = parse_datetime(str(value))
    if parsed is not None and parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed


def _decode_size(data: bytes) -> tuple[int | None, int | None]:
    try:
        from io import BytesIO

        from PIL import Image as PILImage

        with PILImage.open(BytesIO(data)) as img:
            return img.width, img.height
    except Exception:  # pragma: no cover - 依赖缺失/解码失败
        return None, None


def _store_image(file_obj, meta: dict[str, Any], *, required: bool) -> Image | None:
    """落 ``aoi_datasets.image``；D1–D2 stub 不实际写 MinIO（D4 起补上传）。"""
    if file_obj is None:
        if required:
            raise AoiError(CODE_UNPROCESSABLE, 'file is required for kind=suspicious', fields={'file': 'required'})
        return None

    declared_size = getattr(file_obj, 'size', None)
    if declared_size is not None and declared_size > MAX_INGEST_BYTES:
        raise AoiError(CODE_BAD_REQUEST, 'image too large', fields={'file': f'max {MAX_INGEST_BYTES} bytes'})

    data = file_obj.read()
    if len(data) > MAX_INGEST_BYTES:
        raise AoiError(CODE_BAD_REQUEST, 'image too large', fields={'file': f'max {MAX_INGEST_BYTES} bytes'})

    md5 = hashlib.md5(data).hexdigest()
    width, height = _decode_size(data)
    if required and width is None:
        raise AoiError(CODE_BAD_REQUEST, 'image decode failed', fields={'file': 'decode_failed'})

    image_meta = meta.get('image') or {}
    object_key = f'images/{md5}.jpg'
    defaults = {
        'md5': md5,
        'source': 'camera',
        'station_code': meta.get('station_code'),
        'seq': meta.get('seq'),
        'captured_at': _parse_dt(meta.get('captured_at')),
        'width': width or image_meta.get('width'),
        'height': height or image_meta.get('height'),
        'size_bytes': len(data),
        'qc_status': 'ok' if width is not None else 'rejected',
        'qc_reason': None if width is not None else 'decode_failed',
        'status': 'active',
        'trace_id': meta.get('instance_code'),
    }
    image, _created = Image.objects.get_or_create(object_key=object_key, defaults=defaults)
    # TODO(D4): 上传 MinIO images/{md5}.jpg；当前仅登记元数据
    return image


def _ensure_workitem(fact: InspectionFact) -> ReviewWorkitem:
    """``fact`` 对应的 ingest 复审项：不存在则补建（半写/崩溃后的自愈路径）。"""
    workitem = (
        ReviewWorkitem.objects.filter(fact_id=fact.id, source=ReviewWorkitem.SOURCE_INGEST).order_by('id').first()
    )
    if workitem is not None:
        return workitem
    verdict = fact.verdict
    return ReviewWorkitem.objects.create(
        fact_id=fact.id,
        source=ReviewWorkitem.SOURCE_INGEST,
        verdict=verdict,
        bucket=ReviewWorkitem.bucket_for_verdict(verdict),
        forced=verdict == 'manual',
        route='manual',  # MVP: vlm stub 转 manual（契约 §10）
        status='pending',
    )


@extend_schema(tags=['aoi-ingest'])
class IngestFindingsView(AoiAPIView):
    """``POST /api/ingest/findings``（multipart ``meta`` + 可选 ``file``）。"""

    authentication_classes = [InternalTokenAuthentication]
    permission_classes = [AllowAny]

    def post(self, request):
        meta = _parse_meta(request)
        _validate_meta(meta)
        kind = meta['kind']
        fingerprint = _fingerprint(meta)

        if kind == 'suspicious':
            existing = InspectionFact.objects.filter(station_code=meta['station_code'], seq=meta['seq']).first()
            if existing is not None:
                return self._duplicated_suspicious(existing, fingerprint)
            try:
                with transaction.atomic():
                    image = _store_image(request.FILES.get('file'), meta, required=True)
                    fact = self._create_fact(meta, image, fingerprint)
                    workitem = _ensure_workitem(fact)
            except IntegrityError:
                # 并发重复请求：唯一约束兜底，按幂等返回既有资源
                existing = InspectionFact.objects.filter(station_code=meta['station_code'], seq=meta['seq']).first()
                if existing is None:
                    raise
                return self._duplicated_suspicious(existing, fingerprint)
            return self.ok(
                {
                    'fact_id': fact.id,
                    'workitem_id': workitem.id,
                    'image_id': image.id if image is not None else None,
                    'bad_image_id': None,
                    'duplicated': False,
                }
            )

        existing = BadImage.objects.filter(station_code=meta['station_code'], seq=meta['seq']).first()
        if existing is not None:
            return self._duplicated_bad(existing, meta, fingerprint)
        try:
            with transaction.atomic():
                image = _store_image(request.FILES.get('file'), meta, required=False)
                bad = BadImage.objects.create(
                    station_code=meta['station_code'],
                    station_name=meta.get('station_name'),
                    seq=meta['seq'],
                    captured_at=_parse_dt(meta.get('captured_at')),
                    error_code=meta.get('error_code'),
                    image_key=image.object_key if image is not None else None,
                    instance_code=meta.get('instance_code'),
                    handled=False,
                    note=f'{_FP_PREFIX}{fingerprint}',
                )
        except IntegrityError:
            existing = BadImage.objects.filter(station_code=meta['station_code'], seq=meta['seq']).first()
            if existing is None:
                raise
            return self._duplicated_bad(existing, meta, fingerprint)
        return self.ok(
            {
                'fact_id': None,
                'workitem_id': None,
                'image_id': image.id if image is not None else None,
                'bad_image_id': bad.id,
                'duplicated': False,
            }
        )

    # ----------------------------------------------------------------- helpers
    def _create_fact(self, meta: dict[str, Any], image: Image | None, fingerprint: str) -> InspectionFact:
        result_json = {
            'boxes': meta.get('boxes') or [],
            'verdict': meta.get('verdict'),
            'verdict_reasons': meta.get('verdict_reasons') or [],
            'tiling_meta': meta.get('tiling_meta') or {},
            'model_refs': meta.get('model_refs') or [],
            'instance_code': meta.get('instance_code'),
            'template_version': meta.get('template_version'),
            'versions': meta.get('versions'),
            '_ingest_fp': fingerprint,
        }
        return InspectionFact.objects.create(
            image_id=image.id if image is not None else None,
            station_code=meta['station_code'],
            station_name=meta.get('station_name'),
            seq=meta.get('seq'),
            channel_id=meta.get('channel_id'),
            template_version=meta.get('template_version'),
            result_json=result_json,
            verdict=meta.get('verdict'),
            instance_code=meta.get('instance_code'),
            latency_ms=meta.get('latency_ms'),
            status='initial',
            captured_at=_parse_dt(meta.get('captured_at')),
            received_at=_parse_dt(meta.get('received_at')) or datetime.now(timezone.utc),
        )

    def _duplicated_suspicious(self, fact: InspectionFact, fingerprint: str):
        stored = (fact.result_json or {}).get('_ingest_fp')
        if stored != fingerprint:
            raise AoiError(CODE_CONFLICT, 'idempotency conflict: same (station_code, seq) with different content')
        # P0 修复：fact 已存在但 workitem 缺失（历史半写/崩溃）→ 补建后再返回
        workitem = _ensure_workitem(fact)
        return self.ok(
            {
                'fact_id': fact.id,
                'workitem_id': workitem.id,
                'image_id': fact.image_id,
                'bad_image_id': None,
                'duplicated': True,
            }
        )

    def _duplicated_bad(self, bad: BadImage, meta: dict[str, Any], fingerprint: str):
        stored = None
        if bad.note and bad.note.startswith(_FP_PREFIX):
            stored = bad.note[len(_FP_PREFIX) :]
        if stored != fingerprint:
            raise AoiError(CODE_CONFLICT, 'idempotency conflict: same (station_code, seq) with different content')
        return self.ok(
            {
                'fact_id': None,
                'workitem_id': None,
                'image_id': None,
                'bad_image_id': bad.id,
                'duplicated': True,
            }
        )
