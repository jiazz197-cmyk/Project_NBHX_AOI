"""aoi 导入包裹 Celery 任务（契约 §4.1/§5.2，D5）。

``process_import_job``：消费 ``aoi_datasets.import_job``（queued）中复用 LS 上传生成的
``FileUpload``，逐文件 md5 全局去重 → PIL 解码质检 → 登记 ``aoi_datasets.image`` →
批量建 LS 任务（镜像上游 ``data_import.functions.async_import_background`` 的任务落库路径：
``ProjectSummary`` 行锁 + ``ImportApiSerializer`` + ``update_tasks_counters_and_task_states``
+ ``update_data_columns``；不 emit webhook——aoi 不承诺）。

- 任务自身异常**不外抛**：落 ``failed`` + ``error_message``（前端轮询可见）；
- md5 为**全局**去重语义：同图不进第二个数据集/LS 项目，计 ``dup``；
- dup/bad 文件已上传的 FileUpload 字节保留，不清理（已知残留行为）。
"""

from __future__ import annotations

import hashlib
import logging
import re
from datetime import datetime, timezone
from io import BytesIO

from celery import shared_task
from django.conf import settings
from django.db import transaction

logger = logging.getLogger(__name__)

__all__ = ['process_import_job']

#: 上游 ``upload_name_generator`` 把文件改名成 ``{uuid8}-{filename}``；
#: bad_items 面向用户，这里还原原始文件名。
_UUID8_PREFIX = re.compile(r'^[0-9a-f]{8}-')


def _original_filename(file_upload) -> str:
    name = file_upload.file_name or ''
    return _UUID8_PREFIX.sub('', name, count=1) or name


def _image_value(file_upload) -> str:
    """LS 任务 ``data.image`` 落**浏览器可直接加载的同源 URL**（D5 实测修复）。

    上游云端分支返回裸存储对象键（``filepath``），LSF 会把它按**相对路径**解析 →
    404 → 标注页四张图全部 ERR_LOADING_HTTP（文件本身正常，并非跨域）。本部署
    MinIO 走 LS ``/data/`` 鉴权代理（``AWS_QUERYSTRING_AUTH=False`` + custom domain
    指回 LS），与本地模式同一条 ``UploadedFileResponse`` 路由，因此统一拼
    ``MEDIA_URL``（``/data/``）前缀；LSF 同源加载带 session cookie，天然无跨域问题。
    """
    if settings.CLOUD_FILE_STORAGE_ENABLED:
        name = (file_upload.file.name or '').lstrip('/')
        url = f'{settings.MEDIA_URL}{name}'  # '/data/' + 'upload/<project>/<uuid8>-<filename>'
        script_name = getattr(settings, 'FORCE_SCRIPT_NAME', '') or ''
        if script_name and not url.startswith(f'{script_name}/'):
            url = f'{script_name}{url}'
        return url
    return file_upload.url


def _decode_image(raw: bytes) -> tuple[int | None, int | None]:
    """PIL 解码校验；失败抛异常（由调用方记 ``decode_failed``）。返回 (width, height)。"""
    from PIL import Image as PILImage

    with PILImage.open(BytesIO(raw)) as img:
        img.load()  # 强制解码全图，坏字节在此抛出
        return img.width, img.height


@shared_task
def process_import_job(job_id: int):
    """执行导入任务：登记图片 + 建 LS 任务，写回 job 终态。异常一律落 ``failed``。"""
    from aoi.datasets.models import Dataset, Image, ImportJob
    from data_import.models import FileUpload
    from projects.models import Project, ProjectSummary

    try:
        job = ImportJob.objects.filter(pk=job_id).first()
        if job is None:
            logger.error('import job pk=%s not found, skip', job_id)
            return
        if job.status != ImportJob.STATUS_QUEUED:
            logger.warning('import job %s already processed (status=%s), skip', job.job_id, job.status)
            return
        job.status = ImportJob.STATUS_RUNNING
        job.save(update_fields=['status'])

        dataset = Dataset.objects.filter(pk=job.dataset_id).first() if job.dataset_id else None
        project = (
            Project.objects.filter(pk=dataset.ls_project_id).first()
            if dataset is not None and dataset.ls_project_id
            else None
        )
        if project is None:
            raise RuntimeError(f'dataset {job.dataset_id} has no LS project')

        # D5 收尾修正：计数初值拆开——bad 继承预检拒绝数，ok/dup 必须从 0 起
        # （原 `ok = dup = bad = job.bad` 会把预检 bad 数虚增进 ok/dup，混合批次结果失真）
        ok = 0
        dup = 0
        bad = job.bad
        bad_items = list(job.bad_items or [])
        task_data: list[dict] = []

        for fu_id in job.file_upload_ids or []:
            file_upload = FileUpload.objects.filter(pk=fu_id).first()
            if file_upload is None:
                bad += 1
                bad_items.append({'filename': f'file_upload:{fu_id}', 'reason': 'decode_failed'})
                continue
            raw = file_upload.file.read()
            md5 = hashlib.md5(raw).hexdigest()
            filename = _original_filename(file_upload)

            # md5 全局去重：同图不进第二个数据集/LS 项目
            if Image.objects.filter(md5=md5).exists():
                dup += 1
                continue

            try:
                width, height = _decode_image(raw)
            except Exception:
                # 坏图：登记为 rejected，计入 bad（字节保留在 LS 存储，不清理）
                Image.objects.create(
                    object_key=file_upload.file.name,
                    md5=md5,
                    source=job.source or 'manual_real',
                    station_code=job.station_code,
                    size_bytes=len(raw),
                    qc_status='rejected',
                    qc_reason='decode_failed',
                )
                bad += 1
                bad_items.append({'filename': filename, 'reason': 'decode_failed'})
                continue

            Image.objects.create(
                object_key=file_upload.file.name,
                md5=md5,
                source=job.source or 'manual_real',
                station_code=job.station_code,
                width=width,
                height=height,
                size_bytes=len(raw),
                qc_status='ok',
            )
            task_data.append({'data': {'image': _image_value(file_upload)}})
            ok += 1

        if task_data:
            # 镜像上游 async_import_background 的任务落库路径（含 ProjectSummary 行锁）
            from data_import.serializers import ImportApiSerializer

            with transaction.atomic():
                summary = ProjectSummary.objects.select_for_update().get(project=project)
                serializer = ImportApiSerializer(data=task_data, many=True, context={'project': project})
                serializer.is_valid(raise_exception=True)
                tasks = serializer.save(project_id=project.id)
                project.update_tasks_counters_and_task_states(
                    tasks_queryset=tasks,
                    maximum_annotations_changed=False,
                    overlap_cohort_percentage_changed=False,
                    tasks_number_changed=True,
                    recalculate_stats_counts={
                        'task_count': len(tasks),
                        'annotation_count': 0,
                        'prediction_count': 0,
                    },
                )
                summary.update_data_columns(tasks)

        job.ok = ok
        job.dup = dup
        job.bad = bad
        job.bad_items = bad_items
        job.status = ImportJob.STATUS_SUCCEEDED
        job.finished_at = datetime.now(timezone.utc)
        job.save()
        logger.info('import job %s succeeded: total=%s ok=%s dup=%s bad=%s', job.job_id, job.total, ok, dup, bad)
    except Exception as exc:  # 任务异常不外抛：终态 failed + error_message（契约 §4.1）
        logger.exception('import job processing failed (pk=%s)', job_id)
        ImportJob.objects.filter(pk=job_id).update(
            status=ImportJob.STATUS_FAILED,
            error_message=str(exc)[:2000],
            finished_at=datetime.now(timezone.utc),
        )
