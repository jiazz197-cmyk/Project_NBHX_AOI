"""aoi.datasets 端点（契约 §4.1）。

D5：导入包裹真实化（复用 LS 上传 + Celery ``default`` 队列异步，契约 §5.2）、
标注项目创建自 D6 提前（``POST /api/datasets`` 服务端按 ``ls_project.py`` 模板创建 LS 项目）。
写操作接受 ``Idempotency-Key``（记录，不强制）。
"""

from __future__ import annotations

import logging
import os
import uuid
from datetime import datetime, timezone
from typing import Any

from aoi.common.audit import write_audit
from aoi.common.errors import CODE_CONFLICT, CODE_NOT_FOUND, CODE_UNAVAILABLE, CODE_UNPROCESSABLE, AoiError
from aoi.common.idempotency import get_idempotency_key
from aoi.common.pagination import paginate
from aoi.common.views import AoiAPIView
from aoi.datasets import label_config
from aoi.datasets.models import Dataset, DatasetVersion, DefectClass, DefectDictVersion, Image, ImportJob
from aoi.datasets.serializers import (
    serialize_dataset,
    serialize_dataset_version,
    serialize_defect,
    serialize_defect_version,
    serialize_image,
    serialize_import_job,
)
from django.db import IntegrityError
from django.db.models import Q
from drf_spectacular.utils import extend_schema

logger = logging.getLogger(__name__)


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
        'versions': [],
        'stub': True,
    }


# --------------------------------------------------------------------- delete helpers
def _delete_ls_tasks_by_object_keys(object_keys: list[str]) -> int:
    """按 ``data.image`` 删除 LS 任务（D5 图片/数据集删除共用）。

    镜像上游 Data Manager ``delete_tasks`` 动作路径：删前 ``summary.remove_created_annotations_and_labels``
    + ``remove_data_columns``，批量删任务（关信号），删后 ``update_tasks_states`` 重算计数。
    返回删除任务数。
    """
    if not object_keys:
        return 0
    from data_manager.actions.basic import async_project_summary_recalculation
    from projects.models import Project
    from tasks.models import Task

    deleted = 0
    affected: dict[int, list[int]] = {}
    for key in object_keys:
        # 任务 data.image 有两态：旧任务=裸对象键，新任务=/data/upload/... 同源 URL（D5 收尾修正），
        # 按「精确匹配 + 后缀匹配」两种形式找，兼容存量数据
        task_ids = list(
            Task.objects.filter(Q(data__image=key) | Q(data__image__endswith=f'/{key}')).values_list('id', flat=True)
        )
        if not task_ids:
            continue
        deleted += len(task_ids)
        for project_id in Task.objects.filter(pk__in=task_ids).values_list('project_id', flat=True).distinct():
            if project_id is not None:
                affected.setdefault(project_id, []).extend(task_ids)

    for project_id, task_ids in affected.items():
        project = Project.objects.filter(pk=project_id).first()
        if project is None:
            continue
        async_project_summary_recalculation(task_ids, project_id)
        project.update_tasks_states(
            maximum_annotations_changed=False,
            overlap_cohort_percentage_changed=False,
            tasks_number_changed=True,
        )
    return deleted


def _delete_file_uploads(queryset) -> int:
    """删除 ``FileUpload`` 行并清掉存储字节（MinIO/本地）；存储异常仅告警不阻断 DB 清理。"""
    deleted = 0
    for file_upload in queryset:
        try:
            file_upload.file.delete(save=False)
        except Exception:  # noqa: BLE001 — 字节清理失败不应卡住登记删除
            logger.warning('failed to delete storage file %s', file_upload.file.name, exc_info=True)
        file_upload.delete()
        deleted += 1
    return deleted


def _delete_images(images) -> dict[str, int]:
    """删除图片登记及其衍生数据：LS 任务、存储字节（FileUpload）、版本明细（dataset_item）。"""
    from aoi.datasets.models import DatasetItem
    from data_import.models import FileUpload

    images = list(images)
    object_keys = [image.object_key for image in images]
    tasks_deleted = _delete_ls_tasks_by_object_keys(object_keys)
    for image in images:
        DatasetItem.objects.filter(image_id=image.id).delete()
        _delete_file_uploads(FileUpload.objects.filter(file=image.object_key))
    for image in images:
        image.delete()
    return {'tasks_deleted': tasks_deleted, 'images_deleted': len(images)}


