"""aoi.prelabel 端点（契约 §4.3；T2.5 stub）。

- ``/api/prelabel/tasks``：预标任务 CRUD（JWT，D4 起真实导入/推理）；
- ``/api/prelabel/{task_id}/{health,setup,predict,validate,webhook}``：LS 官方 ML backend 协议；
- **鉴权实证**：LS 1.x ``MLApi`` 只发送 ``User-Agent``（可选 Basic Auth），不携带
  ``X-Internal-Token``（``label_studio/ml/api_connector.py``）。故默认放行 LS 调用；
  若请求携带内部头则必须正确；置 ``AOI_PRELABEL_REQUIRE_INTERNAL_TOKEN=true`` 可强制 40100。
"""

from __future__ import annotations

from typing import Any

from aoi.common.errors import CODE_UNPROCESSABLE, AoiError
from aoi.common.idempotency import get_idempotency_key
from aoi.common.pagination import paginate
from aoi.common.settings import get_prelabel_require_internal_token, internal_token_matches
from aoi.common.views import AoiAPIView
from aoi.datasets.models import PrelabelTask
from aoi.prelabel import protocol
from django.contrib.auth.models import AnonymousUser
from drf_spectacular.utils import extend_schema
from rest_framework.authentication import BaseAuthentication
from rest_framework.exceptions import AuthenticationFailed
from rest_framework.permissions import AllowAny
from skillname import parse_model_ref

__all__ = ['PrelabelTokenAuthentication']


class PrelabelTokenAuthentication(BaseAuthentication):
    """可选 ``X-Internal-Token`` 鉴权（默认放行 LS；带错头 → 40100，未配置 fail closed）。"""

    def authenticate(self, request):
        provided = request.headers.get('X-Internal-Token')
        if get_prelabel_require_internal_token():
            if not internal_token_matches(provided):
                raise AuthenticationFailed('invalid or missing X-Internal-Token')
        elif provided and not internal_token_matches(provided):
            raise AuthenticationFailed('invalid X-Internal-Token')
        return (AnonymousUser(), None)


class PrelabelProtocolView(AoiAPIView):
    """ML backend 协议端点基类（无 JWT，可选内部头）。

    **不使用 aoi 信封**：LS 官方协议要求顶层 ``status``/``results``/``errors``
    （契约 §4.3），信封只用于 aoi 业务接口。
    """

    authentication_classes = [PrelabelTokenAuthentication]
    permission_classes = [AllowAny]

    def ok(self, data=None, *, message: str = 'ok', status_code: int = 200):
        from rest_framework.response import Response

        return Response(data if data is not None else {}, status=status_code)


def _payload(request) -> dict[str, Any]:
    return request.data if isinstance(request.data, dict) else {}


PRELABEL_SCOPE_UNLABELED_ONLY = 'unlabeled_only'


def _validate_scope(payload: dict[str, Any]) -> None:
    """MVP 固定只对未标注图片推理（D2 确认）。"""
    scope = payload.get('scope')
    if scope not in (None, PRELABEL_SCOPE_UNLABELED_ONLY):
        raise AoiError(
            CODE_UNPROCESSABLE,
            'scope is fixed to unlabeled_only in MVP',
            fields={'scope': f'must be {PRELABEL_SCOPE_UNLABELED_ONLY}'},
        )


def _validate_model_ref(value: Any) -> str:
    """P1：``model_ref`` 必须能被 ``skillname.parse_model_ref`` 解析（否则 D12 才炸）。"""
    try:
        return str(parse_model_ref(value))
    except ValueError as exc:
        raise AoiError(
            CODE_UNPROCESSABLE,
            'invalid model_ref',
            fields={'model_ref': str(exc)},
        ) from exc


