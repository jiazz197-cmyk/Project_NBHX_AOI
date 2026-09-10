"""aoi.datasets 端点（契约 §4.1；D1–D2 全量 stub）。

写操作接受 ``Idempotency-Key``（D1–D2 仅记录，不强制）；数据落 ``aoi_datasets`` 表，
未命中/空库时返回同形 stub，保证 D3 验收「stub 全量 200」。
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any

from aoi.common.errors import CODE_CONFLICT, CODE_NOT_FOUND, CODE_UNPROCESSABLE, AoiError
from aoi.common.idempotency import get_idempotency_key
from aoi.common.pagination import paginate
from aoi.common.views import AoiAPIView
from aoi.datasets import label_config
from aoi.datasets.models import Dataset, DatasetVersion, DefectClass, DefectDictVersion, Image
from aoi.datasets.serializers import (
    serialize_dataset,
    serialize_dataset_version,
    serialize_defect,
    serialize_image,
)
from django.db import IntegrityError
from drf_spectacular.utils import extend_schema

# 进程内导入任务占位（D4 起落 Celery 任务表）
_IMPORT_JOBS: dict[str, dict[str, Any]] = {}


def _payload(request) -> dict[str, Any]:
    return request.data if isinstance(request.data, dict) else {}


def _dataset_or_stub(pk: int) -> dict[str, Any]:
    obj = Dataset.objects.filter(pk=pk).first()
    if obj is not None:
        return serialize_dataset(obj)
    return {
        'id': pk,
        'name': f'stub-dataset-{pk}',
        'cur_version': None,
        'ls_project_id': None,
        'created_by': None,
        'stub': True,
    }


# --------------------------------------------------------------------------- import
@extend_schema(tags=['aoi-datasets'])
class ImportCreateView(AoiAPIView):
    """``POST /api/datasets/import`` → ``{job_id}``（包裹 LS 上传，D4 起接真实导入）。"""

    aoi_perm = 'datasets.create'

    def post(self, request):
        get_idempotency_key(request)  # D4: 幂等表 CAS
        # P1：契约 §4.1 的字段名是 files[]；兼容 files/file 两种别名
        files = request.FILES.getlist('files[]') or request.FILES.getlist('files') or request.FILES.getlist('file')
        total = len(files)
        job_id = uuid.uuid4().hex[:12]
        _IMPORT_JOBS[job_id] = {
            # D1–D2 stub：尚未真正导入，用 stub 标记避免被当成已完成
            'status': 'succeeded',
            'stub': True,
            'total': total,
            'ok': total,
            'dup': 0,
            'bad': 0,
            'bad_items': [],
            'source': request.data.get('source'),
            'station_code': request.data.get('station_code'),
        }
        return self.ok({'job_id': job_id}, message='import accepted')


@extend_schema(tags=['aoi-datasets'])
class ImportDetailView(AoiAPIView):
    """``GET /api/datasets/import/{job_id}``。"""

    aoi_perm = 'datasets.view'

    def get(self, request, job_id: str):
        job = _IMPORT_JOBS.get(job_id)
        if job is None:
            # D1–D2 stub：未知 job 明确标记，不再伪装成"已完成"
            return self.ok({'status': 'unknown', 'stub': True, 'job_id': job_id})
        return self.ok(job)


# ---------------------------------------------------------------------------- images
@extend_schema(tags=['aoi-datasets'])
class ImageListView(AoiAPIView):
    """``GET /api/datasets/images``（筛选/分页）。"""

    aoi_perm = 'datasets.view'

    def get(self, request):
        qs = Image.objects.all().order_by('id')
        source = request.query_params.get('source')
        station_code = request.query_params.get('station_code')
        if source:
            qs = qs.filter(source=source)
        if station_code:
            qs = qs.filter(station_code=station_code)
        items = [serialize_image(obj) for obj in qs]
        return self.ok(paginate(request, items))


@extend_schema(tags=['aoi-datasets'])
class ImageDownloadView(AoiAPIView):
    """``GET /api/datasets/images/{id}/download`` → 预签名 URL（D4 接 MinIO）。"""

    aoi_perm = 'datasets.view'

    def get(self, request, id: int):
        obj = Image.objects.filter(pk=id).first()
        object_key = obj.object_key if obj is not None else f'images/stub-{id}.jpg'
        return self.ok(
            {
                'id': id,
                'object_key': object_key,
                'url': f'/data/{object_key}',
                'expires_in': 3600,
            }
        )


# --------------------------------------------------------------------------- defects
def _defect_payload(obj: DefectClass) -> dict[str, Any]:
    return serialize_defect(obj)


def _validate_defect_payload(payload: dict[str, Any]) -> dict[str, Any]:
    from skillname import is_valid_fault_code

    fields: dict[str, str] = {}
    code = payload.get('code')
    if not is_valid_fault_code(code):
        fields['code'] = f'invalid fault code: {code!r}'
    name_cn = payload.get('name_cn')
    if not name_cn:
        fields['name_cn'] = 'required'
    elif not isinstance(name_cn, str) or len(name_cn) > 64:
        fields['name_cn'] = 'must be a string <= 64 chars'
    # P1：risk_level 必填（它决定 model.yaml 的 recommended 阈值，静默按 1/低 处理会改变门禁口径）
    if 'risk_level' not in payload:
        fields['risk_level'] = 'required (1=low, 2=medium, 3=high)'
    risk_level = payload.get('risk_level')
    if isinstance(risk_level, bool) or risk_level not in (1, 2, 3):
        fields['risk_level'] = 'must be 1/2/3'
    aliases = payload.get('aliases')
    if aliases is not None and (not isinstance(aliases, list) or any(not isinstance(alias, str) for alias in aliases)):
        fields['aliases'] = 'must be a list of strings'
    if fields:
        raise AoiError(CODE_UNPROCESSABLE, 'invalid defect', fields=fields)
    return {'code': code, 'name_cn': str(name_cn), 'risk_level': int(risk_level), 'aliases': aliases or []}


@extend_schema(tags=['aoi-datasets'])
class DefectListCreateUpdateView(AoiAPIView):
    """``GET/POST/PUT /api/datasets/defects``（契约 §4.1）。"""

    aoi_perm = 'datasets.view'
    aoi_perm_by_method = {'POST': 'datasets.update', 'PUT': 'datasets.update'}

    def get(self, request):
        qs = DefectClass.objects.all().order_by('code')
        active = request.query_params.get('active')
        if active is not None:
            qs = qs.filter(active=str(active).lower() in {'1', 'true', 'yes'})
        return self.ok(paginate(request, [_defect_payload(obj) for obj in qs]))

    def post(self, request):
        get_idempotency_key(request)
        payload = _payload(request)
        data = _validate_defect_payload(payload)
        try:
            obj = DefectClass.objects.create(
                code=data['code'],
                name_cn=data['name_cn'],
                risk_level=data['risk_level'],
                aliases=payload.get('aliases') or [],
                active=bool(payload.get('active', True)),
            )
        except IntegrityError as exc:
            raise AoiError(CODE_CONFLICT, 'defect code already exists') from exc
        return self.ok(_defect_payload(obj))

    def put(self, request):
        get_idempotency_key(request)
        payload = _payload(request)
        code = payload.get('code')
        obj = DefectClass.objects.filter(code=code).first()
        if obj is None:
            raise AoiError(CODE_NOT_FOUND, f'defect not found: {code!r}')
        data = _validate_defect_payload(payload)
        obj.name_cn = data['name_cn']
        obj.risk_level = data['risk_level']
        if 'aliases' in payload:
            obj.aliases = payload.get('aliases') or []
        if 'active' in payload:
            obj.active = bool(payload.get('active'))
        obj.save()
        return self.ok(_defect_payload(obj))


@extend_schema(tags=['aoi-datasets'])
class DefectPublishView(AoiAPIView):
    """``POST /api/datasets/defects/publish`` → 渲染 label config + 版本快照（T2.2）。"""

    aoi_perm = 'datasets.publish'

    def post(self, request):
        get_idempotency_key(request)
        payload = _payload(request)
        defects = payload.get('defects')
        if defects is None:
            defects = [
                {'code': obj.code, 'name_cn': obj.name_cn, 'risk_level': obj.risk_level}
                for obj in DefectClass.objects.filter(active=True).order_by('code')
            ]
        label_config_xml = label_config.render_label_config(defects)
        snapshot = label_config.snapshot_from_defects(defects)

        today = datetime.now(timezone.utc).strftime('%Y%m%d')
        prefix = f'{today}-'
        existing = DefectDictVersion.objects.filter(version__startswith=prefix).count()
        version = f'{prefix}{existing + 1}'
        obj = DefectDictVersion.objects.create(
            version=version,
            snapshot=snapshot,
            published_by=self.user_id,
            published_at=datetime.now(timezone.utc),
        )
        from aoi.common.audit import write_audit

        write_audit(
            actor_id=self.user_id,
            action='defects.publish',
            object_type='defect_dict_version',
            object_id=str(obj.pk),
            detail={'version': version},
            request_id=self.request_id,
        )
        return self.ok({'version': version, 'label_config': label_config_xml})


# -------------------------------------------------------------------------- datasets
@extend_schema(tags=['aoi-datasets'])
class DatasetListCreateView(AoiAPIView):
    """``GET/POST /api/datasets``（T2.9 裁定路径）。"""

    aoi_perm = 'datasets.view'
    aoi_perm_by_method = {'POST': 'datasets.create'}

    def get(self, request):
        items = [serialize_dataset(obj) for obj in Dataset.objects.all().order_by('id')]
        return self.ok(paginate(request, items))

    def post(self, request):
        get_idempotency_key(request)
        payload = _payload(request)
        cur_version = payload.get('cur_version')
        if cur_version is not None and not isinstance(cur_version, str):
            raise AoiError(CODE_UNPROCESSABLE, 'invalid cur_version', fields={'cur_version': 'must be a string'})
        ls_project_id = payload.get('ls_project_id')
        if ls_project_id is not None and (isinstance(ls_project_id, bool) or not isinstance(ls_project_id, int)):
            raise AoiError(CODE_UNPROCESSABLE, 'invalid ls_project_id', fields={'ls_project_id': 'must be an int'})
        obj = Dataset.objects.create(
            name=str(payload.get('name') or '') or None,
            cur_version=cur_version,
            ls_project_id=ls_project_id,
            created_by=self.user_id,
        )
        return self.ok(serialize_dataset(obj))


@extend_schema(tags=['aoi-datasets'])
class DatasetDetailView(AoiAPIView):
    """``GET/PUT/DELETE /api/datasets/{id}``（T2.9 裁定路径；stub 未命中返回占位对象）。"""

    aoi_perm = 'datasets.view'
    aoi_perm_by_method = {'PUT': 'datasets.update', 'DELETE': 'datasets.update'}

    _EDITABLE = ('name', 'cur_version', 'ls_project_id')

    def get(self, request, id: int):
        return self.ok(_dataset_or_stub(id))

    def put(self, request, id: int):
        get_idempotency_key(request)
        payload = _payload(request)
        fields: dict[str, str] = {}
        if 'cur_version' in payload and not isinstance(payload.get('cur_version'), str):
            fields['cur_version'] = 'must be a string'
        ls_project_id = payload.get('ls_project_id')
        if 'ls_project_id' in payload and (isinstance(ls_project_id, bool) or not isinstance(ls_project_id, int)):
            fields['ls_project_id'] = 'must be an int'
        if fields:
            raise AoiError(CODE_UNPROCESSABLE, 'invalid dataset payload', fields=fields)
        obj = Dataset.objects.filter(pk=id).first()
        if obj is None:
            # D1–D2 stub：未命中返回可写占位（40401 语义进 D3 工程卫生清单）
            data = _dataset_or_stub(id)
            data.update({key: payload.get(key) for key in self._EDITABLE if key in payload})
            return self.ok(data)
        for key in self._EDITABLE:
            if key in payload:
                setattr(obj, key, payload.get(key))
        obj.save()
        return self.ok(serialize_dataset(obj))

    def delete(self, request, id: int):
        obj = Dataset.objects.filter(pk=id).first()
        if obj is not None:
            obj.delete()
        return self.ok({'id': id, 'deleted': True, 'stub': obj is None})


@extend_schema(tags=['aoi-datasets'])
class DatasetVersionCreateView(AoiAPIView):
    """``POST /api/datasets/{id}/versions``（发布触发划分 + 测试集红线，D4 实现）。

    P1：``status``/``phase`` 由服务端控制，创建时一律 ``draft``；客户端传入其它取值 → 42200，
    防止绕过"全部 workitem finalized + 人工确认 + 系统校验"的落版门禁（设计 §9 #9）。
    """

    aoi_perm = 'datasets.update'

    def post(self, request, id: int):
        get_idempotency_key(request)
        payload = _payload(request)
        fields: dict[str, str] = {}
        status_value = payload.get('status')
        if status_value not in (None, '', DatasetVersion.STATUS_DRAFT):
            fields['status'] = 'server-controlled; new versions always start as draft'
        phase_value = payload.get('phase')
        if phase_value not in (None, '', DatasetVersion.PHASE_DRAFT):
            fields['phase'] = 'server-controlled; new versions always start as draft'
        if fields:
            raise AoiError(CODE_UNPROCESSABLE, 'invalid dataset version payload', fields=fields)
        version = str(payload.get('version') or '')
        if not version:
            count = DatasetVersion.objects.filter(dataset_id=id).count()
            version = f'1.0.{count}'
        if len(version) > 16:
            raise AoiError(CODE_UNPROCESSABLE, 'invalid version', fields={'version': 'must be <=16 chars'})
        split_seed = payload.get('split_seed')
        if split_seed is not None and (isinstance(split_seed, bool) or not isinstance(split_seed, int)):
            raise AoiError(CODE_UNPROCESSABLE, 'invalid split_seed', fields={'split_seed': 'must be an int'})
        try:
            obj = DatasetVersion.objects.create(
                dataset_id=id,
                version=version,
                status=DatasetVersion.STATUS_DRAFT,
                phase=DatasetVersion.PHASE_DRAFT,
                split_seed=split_seed,
                split_stats=payload.get('split_stats'),
                class_dist=payload.get('class_dist'),
                source_stats=payload.get('source_stats'),
                dict_version=payload.get('dict_version'),
                note=payload.get('note'),
                created_by=self.user_id,
            )
        except IntegrityError as exc:
            raise AoiError(CODE_CONFLICT, 'dataset version already exists') from exc
        return self.ok(serialize_dataset_version(obj))


@extend_schema(tags=['aoi-datasets'])
class DatasetExportView(AoiAPIView):
    """``GET /api/datasets/{id}/versions/{v}/export``（复用 LS data_export YOLO，D4 实现）。

    D2 实测：LS 1.24 YOLO zip 为 ``images/ + labels/ + classes.txt + notes.json``，
    **无 data.yaml**；``classes.txt`` 行序即 label config / 字典快照顺序。
    Ultralytics ``data.yaml`` 由训练包裹（D9）在训练时按需生成，不作为导出产物。
    """

    aoi_perm = 'datasets.export'

    def get(self, request, id: int, v: str):
        return self.ok(
            {
                'dataset_id': id,
                'version': v,
                'format': 'yolo',
                'status': 'ready',
                'url': f'/data/datasets/exports/{id}_{v}.zip',
                'expires_in': 3600,
                # T2.7 实测 & 契约 §9 修正（D2）：names 顺序以 classes.txt 为准
                'classes_source': 'classes.txt',
                'data_yaml': None,
                'stub': True,
            }
        )


@extend_schema(tags=['aoi-datasets'])
class AnnotationStatsView(AoiAPIView):
    """``GET /api/datasets/annotation-stats``（LS 标注/审核状态只读投影，D4 实现）。"""

    aoi_perm = 'datasets.view'

    def get(self, request):
        return self.ok(
            {
                'total': 0,
                'annotated': 0,
                'reviewed': 0,
                'approved': 0,
                'by_status': {},
                'stub': True,
            }
        )