# --------------------------------------------------------------------------- import
#: A 导入允许的图片扩展名（契约 §4.1；B 回传链路不受此限制）
_IMPORT_EXTENSIONS = {'.jpg', '.jpeg', '.png', '.bmp'}
#: 单文件大小上限（与计划口径一致：100MB）
_IMPORT_MAX_FILE_SIZE = 100 * 1024 * 1024
#: source 白名单（`manual_real` 为 A 前端人工导入；camera/reflux_review 归 B/预标链路）
_IMPORT_SOURCES = {'manual_real'}


def _import_source_or_error(payload: dict[str, Any]) -> str | None:
    source = payload.get('source')
    if source in (None, ''):
        return None
    if not isinstance(source, str) or source not in _IMPORT_SOURCES:
        raise AoiError(
            CODE_UNPROCESSABLE,
            'invalid source',
            fields={'source': f'must be one of {sorted(_IMPORT_SOURCES)}'},
        )
    return source


def _import_station_or_error(payload: dict[str, Any]) -> str | None:
    station_code = payload.get('station_code')
    if station_code in (None, ''):
        return None
    if not isinstance(station_code, str) or len(station_code) > 32:
        raise AoiError(
            CODE_UNPROCESSABLE, 'invalid station_code', fields={'station_code': 'must be a string <= 32 chars'}
        )
    return station_code


@extend_schema(tags=['aoi-datasets'])
class ImportCreateView(AoiAPIView):
    """``POST /api/datasets/import`` → ``{job_id}``（D5：复用 LS 上传 + Celery 异步）。

    流程：预检（扩展名/大小，坏文件记 ``bad_items`` 不上传，部分成功语义）→ 合法文件
    ``data_import.uploader.create_file_upload`` 入 LS 存储 → 落 ``aoi_datasets.import_job``
    （queued）→ ``process_import_job.delay``；broker 不可用 → ``50300``（job 留 queued，
    已上传的 FileUpload 字节保留为已知孤儿行为）。
    """

    aoi_perm = 'datasets.create'

    def post(self, request):
        get_idempotency_key(request)  # D4: 幂等表 CAS
        payload = _payload(request)
        source = _import_source_or_error(payload)
        station_code = _import_station_or_error(payload)

        dataset_id = payload.get('dataset_id')
        # multipart 表单里所有字段都是字符串（前端 FormData 场景），接受数字字符串
        if isinstance(dataset_id, str) and dataset_id.isdigit():
            dataset_id = int(dataset_id)
        if isinstance(dataset_id, bool) or not isinstance(dataset_id, int):
            raise AoiError(CODE_UNPROCESSABLE, 'invalid dataset_id', fields={'dataset_id': 'required (int)'})
        dataset = Dataset.objects.filter(pk=dataset_id).first()
        if dataset is None:
            raise AoiError(CODE_NOT_FOUND, f'dataset not found: {dataset_id}')
        # D5：导入必须带 dataset_id 且其 LS 项目已存在（标注项目创建自 D6 提前后必然成立）
        if not dataset.ls_project_id:
            raise AoiError(
                CODE_UNPROCESSABLE,
                'dataset has no LS project',
                fields={'dataset_id': 'create the dataset first (server creates the LS project)'},
            )
        from projects.models import Project

        project = Project.objects.filter(pk=dataset.ls_project_id).first()
        if project is None:
            raise AoiError(
                CODE_UNPROCESSABLE,
                'LS project not found for dataset',
                fields={'dataset_id': f'ls_project_id {dataset.ls_project_id} does not exist'},
            )

        # P1：契约 §4.1 的字段名是 files[]；兼容 files/file 两种别名
        files = request.FILES.getlist('files[]') or request.FILES.getlist('files') or request.FILES.getlist('file')
        if not files:
            raise AoiError(CODE_UNPROCESSABLE, 'no files to import', fields={'files[]': 'required'})

        total = len(files)
        bad_items: list[dict[str, str]] = []
        accepted: list = []
        for item in files:
            _, ext = os.path.splitext(item.name or '')
            if ext.lower() not in _IMPORT_EXTENSIONS:
                bad_items.append({'filename': item.name, 'reason': 'unsupported_extension'})
                continue
            if item.size > _IMPORT_MAX_FILE_SIZE:
                bad_items.append({'filename': item.name, 'reason': 'too_large'})
                continue
            accepted.append(item)

        # 合法文件逐个复用 LS 上传（字节入 LS 存储，生产=MinIO；坏文件不上传）
        from aoi.datasets.tasks import process_import_job
        from data_import.uploader import create_file_upload

        file_upload_ids: list[int] = []
        for item in accepted:
            file_upload = create_file_upload(request.user, project, item)
            file_upload_ids.append(file_upload.pk)

        job = ImportJob.objects.create(
            job_id=uuid.uuid4().hex[:12],
            status=ImportJob.STATUS_QUEUED,
            total=total,
            bad=len(bad_items),
            bad_items=bad_items,
            file_upload_ids=file_upload_ids,
            source=source or 'manual_real',
            station_code=station_code,
            dataset_id=dataset.pk,
            created_by=self.user_id,
            created_at=datetime.now(timezone.utc),
        )
        try:
            process_import_job.delay(job.pk)
        except Exception as exc:  # broker 不可用：job 留 queued，FileUpload 已存为已知孤儿行为
            logger.warning('import job %s dispatch failed: %s', job.job_id, exc)
            raise AoiError(CODE_UNAVAILABLE, 'task queue unavailable, retry later') from exc
        return self.ok({'job_id': job.job_id}, message='import accepted')


