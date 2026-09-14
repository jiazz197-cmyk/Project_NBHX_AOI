"""aoi_datasets 数据模型（契约 §3.2，逐字段对照）。

所有表位于 PostgreSQL schema ``aoi_datasets``；**仅支持 PostgreSQL**（计划 §2 决策 3）。
"""

from django.db import models

__all__ = [
    'Image',
    'DefectClass',
    'DefectDictVersion',
    'Dataset',
    'DatasetVersion',
    'DatasetItem',
    'PrelabelTask',
]

SCHEMA = 'aoi_datasets'


class Image(models.Model):
    """原图登记（含 B 回传图片）：``images/{md5}.jpg``。"""

    id = models.AutoField(primary_key=True)
    object_key = models.CharField(max_length=128, unique=True)  # images/{md5}.jpg
    md5 = models.CharField(max_length=32)
    source = models.CharField(max_length=24)  # manual_real/camera/reflux_review/prelabel_model_{id}
    station_code = models.CharField(max_length=32, null=True, blank=True)
    seq = models.BigIntegerField(null=True, blank=True)
    captured_at = models.DateTimeField(null=True, blank=True)
    width = models.IntegerField(null=True, blank=True)
    height = models.IntegerField(null=True, blank=True)
    size_bytes = models.BigIntegerField(null=True, blank=True)
    qc_status = models.CharField(max_length=16, default='pending')  # pending/ok/rejected
    qc_reason = models.CharField(max_length=128, null=True, blank=True)
    status = models.CharField(max_length=16, default='active')
    trace_id = models.CharField(max_length=64, null=True, blank=True)

    class Meta:
        app_label = 'aoi_datasets'
        db_table = '"aoi_datasets"."image"'

    def __str__(self) -> str:
        return self.object_key


class DefectClass(models.Model):
    """缺陷字典条目：``code = object_fault_type_XX``。"""

    id = models.AutoField(primary_key=True)
    code = models.CharField(max_length=32, unique=True)
    name_cn = models.CharField(max_length=64)
    risk_level = models.SmallIntegerField()  # 3=高 2=中 1=低
    aliases = models.JSONField(default=list)
    active = models.BooleanField(default=True)

    class Meta:
        app_label = 'aoi_datasets'
        db_table = '"aoi_datasets"."defect_class"'

    def __str__(self) -> str:
        return self.code


class DefectDictVersion(models.Model):
    """缺陷字典发布版本：``snapshot = {labels:{code:{index,color}}}``。"""

    id = models.AutoField(primary_key=True)
    version = models.CharField(max_length=16)
    snapshot = models.JSONField(default=dict)
    published_by = models.IntegerField(null=True, blank=True)
    published_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        app_label = 'aoi_datasets'
        db_table = '"aoi_datasets"."defect_dict_version"'

    def __str__(self) -> str:
        return self.version


class Dataset(models.Model):
    """数据集（对应 LS project）。"""

    id = models.AutoField(primary_key=True)
    name = models.CharField(max_length=128, null=True, blank=True)
    cur_version = models.CharField(max_length=16, null=True, blank=True)
    ls_project_id = models.IntegerField(null=True, blank=True)
    created_by = models.IntegerField(null=True, blank=True)

    class Meta:
        app_label = 'aoi_datasets'
        db_table = '"aoi_datasets"."dataset"'

    def __str__(self) -> str:
        return self.name or f'dataset-{self.pk}'


