"""aoi.audit 端点：``GET /api/system/audit``（契约 §4.5）。"""

from __future__ import annotations

from aoi.audit.models import AuditLog
from aoi.common.pagination import paginate
from aoi.common.views import AoiAPIView
from drf_spectacular.utils import extend_schema


@extend_schema(tags=['aoi-system'])
class AuditListView(AoiAPIView):
    """``GET /api/system/audit``（system.audit，D4 前不拦截）。"""

    aoi_perm = 'system.audit'

    def get(self, request):
        qs = AuditLog.objects.all().order_by('-id')
        action = request.query_params.get('action')
        object_type = request.query_params.get('object_type')
        if action:
            qs = qs.filter(action=action)
        if object_type:
            qs = qs.filter(object_type=object_type)
        items = [
            {
                'id': obj.id,
                'actor_id': obj.actor_id,
                'action': obj.action,
                'object_type': obj.object_type,
                'object_id': obj.object_id,
                'detail': obj.detail,
                'request_id': obj.request_id,
                'created_at': obj.created_at.isoformat() if obj.created_at else None,
            }
            for obj in qs
        ]
        return self.ok(paginate(request, items))