@extend_schema(tags=['aoi-datasets'])
class ImportDetailView(AoiAPIView):
    """``GET /api/datasets/import/{job_id}`` → 任务状态（契约 §4.1；未知 job → ``40401``）。"""

    aoi_perm = 'datasets.view'

    def get(self, request, job_id: str):
        job = ImportJob.objects.filter(job_id=job_id).first()
        if job is None:
            raise AoiError(CODE_NOT_FOUND, f'import job not found: {job_id}')
        return self.ok(serialize_import_job(job))


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


@extend_schema(tags=['aoi-datasets'])
class ImageDetailView(AoiAPIView):
    """``GET/DELETE /api/datasets/images/{id}``（D5 实测新增 DELETE）。

    DELETE = 删除图片登记 + 其 LS 任务（镜像上游删任务路径，计数同步）+ 存储字节
    （``FileUpload``）+ 版本明细（``dataset_item``）；未知 id → ``40401``。
    """

    aoi_perm = 'datasets.view'
    aoi_perm_by_method = {'DELETE': 'datasets.update'}

    def get(self, request, id: int):
        obj = Image.objects.filter(pk=id).first()
        if obj is None:
            raise AoiError(CODE_NOT_FOUND, f'image not found: {id}')
        return self.ok(serialize_image(obj))

    def delete(self, request, id: int):
        obj = Image.objects.filter(pk=id).first()
        if obj is None:
            raise AoiError(CODE_NOT_FOUND, f'image not found: {id}')
        summary = _delete_images([obj])
        write_audit(
            actor_id=self.user_id,
            action='datasets.image.delete',
            object_type='image',
            object_id=str(id),
            detail={'object_key': obj.object_key, **summary},
            request_id=self.request_id,
        )
        return self.ok({'id': id, 'deleted': True, **summary}, message='image deleted')


# --------------------------------------------------------------------------- defects
def _defect_payload(obj: DefectClass) -> dict[str, Any]:
    return serialize_defect(obj)


def _validate_defect_payload(payload: dict[str, Any]) -> dict[str, Any]:
    """POST 全量校验：code/name_cn/risk_level 必填。"""
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


