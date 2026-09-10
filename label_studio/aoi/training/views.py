"""aoi.training 端点（契约 §4.2；D1–D2 全量 stub）。

- 训练/模型数据落 ``aoi_training`` 表；未命中返回同形 stub；
- SSE 进度用 Django ``StreamingHttpResponse``（P0 §2.6：training×2~3 + finished）；
- 发布为 stub：写 ``model_publish=queued``，真实 build/push 在 D7（计划 §7 出界）。
"""

from __future__ import annotations

import json
from typing import Any

from aoi.common.errors import CODE_CONFLICT, CODE_NOT_FOUND, CODE_UNPROCESSABLE, AoiError
from aoi.common.idempotency import get_idempotency_key
from aoi.common.pagination import paginate
from aoi.common.settings import get_model_image_repo, get_model_registry
from aoi.common.views import AoiAPIView
from aoi.training.models import BaseModel, Model, ModelPublish, Preset, TrainJob
from django.http import StreamingHttpResponse
from drf_spectacular.utils import extend_schema
from skillname import SkillName, image_tag_from_model_ref

DEFAULT_PRESET = {
    'framework': 'yolo',
    'base_model': 'yolov8s.pt',
    'class_subset': ['object_fault_type_01'],
    'params': {
        'tiling': {'size': 1280, 'overlap': 0.2, 'enabled': True},
        'imgsz': 1280,
        'batch': 8,
        'epochs': 100,
        'lr0': 0.01,
        'patience': 20,
        'augment': {'flip': True, 'mosaic': True, 'mixup': 0.1},
        'split': {'train': 0.7, 'val': 0.2, 'test': 0.1},
    },
}


def _payload(request) -> dict[str, Any]:
    return request.data if isinstance(request.data, dict) else {}


def _iso(value: Any) -> Any:
    return value.isoformat() if value is not None and hasattr(value, 'isoformat') else value


def _serialize_base_model(obj: BaseModel) -> dict[str, Any]:
    return {
        'id': obj.id,
        'name': obj.name,
        'framework': obj.framework,
        'task_type': obj.task_type,
        'weights_key': obj.weights_key,
        'params_schema': obj.params_schema,
        'active': obj.active,
    }


def _serialize_preset(obj: Preset) -> dict[str, Any]:
    return {
        'id': obj.id,
        'name': obj.name,
        'framework': obj.framework,
        'task_type': obj.task_type,
        'base_model': obj.base_model,
        'params': obj.params,
        'class_subset': obj.class_subset,
        'created_by': obj.created_by,
        'active': obj.active,
    }


def _serialize_train_job(obj: TrainJob) -> dict[str, Any]:
    return {
        'id': obj.id,
        'dataset_version': obj.dataset_version,
        'framework': obj.framework,
        'task_type': obj.task_type,
        'preset': obj.preset,
        'status': obj.status,
        'celery_task_id': obj.celery_task_id,
        'metrics': obj.metrics,
        'artifact_path': obj.artifact_path,
        'error_message': obj.error_message,
        'created_by': obj.created_by,
        'started_at': _iso(obj.started_at),
        'finished_at': _iso(obj.finished_at),
    }


def _serialize_model(obj: Model) -> dict[str, Any]:
    return {
        'id': obj.id,
        'version': obj.version,
        'framework': obj.framework,
        'task_type': obj.task_type,
        'dataset_version': obj.dataset_version,
        'base_model': obj.base_model,
        'weights_key': obj.weights_key,
        'class_names': obj.class_names,
        'cover_classes': obj.cover_classes,
        'precision': obj.precision,
        'input_shape': obj.input_shape,
        'tensor_names': obj.tensor_names,
        'eval_metrics': obj.eval_metrics,
        'gate_status': obj.gate_status,
        'llm_review': obj.llm_review,
        'lifecycle': obj.lifecycle,
        'config_snapshot': obj.config_snapshot,
    }


