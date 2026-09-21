"""aoi.datasets stub 序列化（dict 形式，D4 起替换为 DRF Serializer）。"""

from __future__ import annotations

from typing import Any

__all__ = [
    'serialize_image',
    'serialize_defect',
    'serialize_dataset',
    'serialize_dataset_version',
    'serialize_import_job',
    'serialize_defect_version',
]


#: 数据集投影里携带的预览图数量上限（图库概览每个数据集只画这么多）
DATASET_PREVIEW_IMAGE_LIMIT = 5


def _iso(value: Any) -> Any:
    return value.isoformat() if value is not None and hasattr(value, 'isoformat') else value


def serialize_image(obj: Any, *, dataset_id: int | None = None) -> dict[str, Any]:
    """图片投影；``dataset_id`` 由调用方按导入前缀反查后传入（``image`` 表无 dataset 外键）。"""
    return {
        'id': obj.id,
        'dataset_id': dataset_id,
        'object_key': obj.object_key,
        'md5': obj.md5,
        'source': obj.source,
        'station_code': obj.station_code,
        'seq': obj.seq,
        'captured_at': _iso(obj.captured_at),
        'width': obj.width,
        'height': obj.height,
        'size_bytes': obj.size_bytes,
        'qc_status': obj.qc_status,
        'qc_reason': obj.qc_reason,
        'status': obj.status,
        'trace_id': obj.trace_id,
    }


def serialize_defect(obj: Any) -> dict[str, Any]:
    return {
        'id': obj.id,
        'code': obj.code,
        'name_cn': obj.name_cn,
        'risk_level': obj.risk_level,
        'aliases': obj.aliases or [],
        'active': obj.active,
    }


def serialize_dataset(obj: Any) -> dict[str, Any]:
    """数据集投影；D5 实测补 ``versions``（草稿版本创建后前端可见，修复「无反应」观感）。

    ``dataset_id`` 是普通整型列（非 FK），无法 prefetch_related；列表页数据量小（≤200），
    每行一查可接受。

    D5 收尾第四轮补 ``image_count``：数据集账本/上传下拉要显示"这个数据集里有多少张图"，
    按导入路径前缀 ``upload/{ls_project_id}/`` 计数（一行一查，规模同上）。
    """
    from aoi.datasets.models import DatasetVersion, Image

    versions = list(
        DatasetVersion.objects.filter(dataset_id=obj.id).order_by('id').values('id', 'version', 'status', 'phase')
    )
    image_count = 0
    preview_images: list[dict[str, Any]] = []
    if obj.ls_project_id:
        scoped = Image.objects.filter(object_key__startswith=f'upload/{obj.ls_project_id}/').order_by('id')
        image_count = scoped.count()
        # D5 收尾第六轮：图库按数据集展示，每个数据集只带 5 张预览（其余到「查看全部」里翻页）
        preview_images = [serialize_image(image, dataset_id=obj.id) for image in scoped[:DATASET_PREVIEW_IMAGE_LIMIT]]
    return {
        'id': obj.id,
        'name': obj.name,
        'cur_version': obj.cur_version,
        'ls_project_id': obj.ls_project_id,
        'created_by': obj.created_by,
        'image_count': image_count,
        'preview_images': preview_images,
        'versions': versions,
    }


def serialize_dataset_version(obj: Any) -> dict[str, Any]:
    return {
        'id': obj.id,
        'dataset_id': obj.dataset_id,
        'version': obj.version,
        'status': obj.status,
        'phase': getattr(obj, 'phase', 'draft'),
        'split_seed': obj.split_seed,
        'split_stats': obj.split_stats,
        'class_dist': obj.class_dist,
        'source_stats': obj.source_stats,
        'dict_version': obj.dict_version,
        'note': obj.note,
        'created_by': obj.created_by,
    }


def serialize_defect_version(
    obj: Any,
    *,
    labels: list[dict[str, Any]] | None = None,
    publisher_name: str | None = None,
    is_latest: bool = False,
) -> dict[str, Any]:
    """缺陷字典发布历史条目（契约 §4.1 ``GET /defects/versions``，D5 收尾 #1）。

    ``labels`` 由调用方用 ``label_config.defects_from_snapshot`` 还原（含中文名兜底），
    这里不重复实现快照解析；``snapshot`` 原样返回，便于前端/排障对照。
    """
    return {
        'id': obj.id,
        'version': obj.version,
        'published_by': obj.published_by,
        'published_by_name': publisher_name,
        'published_at': _iso(obj.published_at),
        'defect_count': len(labels) if labels is not None else len((obj.snapshot or {}).get('labels') or {}),
        'labels': labels or [],
        'is_latest': is_latest,
    }


def serialize_import_job(obj: Any) -> dict[str, Any]:
    """导入任务状态（契约 §4.1 ``GET /import/{job_id}``）。"""
    return {
        'job_id': obj.job_id,
        'status': obj.status,
        'total': obj.total,
        'ok': obj.ok,
        'dup': obj.dup,
        'bad': obj.bad,
        'bad_items': obj.bad_items or [],
        'source': obj.source,
        'station_code': obj.station_code,
        'dataset_id': obj.dataset_id,
        'error_message': obj.error_message,
        'created_at': _iso(obj.created_at),
        'finished_at': _iso(obj.finished_at),
    }