def _validate_defect_patch(payload: dict[str, Any]) -> dict[str, Any]:
    """PUT 部分更新校验（D5 实测修复：启停开关只带 ``{code, active}``，原全量校验误伤 → 42200）。

    仅校验/收集 payload 中出现的字段；``code`` 用于定位对象且不可改（前端编辑态 code 只读）。
    """
    from skillname import is_valid_fault_code

    fields: dict[str, str] = {}
    patch: dict[str, Any] = {}
    code = payload.get('code')
    if not is_valid_fault_code(code):
        raise AoiError(CODE_UNPROCESSABLE, 'invalid defect', fields={'code': f'invalid fault code: {code!r}'})
    if 'name_cn' in payload:
        name_cn = payload.get('name_cn')
        if not name_cn or not isinstance(name_cn, str) or len(name_cn) > 64:
            fields['name_cn'] = 'must be a non-empty string <= 64 chars'
        else:
            patch['name_cn'] = name_cn
    if 'risk_level' in payload:
        risk_level = payload.get('risk_level')
        if isinstance(risk_level, bool) or risk_level not in (1, 2, 3):
            fields['risk_level'] = 'must be 1/2/3'
        else:
            patch['risk_level'] = int(risk_level)
    if 'aliases' in payload:
        aliases = payload.get('aliases')
        if aliases is not None and (not isinstance(aliases, list) or any(not isinstance(alias, str) for alias in aliases)):
            fields['aliases'] = 'must be a list of strings'
        else:
            patch['aliases'] = aliases or []
    if 'active' in payload:
        patch['active'] = bool(payload.get('active'))
    if fields:
        raise AoiError(CODE_UNPROCESSABLE, 'invalid defect', fields=fields)
    patch['code'] = code
    return patch


@extend_schema(tags=['aoi-datasets'])
class DefectListCreateUpdateView(AoiAPIView):
    """``GET/POST/PUT /api/datasets/defects``（契约 §4.1）。"""

    aoi_perm = 'datasets.view'
    # D5 权限澄清（契约 §4.1）：POST=datasets.create、PUT=datasets.update（三角色对两码同持，行为无回退）
    aoi_perm_by_method = {'POST': 'datasets.create', 'PUT': 'datasets.update'}

    def get(self, request):
        # 按 id（创建序）而非 code 字典序：code 前缀已放宽为可变英文词（D5 收尾第二轮），
        # 字典序不再等于「字典构建顺序」；id 序与 training/publish.py 的取数顺序一致，
        # 也保证发布时默认 index（=列表位置）与调色板分配稳定（新增条目追加在末尾）
        qs = DefectClass.objects.all().order_by('id')
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
        # D5 实测修复：PUT 为部分更新语义（如启停开关只带 {code, active}），
        # 原先走 POST 的全量校验会把开关请求误判成 42200
        patch = _validate_defect_patch(payload)
        obj = DefectClass.objects.filter(code=patch['code']).first()
        if obj is None:
            raise AoiError(CODE_NOT_FOUND, f'defect not found: {patch["code"]!r}')
        for key in ('name_cn', 'risk_level', 'aliases', 'active'):
            if key in patch:
                setattr(obj, key, patch[key])
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
                for obj in DefectClass.objects.filter(active=True).order_by('id')
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
        # D5 收尾 #2：把新字典（含中文展示名 html）回写到已建 AOI 标注项目，
        # 否则老数据集标注页仍然显示 code
        projects_synced = _sync_dataset_projects(label_config_xml)
        return self.ok(
            {'version': version, 'label_config': label_config_xml, 'projects_synced': projects_synced},
            message='defect dictionary published',
        )


@extend_schema(tags=['aoi-datasets'])
class DefectVersionListView(AoiAPIView):
    """``GET /api/datasets/defects/versions`` → 缺陷字典发布历史（D5 收尾 #1）。

    历史此前只写库不可见：前端发布后只拿到当次 ``{version, label_config}``，刷新即失，
    无法回答「当前项目用的是哪一版、谁在什么时候改了什么」。
    """

    aoi_perm = 'datasets.view'

    def get(self, request):
        qs = list(DefectDictVersion.objects.all().order_by('-id'))
        latest_id = qs[0].id if qs else None
        publisher_names = _publisher_names({obj.published_by for obj in qs if obj.published_by})
        items = [
            serialize_defect_version(
                obj,
                labels=_defects_from_snapshot(obj.snapshot),
                publisher_name=publisher_names.get(obj.published_by),
                is_latest=obj.id == latest_id,
            )
            for obj in qs
        ]
        return self.ok(paginate(request, items))


