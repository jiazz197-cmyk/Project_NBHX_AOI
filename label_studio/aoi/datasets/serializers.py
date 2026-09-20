"""aoi.datasets stub 序列化（dict 形式，D4 起替换为 DRF Serializer）。"""

from __future__ import annotations

from typing import Any

__all__ = [
    'serialize_image',
    'serialize_defect',
    'serialize_dataset',
    'serialize_dataset_version',
    'serialize_import_job',
]


def _iso(value: Any) -> Any:
    return value.isoformat() if value is not None and hasattr(value, 'isoformat') else value


def serialize_image(obj: Any) -> dict[str, Any]:
    return {
        'id': obj.id,
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
    """
    from aoi.datasets.models import DatasetVersion

    versions = list(
        DatasetVersion.objects.filter(dataset_id=obj.id).order_by('id').values('id', 'version', 'status', 'phase')
    )
    return {
        'id': obj.id,
        'name': obj.name,
        'cur_version': obj.cur_version,
        'ls_project_id': obj.ls_project_id,
        'created_by': obj.created_by,
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
