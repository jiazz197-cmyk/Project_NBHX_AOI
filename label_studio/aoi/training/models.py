"""aoi_training 数据模型（契约 §3.3）。

D1 必须就位四表：``base_model`` / ``preset`` / ``train_job`` / ``model``；
``model_publish`` 于 D2（T2.1）落表，D3 只做发布 stub（计划 §2 决策 7）。
"""

from django.db import models
from skillname import SkillName

__all__ = ['BaseModel', 'Preset', 'TrainJob', 'Model', 'ModelPublish']

SCHEMA = 'aoi_training'


class BaseModel(models.Model):
    """基础权重（如 ``yolov8s.pt``）。"""

    id = models.AutoField(primary_key=True)
    name = models.CharField(max_length=64, unique=True)
    framework = models.CharField(max_length=16)  # yolo
    task_type = models.CharField(max_length=32, default=SkillName.OBJECT_DETECTION.value)  # skillname: ObjectDetection
    weights_key = models.TextField(null=True, blank=True)
    params_schema = models.JSONField(null=True, blank=True)
    active = models.BooleanField(default=True)

    class Meta:
        app_label = 'aoi_training'
        db_table = '"aoi_training"."base_model"'

    def __str__(self) -> str:
        return self.name


class Preset(models.Model):
    """训练预置方案（含 class_subset）。"""

    id = models.AutoField(primary_key=True)
    name = models.CharField(max_length=64, unique=True)
    framework = models.CharField(max_length=16)
    task_type = models.CharField(max_length=32, default=SkillName.OBJECT_DETECTION.value)
    base_model = models.CharField(max_length=64, null=True, blank=True)
    params = models.JSONField(null=True, blank=True)
    class_subset = models.JSONField(null=True, blank=True)
    created_by = models.IntegerField(null=True, blank=True)
    active = models.BooleanField(default=True)

    class Meta:
        app_label = 'aoi_training'
        db_table = '"aoi_training"."preset"'

    def __str__(self) -> str:
        return self.name


class TrainJob(models.Model):
    """训练任务：``queued → running → succeeded/failed/canceled``。"""

    STATUS_QUEUED = 'queued'
    STATUS_RUNNING = 'running'
    STATUS_SUCCEEDED = 'succeeded'
    STATUS_FAILED = 'failed'
    STATUS_CANCELED = 'canceled'
    STATUS_CHOICES = (
        (STATUS_QUEUED, 'queued'),
        (STATUS_RUNNING, 'running'),
        (STATUS_SUCCEEDED, 'succeeded'),
        (STATUS_FAILED, 'failed'),
        (STATUS_CANCELED, 'canceled'),
    )

    id = models.AutoField(primary_key=True)
    dataset_version = models.CharField(max_length=16)
    framework = models.CharField(max_length=16)  # MVP 仅 yolo
    task_type = models.CharField(max_length=32, default=SkillName.OBJECT_DETECTION.value)  # skillname
    preset = models.JSONField(default=dict)  # 含 class_subset
    status = models.CharField(max_length=16, default=STATUS_QUEUED, choices=STATUS_CHOICES)
    celery_task_id = models.CharField(max_length=128, null=True, blank=True)
    metrics = models.JSONField(null=True, blank=True)
    artifact_path = models.TextField(null=True, blank=True)
    error_message = models.TextField(null=True, blank=True)
    created_by = models.IntegerField(null=True, blank=True)
    started_at = models.DateTimeField(null=True, blank=True)
    finished_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        app_label = 'aoi_training'
        db_table = '"aoi_training"."train_job"'

    def __str__(self) -> str:
        return f'job-{self.pk}'


class Model(models.Model):
    """模型注册表：``version = {seq}-{framework}@ds{dataset_version}`` 唯一。"""

    LIFECYCLE_CANDIDATE = 'candidate'
    LIFECYCLE_APPROVED = 'approved'
    LIFECYCLE_PUBLISHED = 'published'
    LIFECYCLE_RETIRED = 'retired'

    GATE_PENDING = 'pending'
    GATE_PASSED = 'passed'
    GATE_FAILED = 'failed'

    id = models.AutoField(primary_key=True)
    version = models.CharField(max_length=64, unique=True)  # model_ref
    framework = models.CharField(max_length=16, null=True, blank=True)
    dataset_version = models.CharField(max_length=16, null=True, blank=True)
    task_type = models.CharField(
        max_length=32, default=SkillName.OBJECT_DETECTION.value
    )  # ObjectDetection（skillname）
    base_model = models.CharField(max_length=64, null=True, blank=True)
    weights_key = models.TextField(null=True, blank=True)
    class_names = models.JSONField(default=list)  # 索引序：["object_fault_type_01", ...]
    cover_classes = models.JSONField(default=list)
    precision = models.CharField(max_length=8, default='fp32')
    input_shape = models.JSONField(null=True, blank=True)
    tensor_names = models.JSONField(null=True, blank=True)  # {"input":"images","output":"output0"}
    eval_metrics = models.JSONField(null=True, blank=True)
    gate_status = models.CharField(max_length=16, default=GATE_PENDING)  # pending/passed/failed
    llm_review = models.JSONField(null=True, blank=True)  # 预留：LLM 参数复审报告
    lifecycle = models.CharField(max_length=16, default=LIFECYCLE_CANDIDATE)
    config_snapshot = models.JSONField(null=True, blank=True)  # 含 model.yaml 快照

    class Meta:
        app_label = 'aoi_training'
        db_table = '"aoi_training"."model"'

    def __str__(self) -> str:
        return self.version


class ModelPublish(models.Model):
    """模型发布到镜像仓库（A→registry，契约 §3.3 / 跨平台契约 §2.4）。"""

    STATUS_QUEUED = 'queued'
    STATUS_BUILDING = 'building'
    STATUS_PUSHING = 'pushing'
    STATUS_PUBLISHED = 'published'
    STATUS_FAILED = 'failed'
    STATUS_CHOICES = (
        (STATUS_QUEUED, 'queued'),
        (STATUS_BUILDING, 'building'),
        (STATUS_PUSHING, 'pushing'),
        (STATUS_PUBLISHED, 'published'),
        (STATUS_FAILED, 'failed'),
    )

    id = models.AutoField(primary_key=True)
    # P1 修复：唯一性按 (model_ref, tag)，否则 fp16 的 `3-yolo-ds1-fp16` 永远发不出去
    # （跨平台契约 §2.2 允许同 model_ref 的 fp32/fp16 两个 tag；§4.1 幂等键 = model_ref + tag）
    model_ref = models.CharField(max_length=64)
    registry = models.CharField(max_length=128)
    image = models.CharField(max_length=256)
    tag = models.CharField(max_length=128)
    digest = models.CharField(max_length=128, null=True, blank=True)
    status = models.CharField(max_length=16, default=STATUS_QUEUED, choices=STATUS_CHOICES)
    attempts = models.IntegerField(default=0)
    error_message = models.TextField(null=True, blank=True)
    # 软删（D7）：只清 A 侧管理记录，仓库镜像与 tag 一律保留（B 仍可拉取/回滚）
    deleted_at = models.DateTimeField(null=True, blank=True)
    deleted_by = models.IntegerField(null=True, blank=True)
    published_by = models.IntegerField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    published_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        app_label = 'aoi_training'
        db_table = '"aoi_training"."model_publish"'
        constraints = [
            models.UniqueConstraint(fields=['model_ref', 'tag'], name='uniq_model_publish_ref_tag'),
        ]

    def __str__(self) -> str:
        return self.model_ref