class DatasetVersion(models.Model):
    """数据集版本：``UNIQUE(dataset_id, version)``。

    ``status`` 保留契约原语义（draft/published/archived）；
    ``phase`` 承载流程状态（D2 三桶复审设计确认）。
    """

    PHASE_DRAFT = 'draft'
    PHASE_LABELING = 'labeling'
    PHASE_TRAINING = 'training'
    PHASE_PRELABELING = 'prelabeling'
    PHASE_REVIEWING = 'reviewing'
    PHASE_PUBLISHED = 'published'
    PHASE_ARCHIVED = 'archived'
    PHASE_CHOICES = (
        (PHASE_DRAFT, 'draft'),
        (PHASE_LABELING, 'labeling'),
        (PHASE_TRAINING, 'training'),
        (PHASE_PRELABELING, 'prelabeling'),
        (PHASE_REVIEWING, 'reviewing'),
        (PHASE_PUBLISHED, 'published'),
        (PHASE_ARCHIVED, 'archived'),
    )

    STATUS_DRAFT = 'draft'
    STATUS_PUBLISHED = 'published'
    STATUS_ARCHIVED = 'archived'
    STATUS_CHOICES = (
        (STATUS_DRAFT, 'draft'),
        (STATUS_PUBLISHED, 'published'),
        (STATUS_ARCHIVED, 'archived'),
    )

    id = models.AutoField(primary_key=True)
    dataset_id = models.IntegerField()
    version = models.CharField(max_length=16)
    status = models.CharField(max_length=16, default=STATUS_DRAFT, choices=STATUS_CHOICES)
    phase = models.CharField(max_length=16, default=PHASE_DRAFT, choices=PHASE_CHOICES)  # D2 三桶复审流程状态
    split_seed = models.IntegerField(null=True, blank=True)
    split_stats = models.JSONField(null=True, blank=True)
    class_dist = models.JSONField(null=True, blank=True)
    source_stats = models.JSONField(null=True, blank=True)
    dict_version = models.CharField(max_length=16, null=True, blank=True)
    note = models.TextField(null=True, blank=True)
    created_by = models.IntegerField(null=True, blank=True)

    class Meta:
        app_label = 'aoi_datasets'
        db_table = '"aoi_datasets"."dataset_version"'
        constraints = [models.UniqueConstraint(fields=['dataset_id', 'version'], name='uniq_dataset_version')]

    def __str__(self) -> str:
        return f'{self.dataset_id}/{self.version}'


class DatasetItem(models.Model):
    """版本-图片-子集：复合主键 ``(version_id, image_id)``。"""

    pk = models.CompositePrimaryKey('version_id', 'image_id')
    version_id = models.IntegerField()
    image_id = models.IntegerField()
    subset = models.CharField(max_length=8)  # train/val/test

    class Meta:
        app_label = 'aoi_datasets'
        db_table = '"aoi_datasets"."dataset_item"'


class PrelabelTask(models.Model):
    """预标任务（A 自实现 ML backend，契约 §3.2/§4.3）。

    状态机（设计 §8，服务端控制）：``queued → running → succeeded/failed/canceled``。
    """

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

    #: 允许的状态迁移（P1：客户端只能推进到合法状态）
    STATUS_TRANSITIONS = {
        STATUS_QUEUED: {STATUS_RUNNING, STATUS_FAILED, STATUS_CANCELED},
        STATUS_RUNNING: {STATUS_SUCCEEDED, STATUS_FAILED, STATUS_CANCELED},
        STATUS_SUCCEEDED: set(),
        STATUS_FAILED: set(),
        STATUS_CANCELED: set(),
    }

    id = models.AutoField(primary_key=True)
    dataset_id = models.IntegerField(null=True, blank=True)
    backend_url = models.CharField(max_length=256, null=True, blank=True)
    model_ref = models.CharField(max_length=64, null=True, blank=True)
    route_config = models.JSONField(null=True, blank=True)  # 三桶阈值（默认取自 model.yaml recommended）
    status = models.CharField(max_length=16, default=STATUS_QUEUED, choices=STATUS_CHOICES)
    route_bucket = models.JSONField(null=True, blank=True)
    created_by = models.IntegerField(null=True, blank=True)

    class Meta:
        app_label = 'aoi_datasets'
        db_table = '"aoi_datasets"."prelabel_task"'
