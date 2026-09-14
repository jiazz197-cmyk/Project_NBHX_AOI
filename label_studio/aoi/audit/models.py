"""aoi_audit 数据模型（契约 §3.5）。"""

from django.db import models

__all__ = ['AuditLog']


class AuditLog(models.Model):
    """关键操作审计（角色/授权、模型发布、训练、导出等）。"""

    id = models.BigAutoField(primary_key=True)
    actor_id = models.IntegerField(null=True, blank=True)
    action = models.CharField(max_length=64, null=True, blank=True)
    object_type = models.CharField(max_length=32, null=True, blank=True)
    object_id = models.CharField(max_length=64, null=True, blank=True)
    detail = models.JSONField(null=True, blank=True)
    request_id = models.CharField(max_length=64, null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        app_label = 'aoi_audit'
        db_table = '"aoi_audit"."audit_log"'

    def __str__(self) -> str:
        return f'{self.action}@{self.pk}'
