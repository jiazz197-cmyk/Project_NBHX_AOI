"""aoi.review 端点（契约 §4.4/§10；D1–D2 全量 stub）。

复审自研（D2 裁定）：预标三桶 ``auto_pass/recheck/manual`` 中 ``recheck``/``manual``
进入本域人工复审队列；B 回传 ``/api/ingest/findings`` 的 suspicious 也生成 workitem。
本域提供队列/认领/终裁/建议清单/坏图处理。
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from aoi.common.errors import CODE_CONFLICT, CODE_NOT_FOUND, CODE_UNPROCESSABLE, AoiError
from aoi.common.idempotency import get_idempotency_key
from aoi.common.pagination import paginate
from aoi.common.views import AoiAPIView
from aoi.datasets.models import Image
from aoi.datasets.serializers import image_url
from aoi.review.models import BadImage, FeedbackSuggestion, FinalFact, InspectionFact, ReviewWorkitem
from django.db import transaction
from drf_spectacular.utils import extend_schema

FINAL_REASONS = {'misdetection', 'missed_detection', 'new_defect', 'annotation_issue', 'lighting_anomaly'}
FINAL_VERDICTS = {'defect_confirmed', 'false_alarm', 'uncertain'}
REVIEW_ACTIONS = {'accepted_prediction', 'edited', 'relabeled', 'no_defect', 'unlabelable'}
#: 三桶 → UI 颜色（D2 确认：高绿/中黄/低红）
BUCKET_COLORS = {
    ReviewWorkitem.BUCKET_HIGH: '#52C41A',
    ReviewWorkitem.BUCKET_MEDIUM: '#FAAD14',
    ReviewWorkitem.BUCKET_LOW: '#FF4D4F',
}


def _payload(request) -> dict[str, Any]:
    return request.data if isinstance(request.data, dict) else {}


def _iso(value: Any) -> Any:
    return value.isoformat() if value is not None and hasattr(value, 'isoformat') else value


def _serialize_workitem(
    obj: ReviewWorkitem, *, fact: InspectionFact | None = None, image: Any = None
) -> dict[str, Any]:
    """工作项投影；``fact``/``image`` 由列表页批量取（D7 加性投影，契约 §4.4）。

    - ``fact``：ingest 来源的检测事实（工位/序号/verdict 等），预标来源或缺失时为 ``None``；
    - ``image``：``{id, object_key, url, width, height, size_bytes}``（``url`` 按 §4.1 图片 URL
      规则分流），无图或图登记被删时为 ``None``。
    """
    bucket = obj.bucket or ReviewWorkitem.bucket_for_verdict(obj.verdict)
    image_block = None
    if image is not None:
        image_block = {
            'id': image.id,
            'object_key': image.object_key,
            'url': image_url(image),
            'width': image.width,
            'height': image.height,
            'size_bytes': image.size_bytes,
        }
    fact_block = None
    if fact is not None:
        fact_block = {
            'id': fact.id,
            'station_code': fact.station_code,
            'station_name': fact.station_name,
            'seq': fact.seq,
            'captured_at': _iso(fact.captured_at),
            'verdict': fact.verdict,
            'latency_ms': fact.latency_ms,
            'instance_code': fact.instance_code,
        }
    return {
        'id': obj.id,
        'fact_id': obj.fact_id,
        'fact': fact_block,
        'image': image_block,
        'source': obj.source,
        'dataset_version_id': obj.dataset_version_id,
        'image_id': obj.image_id,
        'ls_task_id': obj.ls_task_id,
        'ls_prediction_id': obj.ls_prediction_id,
        'model_ref': obj.model_ref,
        'bucket': bucket,
        'bucket_color': BUCKET_COLORS.get(bucket),
        'verdict': obj.verdict,
        'bucket_reason': obj.bucket_reason,
        'forced': obj.forced,
        'route': obj.route,
        'recheck_result': obj.recheck_result,
        'hv_key': obj.hv_key,
        'status': obj.status,
        'assignee_id': obj.assignee_id,
        'final_verdict': obj.final_verdict,
        'final_reason': obj.final_reason,
        'finalized_at': _iso(obj.finalized_at),
    }


def _serialize_bad_image(obj: BadImage) -> dict[str, Any]:
    return {
        'id': obj.id,
        'station_code': obj.station_code,
        'station_name': obj.station_name,
        'seq': obj.seq,
        'captured_at': _iso(obj.captured_at),
        'error_code': obj.error_code,
        'image_key': obj.image_key,
        'instance_code': obj.instance_code,
        'handled': obj.handled,
        'handled_by': obj.handled_by,
        'note': None if (obj.note or '').startswith('__ingest_fp__:') else obj.note,
        'created_at': _iso(obj.created_at),
    }


def _workitem_page_items(request, qs) -> list[dict[str, Any]]:
    """列表页组装：分页在 Python 侧做（与契约一致），fact/image 各一次批量查询避免 N+1。"""
    page = paginate(request, list(qs))
    items = page['items']
    facts = {obj.id: obj for obj in InspectionFact.objects.filter(id__in={i.fact_id for i in items if i.fact_id})}
    image_ids = set()
    for item in items:
        if item.image_id:
            image_ids.add(item.image_id)
        fact = facts.get(item.fact_id)
        if fact is not None and fact.image_id:
            image_ids.add(fact.image_id)
    images = {obj.id: obj for obj in Image.objects.filter(id__in=image_ids)}
    page['items'] = [
        _serialize_workitem(
            item,
            fact=facts.get(item.fact_id),
            image=images.get(item.image_id)
            or (images.get(facts[item.fact_id].image_id) if item.fact_id in facts else None),
        )
        for item in items
    ]
    return page


@extend_schema(tags=['aoi-review'])
class WorkitemListView(AoiAPIView):
    """``GET /api/review/workitems``（真实队列；空队列返回空列表，不伪造 item）。"""

    aoi_perm = 'review.view'

    def get(self, request):
        qs = ReviewWorkitem.objects.all().order_by('id')
        for field in ('status', 'source', 'bucket'):
            value = request.query_params.get(field)
            if value:
                qs = qs.filter(**{field: value})
        dataset_version_id = request.query_params.get('dataset_version_id')
        if dataset_version_id:
            qs = qs.filter(dataset_version_id=dataset_version_id)
        return self.ok(_workitem_page_items(request, qs))


@extend_schema(tags=['aoi-review'])
class WorkitemClaimView(AoiAPIView):
    """``POST /api/review/workitems/{id}/claim``（乐观并发：只有 pending 能被认领）。"""

    aoi_perm = 'review.update'

    def post(self, request, id: int):
        get_idempotency_key(request)
        updated = ReviewWorkitem.objects.filter(pk=id, status=ReviewWorkitem.STATUS_PENDING).update(
            status=ReviewWorkitem.STATUS_PROCESSING, assignee_id=self.user_id
        )
        obj = ReviewWorkitem.objects.filter(pk=id).first()
        if obj is None:
            raise AoiError(CODE_NOT_FOUND, 'workitem not found')
        if not updated:
            # 只有 pending 能被认领一次；重复认领 → 40900（并发下两个 worker 只有一个成功）
            raise AoiError(
                CODE_CONFLICT,
                f'workitem already {obj.status}',
                fields={'status': obj.status, 'assignee_id': obj.assignee_id},
            )
        return self.ok(_serialize_workitem(obj))


@extend_schema(tags=['aoi-review'])
class WorkitemFinalizeView(AoiAPIView):
    """``POST /api/review/workitems/{id}/finalize``（原因必填；状态机 + 低桶强制重标）。"""

    aoi_perm = 'review.finalize'

    def post(self, request, id: int):
        get_idempotency_key(request)
        payload = _payload(request)
        final_reason = payload.get('final_reason')
        if not final_reason:
            raise AoiError(CODE_UNPROCESSABLE, 'final_reason is required', fields={'final_reason': 'required'})
        if final_reason not in FINAL_REASONS:
            raise AoiError(
                CODE_UNPROCESSABLE,
                'invalid final_reason',
                fields={'final_reason': f'must be one of {sorted(FINAL_REASONS)}'},
            )
        verdict = payload.get('verdict')
        if verdict and verdict not in FINAL_VERDICTS:
            raise AoiError(
                CODE_UNPROCESSABLE,
                'invalid verdict',
                fields={'verdict': f'must be one of {sorted(FINAL_VERDICTS)}'},
            )
        action = payload.get('action')
        if action and action not in REVIEW_ACTIONS:
            raise AoiError(
                CODE_UNPROCESSABLE,
                'invalid action',
                fields={'action': f'must be one of {sorted(REVIEW_ACTIONS)}'},
            )
        annotation = payload.get('annotation') if isinstance(payload.get('annotation'), dict) else None
        annotation_id = payload.get('annotation_id') or (annotation or {}).get('id')

        obj = ReviewWorkitem.objects.filter(pk=id).first()
        if obj is None:
            raise AoiError(CODE_NOT_FOUND, 'workitem not found')
        if obj.status == ReviewWorkitem.STATUS_FINALIZED:
            raise AoiError(CODE_CONFLICT, 'workitem already finalized', fields={'status': obj.status})
        if obj.status not in (ReviewWorkitem.STATUS_PENDING, ReviewWorkitem.STATUS_PROCESSING):
            raise AoiError(CODE_CONFLICT, f'workitem is {obj.status}', fields={'status': obj.status})

        # 低桶 / forced：必须有重标/无缺陷/不可标注动作或人工 annotation（契约 §4.4/§10 / 设计 §5）
        forced = bool(obj.forced or obj.bucket == ReviewWorkitem.BUCKET_LOW)
        if forced and not (action in {'relabeled', 'no_defect', 'unlabelable'} or annotation or annotation_id):
            raise AoiError(
                CODE_UNPROCESSABLE,
                'forced manual review requires action/annotation',
                fields={'action': 'required for low/forced item', 'annotation': 'required if action=edited'},
            )
        # edited 必须带人工标注内容，避免"改了但没留下改了什么"
        if action == 'edited' and not (annotation or payload.get('boxes')):
            raise AoiError(
                CODE_UNPROCESSABLE,
                'action=edited requires annotation or boxes',
                fields={'annotation': 'required if action=edited'},
            )

        finalized_at = datetime.now(timezone.utc)
        with transaction.atomic():
            obj.status = ReviewWorkitem.STATUS_FINALIZED
            obj.final_verdict = verdict or obj.final_verdict
            obj.final_reason = final_reason
            obj.finalized_at = finalized_at
            obj.save(update_fields=['status', 'final_verdict', 'final_reason', 'finalized_at'])
            FinalFact.objects.update_or_create(
                workitem_id=obj.id,
                defaults={
                    'fact_id': obj.fact_id,
                    'source': obj.source,
                    'dataset_version_id': obj.dataset_version_id,
                    'image_id': obj.image_id,
                    'ls_task_id': obj.ls_task_id,
                    'annotation_id': annotation_id,
                    'action': action or 'accepted_prediction',
                    'verdict': verdict or 'defect_confirmed',
                    'class_id': payload.get('class_id'),
                    'boxes': payload.get('boxes'),
                    'note': payload.get('note'),
                    'decided_by': self.user_id,
                    'decided_at': finalized_at,
                },
            )
            # 回传来源的检测事实随终裁推进状态（P1：状态机一致性）
            if obj.fact_id:
                InspectionFact.objects.filter(pk=obj.fact_id).update(status='finalized')
        from aoi.common.audit import write_audit

        write_audit(
            actor_id=self.user_id,
            action='review.finalize',
            object_type='aoi_review.review_workitem',
            object_id=str(id),
            detail={'verdict': verdict, 'final_reason': final_reason, 'action': action},
            request_id=self.request_id,
        )
        return self.ok(_serialize_workitem(obj))


@extend_schema(tags=['aoi-review'])
class SuggestionListView(AoiAPIView):
    """``GET /api/review/suggestions``。"""

    aoi_perm = 'review.view'

    def get(self, request):
        qs = FeedbackSuggestion.objects.all().order_by('id')
        status_param = request.query_params.get('status')
        if status_param:
            qs = qs.filter(status=status_param)
        items = [
            {
                'id': obj.id,
                'workitem_id': obj.workitem_id,
                'image_id': obj.image_id,
                'rule_code': obj.rule_code,
                'suggestion': obj.suggestion,
                'status': obj.status,
                'confirmed_by': obj.confirmed_by,
                'confirmed_at': _iso(obj.confirmed_at),
            }
            for obj in qs
        ]
        return self.ok(paginate(request, items))


@extend_schema(tags=['aoi-review'])
class SuggestionBatchConfirmView(AoiAPIView):
    """``POST /api/review/suggestions/batch-confirm``。"""

    aoi_perm = 'review.update'

    def post(self, request):
        get_idempotency_key(request)
        payload = _payload(request)
        ids = payload.get('ids') or payload.get('suggestion_ids') or []
        if not isinstance(ids, list):
            raise AoiError(CODE_UNPROCESSABLE, 'ids must be a list', fields={'ids': 'must be a list'})
        qs = FeedbackSuggestion.objects.filter(pk__in=ids)
        confirmed = 0
        for obj in qs:
            obj.status = 'confirmed'
            obj.confirmed_by = self.user_id
            obj.confirmed_at = datetime.now(timezone.utc)
            obj.save(update_fields=['status', 'confirmed_by', 'confirmed_at'])
            confirmed += 1
        return self.ok({'confirmed': confirmed, 'requested': len(ids)})


@extend_schema(tags=['aoi-review'])
class BadImageListView(AoiAPIView):
    """``GET /api/review/bad-images``。"""

    aoi_perm = 'review.view'

    def get(self, request):
        qs = BadImage.objects.all().order_by('id')
        handled = request.query_params.get('handled')
        if handled is not None:
            qs = qs.filter(handled=str(handled).lower() in {'1', 'true', 'yes'})
        items = [_serialize_bad_image(obj) for obj in qs]
        return self.ok(paginate(request, items))


@extend_schema(tags=['aoi-review'])
class BadImageHandleView(AoiAPIView):
    """``POST /api/review/bad-images/{id}/handle``。"""

    aoi_perm = 'review.update'

    def post(self, request, id: int):
        get_idempotency_key(request)
        payload = _payload(request)
        obj = BadImage.objects.filter(pk=id).first()
        if obj is None:
            return self.ok({'id': id, 'handled': True, 'handled_by': self.user_id, 'stub': True})
        obj.handled = True
        obj.handled_by = self.user_id
        if payload.get('note') and not str(payload['note']).startswith('__ingest_fp__:'):
            obj.note = str(payload['note'])
        obj.save(update_fields=['handled', 'handled_by', 'note'])
        return self.ok(_serialize_bad_image(obj))