def _validate_route_config(value: Any) -> dict[str, Any] | None:
    """P1：三桶阈值覆盖的形状（契约 §4.3 / 设计 §3）：``0 < recheck_min < auto_min < 1``。"""
    if value is None:
        return None
    if not isinstance(value, dict):
        raise AoiError(
            CODE_UNPROCESSABLE,
            'invalid route_config',
            fields={'route_config': 'must be an object'},
        )
    fields: dict[str, str] = {}
    allowed = ('default', 'classes', 'high_risk_force_recheck', 'low_score_force_manual')
    for key in value:
        if key not in allowed:
            fields[key] = f'unknown key (allowed: {sorted(allowed)})'
    pairs = []
    if 'default' in value:
        pairs.append(('default', value.get('default')))
    classes = value.get('classes')
    if classes is not None:
        if not isinstance(classes, dict):
            fields['classes'] = 'must be an object of {code: {recheck_min, auto_min}}'
        else:
            for code, entry in classes.items():
                pairs.append((f'classes.{code}', entry))
    for name, entry in pairs:
        if not isinstance(entry, dict):
            fields[name] = 'must be an object with recheck_min/auto_min'
            continue
        recheck_min, auto_min = entry.get('recheck_min'), entry.get('auto_min')
        for key, number in (('recheck_min', recheck_min), ('auto_min', auto_min)):
            if isinstance(number, bool) or not isinstance(number, (int, float)):
                fields[f'{name}.{key}'] = 'must be a number'
        if not any(key in fields for key in (f'{name}.recheck_min', f'{name}.auto_min')):
            if not 0 < float(recheck_min) < float(auto_min) < 1:
                fields[name] = 'must satisfy 0 < recheck_min < auto_min < 1'
    if fields:
        raise AoiError(CODE_UNPROCESSABLE, 'invalid route_config', fields=fields)
    return value


def _serialize_task(obj: PrelabelTask) -> dict[str, Any]:
    return {
        'id': obj.id,
        'dataset_id': obj.dataset_id,
        'backend_url': obj.backend_url,
        'model_ref': obj.model_ref,
        'route_config': obj.route_config,
        'status': obj.status,
        'route_bucket': obj.route_bucket,
        'scope': PRELABEL_SCOPE_UNLABELED_ONLY,
        'created_by': obj.created_by,
    }


@extend_schema(tags=['aoi-prelabel'])
class PrelabelTaskListCreateView(AoiAPIView):
    """``GET/POST /api/prelabel/tasks``。"""

    aoi_perm = 'prelabel.view'
    aoi_perm_by_method = {'POST': 'prelabel.create'}

    def get(self, request):
        items = [_serialize_task(obj) for obj in PrelabelTask.objects.all().order_by('id')]
        return self.ok(paginate(request, items))

    def post(self, request):
        get_idempotency_key(request)
        payload = _payload(request)
        _validate_scope(payload)
        dataset_id = payload.get('dataset_id')
        if isinstance(dataset_id, bool) or not isinstance(dataset_id, int):
            raise AoiError(CODE_UNPROCESSABLE, 'invalid dataset_id', fields={'dataset_id': 'required int'})
        # P1：状态由服务端控制（设计 §8：queued → running → succeeded/failed/canceled）
        if payload.get('status') not in (None, '', PrelabelTask.STATUS_QUEUED):
            raise AoiError(
                CODE_UNPROCESSABLE,
                'status is server-controlled',
                fields={'status': 'new prelabel tasks always start as queued'},
            )
        if payload.get('route_bucket') is not None:
            raise AoiError(
                CODE_UNPROCESSABLE,
                'route_bucket is an A-side output',
                fields={'route_bucket': 'read-only'},
            )
        obj = PrelabelTask.objects.create(
            dataset_id=dataset_id,
            backend_url=payload.get('backend_url'),
            model_ref=_validate_model_ref(payload.get('model_ref')),
            route_config=_validate_route_config(payload.get('route_config')),
            status=PrelabelTask.STATUS_QUEUED,
            route_bucket=None,
            created_by=self.user_id,
        )
        return self.ok(_serialize_task(obj))