def _publisher_names(user_ids: set[int]) -> dict[int, str]:
    """发布人 id → 展示名（邮箱优先，其次用户名）；已删用户回落 ``user#id``。"""
    if not user_ids:
        return {}
    from django.contrib.auth import get_user_model

    users = get_user_model().objects.filter(pk__in=user_ids)
    names: dict[int, str] = {}
    for user in users:
        names[user.pk] = getattr(user, 'email', '') or getattr(user, 'username', '') or f'user#{user.pk}'
    return names


# -------------------------------------------------------------------------- datasets
def _defects_from_snapshot(snapshot: dict[str, Any] | None) -> list[dict[str, Any]]:
    """从字典发布快照 ``{labels:{code:{index,color,name_cn,risk_level}}}`` 还原 defects（供模板渲染）。

    D5 收尾 #2：旧快照只有 index/color，中文展示名回退查当前 ``DefectClass``
    （**不改 code/index**，只补展示字段）。
    """
    codes = list(((snapshot or {}).get('labels') or {}).keys())
    name_lookup = {
        obj.code: {'name_cn': obj.name_cn, 'risk_level': obj.risk_level}
        for obj in DefectClass.objects.filter(code__in=codes)
    }
    return label_config.defects_from_snapshot(snapshot, name_lookup)


def _sync_dataset_projects(label_config_xml: str) -> int:
    """把字典渲染出的 label config 回写到**已建成的 AOI 标注项目**（D5 收尾 #2）。

    为什么需要：中文展示名（``html``）只在 label config 里生效，已建项目不会自动更新，
    不回写的话老数据集标注页仍然显示 code。``value``（code）不变，只补 ``html``/背景色，
    已有标注结果仍然合法。返回真正被更新的项目数。
    """
    from projects.models import Project

    project_ids = list(Dataset.objects.exclude(ls_project_id__isnull=True).values_list('ls_project_id', flat=True))
    if not project_ids:
        return 0
    updated = 0
    for project in Project.objects.filter(pk__in=project_ids):
        if project.label_config != label_config_xml:
            project.label_config = label_config_xml
            project.save(update_fields=['label_config'])
            updated += 1
    return updated



@extend_schema(tags=['aoi-datasets'])
class DatasetListCreateView(AoiAPIView):
    """``GET/POST /api/datasets``（T2.9 裁定路径）。

    D5（标注项目创建自 D6 提前）：``POST`` 由服务端按 ``aoi/datasets/ls_project.py``
    模板创建真实 LS 项目（``ls_project_id`` 不再由客户端传入；携带 → ``42200``）。
    字典来源：优先最新已发布缺陷字典版本快照；**无任何已发布版本时回退当前启用缺陷
    （``active=True``）以 draft 语义建项目**（D5 实测修复：未发布字典无法先建数据集）；
    连启用缺陷都没有 → ``42200``。
    """

    aoi_perm = 'datasets.view'
    aoi_perm_by_method = {'POST': 'datasets.create'}

    def get(self, request):
        items = [serialize_dataset(obj) for obj in Dataset.objects.all().order_by('id')]
        return self.ok(paginate(request, items))

    def post(self, request):
        get_idempotency_key(request)
        payload = _payload(request)
        fields: dict[str, str] = {}
        name = payload.get('name')
        if not isinstance(name, str) or not name.strip():
            fields['name'] = 'required'
        if 'ls_project_id' in payload:
            fields['ls_project_id'] = (
                'server-controlled; the LS project is created from the published defect dictionary'
            )
        cur_version = payload.get('cur_version')
        if cur_version is not None and not isinstance(cur_version, str):
            fields['cur_version'] = 'must be a string'
        if fields:
            raise AoiError(CODE_UNPROCESSABLE, 'invalid dataset payload', fields=fields)

        dict_version = DefectDictVersion.objects.order_by('-id').first()
        if dict_version is not None:
            defects = _defects_from_snapshot(dict_version.snapshot)
            dict_version_label = dict_version.version
        else:
            # 无已发布字典版本：回退当前启用缺陷（draft 语义），允许先建数据集再发布字典
            defects = [
                {'code': obj.code, 'name_cn': obj.name_cn, 'risk_level': obj.risk_level}
                for obj in DefectClass.objects.filter(active=True).order_by('id')
            ]
            dict_version_label = 'draft'
            if not defects:
                raise AoiError(
                    CODE_UNPROCESSABLE,
                    'no defects available',
                    fields={'defects': 'publish a defect dictionary or add active defects first'},
                )

        from aoi.datasets.ls_project import build_project_kwargs
        from projects.models import Project

        kwargs = build_project_kwargs(
            dataset_name=name.strip(),
            version='draft',
            dict_version=dict_version_label,
            defects=defects,
        )
        project = Project.objects.create(
            organization=request.user.active_organization,
            created_by=request.user,
            **kwargs,
        )
        obj = Dataset.objects.create(
            name=name.strip(),
            cur_version=cur_version,
            ls_project_id=project.id,
            created_by=self.user_id,
        )
        write_audit(
            actor_id=self.user_id,
            action='datasets.create',
            object_type='dataset',
            object_id=str(obj.pk),
            detail={'name': obj.name, 'ls_project_id': project.id, 'dict_version': dict_version_label},
            request_id=self.request_id,
        )
        return self.ok(serialize_dataset(obj), message='dataset created')