def _model_or_stub(pk: int) -> tuple[dict[str, Any], Model | None]:
    obj = Model.objects.filter(pk=pk).first()
    if obj is not None:
        return _serialize_model(obj), obj
    return (
        {
            'id': pk,
            'version': f'{pk}-yolo@ds1',
            'framework': 'yolo',
            'task_type': SkillName.OBJECT_DETECTION.value,
            'dataset_version': '1',
            'base_model': 'yolov8s.pt',
            'weights_key': None,
            'class_names': ['object_fault_type_01'],
            'cover_classes': ['object_fault_type_01'],
            'precision': 'fp32',
            'input_shape': [1, 3, 1280, 1280],
            'tensor_names': {'input': 'images', 'output': 'output0'},
            'eval_metrics': {},
            'gate_status': 'pending',
            'llm_review': None,
            'lifecycle': 'candidate',
            'config_snapshot': None,
            'stub': True,
        },
        None,
    )


@extend_schema(tags=['aoi-train'])
class BaseModelListView(AoiAPIView):
    """``GET /api/train/base-models``。"""

    aoi_perm = 'training.view'

    def get(self, request):
        items = [_serialize_base_model(obj) for obj in BaseModel.objects.filter(active=True).order_by('id')]
        if not items:
            items = [
                {
                    'id': 1,
                    'name': 'yolov8s.pt',
                    'framework': 'yolo',
                    'task_type': SkillName.OBJECT_DETECTION.value,
                    'weights_key': 'models/base/yolov8s.pt',
                    'params_schema': {
                        'imgsz': {'type': 'int', 'default': 1280},
                        'epochs': {'type': 'int', 'default': 100},
                    },
                    'active': True,
                    'stub': True,
                }
            ]
        return self.ok(paginate(request, items))


@extend_schema(tags=['aoi-train'])
class PresetListView(AoiAPIView):
    """``GET /api/train/presets``。"""

    aoi_perm = 'training.view'

    def get(self, request):
        items = [_serialize_preset(obj) for obj in Preset.objects.filter(active=True).order_by('id')]
        if not items:
            items = [
                {
                    'id': 1,
                    'name': 'default-yolo',
                    'framework': 'yolo',
                    'task_type': SkillName.OBJECT_DETECTION.value,
                    'base_model': 'yolov8s.pt',
                    'params': DEFAULT_PRESET['params'],
                    'class_subset': DEFAULT_PRESET['class_subset'],
                    'created_by': None,
                    'active': True,
                    'stub': True,
                }
            ]
        return self.ok(paginate(request, items))


@extend_schema(tags=['aoi-train'])
class TrainJobCreateView(AoiAPIView):
    """``POST /api/train/jobs`` → ``{job_id}``。"""

    aoi_perm = 'training.create'

    def post(self, request):
        get_idempotency_key(request)
        payload = _payload(request)
        preset = payload.get('preset') or DEFAULT_PRESET
        job = TrainJob.objects.create(
            dataset_version=str(payload.get('dataset_version') or '1'),
            framework=str(payload.get('framework') or 'yolo'),
            task_type=str(payload.get('task_type') or SkillName.OBJECT_DETECTION.value),
            preset=preset,
            status=TrainJob.STATUS_QUEUED,
            created_by=self.user_id,
        )
        return self.ok({'job_id': job.id, 'status': job.status})


@extend_schema(tags=['aoi-train'])
class TrainJobDetailView(AoiAPIView):
    """``GET /api/train/jobs/{id}``。"""

    aoi_perm = 'training.view'

    def get(self, request, id: int):
        obj = TrainJob.objects.filter(pk=id).first()
        if obj is None:
            return self.ok(
                {
                    'id': id,
                    'dataset_version': '1',
                    'framework': 'yolo',
                    'task_type': SkillName.OBJECT_DETECTION.value,
                    'preset': DEFAULT_PRESET,
                    'status': 'queued',
                    'metrics': {},
                    'stub': True,
                }
            )
        return self.ok(_serialize_train_job(obj))