@extend_schema(tags=['aoi-prelabel'])
class PrelabelTaskDetailView(AoiAPIView):
    """``GET/PUT/DELETE /api/prelabel/tasks/{task_id}``。"""

    aoi_perm = 'prelabel.view'
    aoi_perm_by_method = {'PUT': 'prelabel.update', 'DELETE': 'prelabel.update'}

    def get(self, request, task_id: int):
        obj = PrelabelTask.objects.filter(pk=task_id).first()
        if obj is None:
            return self.ok(
                {
                    'id': task_id,
                    'dataset_id': None,
                    'backend_url': f'/api/prelabel/{task_id}',
                    'model_ref': protocol.MODEL_VERSION,
                    'route_config': None,
                    'status': PrelabelTask.STATUS_QUEUED,
                    'route_bucket': None,
                    'scope': PRELABEL_SCOPE_UNLABELED_ONLY,
                    'created_by': None,
                    'stub': True,
                }
            )
        return self.ok(_serialize_task(obj))

    def put(self, request, task_id: int):
        get_idempotency_key(request)
        payload = _payload(request)
        _validate_scope(payload)
        obj = PrelabelTask.objects.filter(pk=task_id).first()
        if obj is None:
            # D1–D2 stub：未命中返回占位（40401 语义进 D3 工程卫生清单）
            data = {'id': task_id, 'status': PrelabelTask.STATUS_QUEUED, 'stub': True}
            data.update(
                {
                    key: payload.get(key)
                    for key in ('dataset_id', 'backend_url', 'model_ref', 'route_config')
                    if key in payload
                }
            )
            return self.ok(data)
        if payload.get('route_bucket') is not None:
            raise AoiError(
                CODE_UNPROCESSABLE,
                'route_bucket is an A-side output',
                fields={'route_bucket': 'read-only'},
            )
        new_status = payload.get('status')
        if new_status is not None and new_status != obj.status:
            allowed = PrelabelTask.STATUS_TRANSITIONS.get(obj.status, set())
            if new_status not in allowed:
                raise AoiError(
                    CODE_UNPROCESSABLE,
                    'invalid status transition',
                    fields={'status': f'{obj.status} -> {new_status} (allowed: {sorted(allowed)})'},
                )
            obj.status = new_status
        if 'dataset_id' in payload:
            dataset_id = payload.get('dataset_id')
            if isinstance(dataset_id, bool) or not isinstance(dataset_id, int):
                raise AoiError(CODE_UNPROCESSABLE, 'invalid dataset_id', fields={'dataset_id': 'must be an int'})
            obj.dataset_id = dataset_id
        if 'backend_url' in payload:
            obj.backend_url = payload.get('backend_url')
        if 'model_ref' in payload:
            obj.model_ref = _validate_model_ref(payload.get('model_ref'))
        if 'route_config' in payload:
            obj.route_config = _validate_route_config(payload.get('route_config'))
        obj.save()
        return self.ok(_serialize_task(obj))

    def delete(self, request, task_id: int):
        obj = PrelabelTask.objects.filter(pk=task_id).first()
        if obj is not None:
            obj.delete()
        return self.ok({'id': task_id, 'deleted': True, 'stub': obj is None})


@extend_schema(tags=['aoi-prelabel'])
class PrelabelHealthView(PrelabelProtocolView):
    """``GET /api/prelabel/{task_id}/health``。"""

    def get(self, request, task_id: int):
        return self.ok(dict(protocol.HEALTH_RESPONSE))


@extend_schema(tags=['aoi-prelabel'])
class PrelabelSetupView(PrelabelProtocolView):
    """``POST /api/prelabel/{task_id}/setup``。"""

    def post(self, request, task_id: int):
        return self.ok(dict(protocol.SETUP_RESPONSE))


@extend_schema(tags=['aoi-prelabel'])
class PrelabelPredictView(PrelabelProtocolView):
    """``POST /api/prelabel/{task_id}/predict``（D15 接真实推理；当前返回 fixture 同形）。"""

    def post(self, request, task_id: int):
        payload = _payload(request)
        tasks = payload.get('tasks') or []
        return self.ok(protocol.build_predict_response(tasks))


@extend_schema(tags=['aoi-prelabel'])
class PrelabelValidateView(PrelabelProtocolView):
    """``POST /api/prelabel/{task_id}/validate``。"""

    def post(self, request, task_id: int):
        return self.ok(dict(protocol.VALIDATE_RESPONSE))


@extend_schema(tags=['aoi-prelabel'])
class PrelabelWebhookView(PrelabelProtocolView):
    """``POST /api/prelabel/{task_id}/webhook``（预留）。"""

    def post(self, request, task_id: int):
        return self.ok({'status': 'ok', 'reserved': True})