@extend_schema(tags=['aoi-datasets'])
class DatasetDetailView(AoiAPIView):
    """``GET/PUT/DELETE /api/datasets/{id}``（T2.9 裁定路径；stub 未命中返回占位对象）。

    D5：``ls_project_id`` 改为服务端生成，客户端不可写（携带 → ``42200``）。
    D5 实测：``DELETE`` 由"只删登记行"改为**级联清理**——LS 项目（含任务/标注）、
    项目内导入的图片登记与存储字节、版本与明细；B 线回传图（``images/{md5}.jpg``）
    不在此路径，登记行保留。
    """

    aoi_perm = 'datasets.view'
    aoi_perm_by_method = {'PUT': 'datasets.update', 'DELETE': 'datasets.update'}

    _EDITABLE = ('name', 'cur_version')

    def get(self, request, id: int):
        return self.ok(_dataset_or_stub(id))

    def put(self, request, id: int):
        get_idempotency_key(request)
        payload = _payload(request)
        fields: dict[str, str] = {}
        if 'cur_version' in payload and not isinstance(payload.get('cur_version'), str):
            fields['cur_version'] = 'must be a string'
        if 'ls_project_id' in payload:
            # D5：LS 项目由服务端在创建数据集时生成，客户端不可改写
            fields['ls_project_id'] = (
                'server-controlled; the LS project is created from the published defect dictionary'
            )
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
        if obj is None:
            # D1–D2 stub：未命中返回幂等占位
            return self.ok({'id': id, 'deleted': True, 'stub': True})

        from aoi.datasets.models import DatasetItem, DatasetVersion, Image
        from core.utils.common import temporary_disconnect_all_signals
        from data_import.models import FileUpload
        from projects.models import Project

        detail: dict[str, Any] = {'ls_project_deleted': False, 'versions_deleted': 0}
        project = Project.objects.filter(pk=obj.ls_project_id).first() if obj.ls_project_id else None
        if project is not None:
            # 项目内导入的图片（A 导入 object_key = upload/{project_id}/...）：登记行 + 任务 + 字节
            images = list(Image.objects.filter(object_key__startswith=f'upload/{project.pk}/'))
            detail.update(_delete_images(images))
            # dup/bad 残留的 FileUpload 字节一并清理（行随 project.delete() 级联）
            _delete_file_uploads(FileUpload.objects.filter(project=project))
            # 镜像上游 ProjectAPI.perform_destroy：整项目删除不重算计数、断开信号
            with temporary_disconnect_all_signals():
                project.delete()
            detail['ls_project_deleted'] = True
        version_ids = list(DatasetVersion.objects.filter(dataset_id=obj.pk).values_list('id', flat=True))
        if version_ids:
            DatasetItem.objects.filter(version_id__in=version_ids).delete()
            DatasetVersion.objects.filter(dataset_id=obj.pk).delete()
            detail['versions_deleted'] = len(version_ids)
        name = obj.name
        obj.delete()
        write_audit(
            actor_id=self.user_id,
            action='datasets.delete',
            object_type='dataset',
            object_id=str(id),
            detail={'name': name, **detail},
            request_id=self.request_id,
        )
        return self.ok({'id': id, 'deleted': True, 'stub': False, **detail})


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
        return self.ok(serialize_dataset_version(obj), message='draft version created')


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