@extend_schema(tags=['aoi-train'])
class TrainJobCancelView(AoiAPIView):
    """``POST /api/train/jobs/{id}/cancel``。"""

    aoi_perm = 'training.cancel'

    def post(self, request, id: int):
        obj = TrainJob.objects.filter(pk=id).first()
        if obj is None:
            return self.ok({'id': id, 'status': 'canceled', 'stub': True})
        if obj.status in (TrainJob.STATUS_QUEUED, TrainJob.STATUS_RUNNING):
            obj.status = TrainJob.STATUS_CANCELED
            obj.save(update_fields=['status'])
        return self.ok(_serialize_train_job(obj))


@extend_schema(tags=['aoi-train'])
class TrainJobProgressView(AoiAPIView):
    """``GET /api/train/jobs/{id}/progress`` → SSE（training×2~3 + finished）。"""

    aoi_perm = 'training.view'

    def get(self, request, id: int):
        total = 3

        def event_stream():
            for epoch in range(1, total + 1):
                payload = {
                    'phase': 'training',
                    'epoch': epoch,
                    'total': 100,
                    'loss': round(0.5 / epoch, 4),
                    'metrics': {'map50': round(0.5 + epoch * 0.1, 4)},
                }
                yield f'data: {json.dumps(payload, ensure_ascii=False)}\n\n'
            yield f'data: {json.dumps({"phase": "finished", "epoch": 100, "total": 100, "metrics": {"map50": 0.9}}, ensure_ascii=False)}\n\n'

        response = StreamingHttpResponse(event_stream(), content_type='text/event-stream')
        response['Cache-Control'] = 'no-cache'
        response['X-Accel-Buffering'] = 'no'
        return response


@extend_schema(tags=['aoi-train'])
class ModelListView(AoiAPIView):
    """``GET /api/train/models?lifecycle=&task_type=``。"""

    aoi_perm = 'training.view'

    def get(self, request):
        qs = Model.objects.all().order_by('id')
        lifecycle = request.query_params.get('lifecycle')
        task_type = request.query_params.get('task_type')
        if lifecycle:
            qs = qs.filter(lifecycle=lifecycle)
        if task_type:
            qs = qs.filter(task_type=task_type)
        items = [_serialize_model(obj) for obj in qs]
        if not items and not lifecycle and not task_type:
            items = [_model_or_stub(1)[0]]
        return self.ok(paginate(request, items))


@extend_schema(tags=['aoi-train'])
class ModelApproveView(AoiAPIView):
    """``POST /api/train/models/{id}/approve``（``{decision, note}`` → lifecycle=approved）。

    P1：未知 id → 40401；``decision ∉ {approve, reject}`` → 42200；``approve`` 要求门禁通过
    （契约 §8：门禁一票否决；金标准 100% 才允许 approved，金标准字段 D9 落表后接入）。
    """

    aoi_perm = 'training.approve'

    APPROVE_DECISIONS = {'approve', 'reject'}

    def post(self, request, id: int):
        payload = _payload(request)
        decision = str(payload.get('decision') or 'approve').lower()
        if decision in {'approved'}:
            decision = 'approve'
        if decision in {'rejected'}:
            decision = 'reject'
        if decision not in self.APPROVE_DECISIONS:
            raise AoiError(
                CODE_UNPROCESSABLE,
                'invalid decision',
                fields={'decision': f'must be one of {sorted(self.APPROVE_DECISIONS)}'},
            )

        obj = Model.objects.filter(pk=id).first()
        if obj is None:
            raise AoiError(CODE_NOT_FOUND, 'model not found')
        if decision == 'approve' and obj.gate_status != Model.GATE_PASSED:
            raise AoiError(
                CODE_CONFLICT,
                'model gate not passed; approval rejected',
                fields={'gate_status': obj.gate_status or 'pending'},
            )

        obj.lifecycle = Model.LIFECYCLE_APPROVED if decision == 'approve' else Model.LIFECYCLE_CANDIDATE
        obj.save(update_fields=['lifecycle'])
        data = _serialize_model(obj)
        from aoi.common.audit import write_audit

        write_audit(
            actor_id=self.user_id,
            action='model.approve',
            object_type='aoi_training.model',
            object_id=str(id),
            detail={'decision': decision, 'gate_status': obj.gate_status},
            request_id=self.request_id,
        )
        return self.ok(data)


@extend_schema(tags=['aoi-train'])
class ModelPublishView(AoiAPIView):
    """``POST/GET /api/train/models/{id}/publish``（D3 stub：写 ``model_publish=queued``，真实 build/push 在 D7）。

    P1：未知模型 → 40401；``lifecycle`` 必须已 approved（契约 §8 发布前置）；唯一性按
    ``(model_ref, tag)``，同 tag 已有的发布记录不再覆盖（换 ``model_ref`` 版本号递增）。
    """

    aoi_perm = 'training.publish'

    _ACTIVE_STATUSES = (
        ModelPublish.STATUS_QUEUED,
        ModelPublish.STATUS_BUILDING,
        ModelPublish.STATUS_PUSHING,
        ModelPublish.STATUS_PUBLISHED,
    )

    def post(self, request, id: int):
        get_idempotency_key(request)
        obj = Model.objects.filter(pk=id).first()
        if obj is None:
            raise AoiError(CODE_NOT_FOUND, 'model not found')
        if obj.lifecycle != Model.LIFECYCLE_APPROVED:
            raise AoiError(
                CODE_CONFLICT,
                'model must be approved before publishing',
                fields={'lifecycle': obj.lifecycle},
            )
        model_ref = str(obj.version)
        try:
            tag = image_tag_from_model_ref(model_ref, obj.precision)
        except ValueError as exc:
            raise AoiError(
                CODE_UNPROCESSABLE,
                'model.version is not a valid model_ref',
                fields={'version': str(exc)},
            ) from exc

        registry = get_model_registry()
        image = f'{registry}/{get_model_image_repo()}'
        existing = ModelPublish.objects.filter(model_ref=model_ref, tag=tag).first()
        if existing is not None and existing.status in self._ACTIVE_STATUSES:
            raise AoiError(
                CODE_CONFLICT,
                'model already published or publishing for this tag',
                fields={'tag': tag, 'status': existing.status},
            )
        if existing is not None:
            # 失败重推：同 tag 重试，不新增记录（同 tag 不同 digest 由发布器在 D7 校验后拒绝覆盖）
            existing.status = ModelPublish.STATUS_QUEUED
            existing.attempts += 1
            existing.error_message = None
            existing.save(update_fields=['status', 'attempts', 'error_message'])
            publish = existing
        else:
            publish = ModelPublish.objects.create(
                model_ref=model_ref,
                registry=registry,
                image=image,
                tag=tag,
                status=ModelPublish.STATUS_QUEUED,
                published_by=self.user_id,
            )
        return self.ok(
            {
                'publish_id': publish.id,
                'status': publish.status,
                'model_ref': model_ref,
                'tag': tag,
                'image': image,
                # D3 stub：真实 build/push 在 D7，调用方据此不要把它当已发布
                'stub': True,
            }
        )

    def get(self, request, id: int):
        obj = Model.objects.filter(pk=id).first()
        if obj is None:
            raise AoiError(CODE_NOT_FOUND, 'model not found')
        model_ref = str(obj.version)
        try:
            tag = image_tag_from_model_ref(model_ref, obj.precision)
        except ValueError as exc:
            raise AoiError(
                CODE_UNPROCESSABLE,
                'model.version is not a valid model_ref',
                fields={'version': str(exc)},
            ) from exc
        publish = ModelPublish.objects.filter(model_ref=model_ref, tag=tag).first()
        if publish is None:
            # 契约 §2.6：GET publish 无记录 → 40401（此前返回伪造的 queued）
            raise AoiError(CODE_NOT_FOUND, 'no publish record for this model/tag', fields={'tag': tag})
        return self.ok(
            {
                'model_ref': publish.model_ref,
                'image': publish.image,
                'tag': publish.tag,
                'digest': publish.digest,
                'status': publish.status,
                'attempts': publish.attempts,
                'error_message': publish.error_message,
                'published_at': _iso(publish.published_at),
            }
        )
