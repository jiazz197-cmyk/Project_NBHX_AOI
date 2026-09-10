"""aoi_review 数据模型（契约 §3.4/§10）。

复审自研（D2 裁定，非 LS Review）：主流程是预标三桶判定
``verdict ∈ {auto_pass, recheck, manual}`` → ``recheck``/``manual`` 生成
``review_workitem`` 进入人工复审；B 回传的 suspicious findings 同样落
``inspection_fact`` + ``review_workitem``，共用同一队列。

检测事实与坏图的**写入**来自 B 的 ``/api/ingest/findings``；本域接口提供队列/认领/终裁/建议/坏图。
``inspection_fact`` 与 ``bad_image`` 各自 ``UNIQUE(station_code, seq)``（回传幂等）。
"""

from django.db import models

__all__ = ['InspectionFact', 'ReviewWorkitem', 'FinalFact', 'FeedbackSuggestion', 'BadImage']

SCHEMA = 'aoi_review'


class InspectionFact(models.Model):
    """检测事实（可疑图回传）：``UNIQUE(station_code, seq)``。"""

    id = models.BigAutoField(primary_key=True)
    image_id = models.IntegerField(null=True, blank=True)
    station_code = models.CharField(max_length=32)
    station_name = models.CharField(max_length=64, null=True, blank=True)
    seq = models.BigIntegerField(null=True, blank=True)
    channel_id = models.IntegerField(null=True, blank=True)
    template_version = models.IntegerField(null=True, blank=True)
    result_json = models.JSONField(default=dict)  # {boxes, verdict, verdict_reasons, tiling_meta}
    verdict = models.CharField(max_length=16, null=True, blank=True)  # 冗余便于查询
    instance_code = models.CharField(max_length=32, null=True, blank=True)
    latency_ms = models.IntegerField(null=True, blank=True)
    status = models.CharField(max_length=16, default='initial')  # initial/rechecking/finalized
    captured_at = models.DateTimeField(null=True, blank=True)
    received_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        app_label = 'aoi_review'
        db_table = '"aoi_review"."inspection_fact"'
        constraints = [models.UniqueConstraint(fields=['station_code', 'seq'], name='uniq_fact_station_seq')]

    def __str__(self) -> str:
        return f'fact-{self.pk}'


class ReviewWorkitem(models.Model):
    """复审工作项（D2 三桶复审方案 A：泛化，支持 B 回传 + A 预标）。

    - ``source=ingest``：B 回传 suspicious，``fact_id`` 指向 ``inspection_fact``；
    - ``source=prelabel``：A 预标三桶，携带 ``dataset_version_id``/``image_id``/``ls_task_id``/
      ``ls_prediction_id``/``model_ref``/``bucket``/``verdict``/``bucket_reason``；
    - 高桶（``auto_pass``）由系统自动接受并写 auto-finalized 记录，低桶 ``forced=true`` 强制人工重标。
    """

    SOURCE_INGEST = 'ingest'
    SOURCE_PRELABEL = 'prelabel'
    SOURCE_CHOICES = ((SOURCE_INGEST, 'ingest'), (SOURCE_PRELABEL, 'prelabel'))

    BUCKET_HIGH = 'high'
    BUCKET_MEDIUM = 'medium'
    BUCKET_LOW = 'low'
    BUCKET_CHOICES = ((BUCKET_HIGH, 'high'), (BUCKET_MEDIUM, 'medium'), (BUCKET_LOW, 'low'))

    STATUS_PENDING = 'pending'
    STATUS_PROCESSING = 'processing'
    STATUS_FINALIZED = 'finalized'
    STATUS_FAILED = 'failed'
    STATUS_CHOICES = (
        (STATUS_PENDING, 'pending'),
        (STATUS_PROCESSING, 'processing'),
        (STATUS_FINALIZED, 'finalized'),
        (STATUS_FAILED, 'failed'),
    )

    VERDICT_CHOICES = (('auto_pass', 'auto_pass'), ('recheck', 'recheck'), ('manual', 'manual'))
    ROUTE_MANUAL = 'manual'
    ROUTE_VLM = 'vlm'
    ROUTE_CHOICES = ((ROUTE_VLM, 'vlm'), (ROUTE_MANUAL, 'manual'))

    #: ``verdict`` → UI 三桶（唯一映射来源，ingest / prelabel / 复审共用）
    VERDICT_TO_BUCKET = {
        'auto_pass': BUCKET_HIGH,
        'recheck': BUCKET_MEDIUM,
        'manual': BUCKET_LOW,
    }

    @classmethod
    def bucket_for_verdict(cls, verdict: str | None) -> str | None:
        """``verdict`` → ``bucket``（未知值返回 ``None``，不臆造桶）。"""
        return cls.VERDICT_TO_BUCKET.get(verdict or '')

    id = models.BigAutoField(primary_key=True)
    fact_id = models.BigIntegerField(null=True, blank=True)  # source=ingest 时指向 inspection_fact
    source = models.CharField(max_length=16, default=SOURCE_INGEST, choices=SOURCE_CHOICES)
    dataset_version_id = models.IntegerField(null=True, blank=True)  # source=prelabel
    image_id = models.IntegerField(null=True, blank=True)  # aoi_datasets.image（可选）
    ls_task_id = models.IntegerField(null=True, blank=True)  # LS task id（打开编辑器用）
    ls_prediction_id = models.BigIntegerField(null=True, blank=True)  # LS Prediction.id
    model_ref = models.CharField(max_length=64, null=True, blank=True)
    bucket = models.CharField(max_length=8, null=True, blank=True, choices=BUCKET_CHOICES)
    verdict = models.CharField(max_length=16, null=True, blank=True, choices=VERDICT_CHOICES)
    bucket_reason = models.JSONField(null=True, blank=True)  # {reasons,scores,thresholds}
    forced = models.BooleanField(default=False)  # 低桶强制人工
    route = models.CharField(max_length=16, choices=ROUTE_CHOICES)  # vlm/manual
    recheck_result = models.JSONField(null=True, blank=True)  # 预留：VLM 复审输出
    hv_key = models.TextField(null=True, blank=True)  # 预留：高价值数据桶对象键
    status = models.CharField(max_length=16, default=STATUS_PENDING, choices=STATUS_CHOICES)
    assignee_id = models.IntegerField(null=True, blank=True)
    final_verdict = models.CharField(max_length=32, null=True, blank=True)
    final_reason = models.CharField(max_length=16, null=True, blank=True)
    finalized_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        app_label = 'aoi_review'
        db_table = '"aoi_review"."review_workitem"'
        ordering = ['id']
        indexes = [
            # 设计 §4.2：复审队列按 (来源/版本, 桶, 状态) 检索
            models.Index(fields=['source', 'status'], name='idx_workitem_source_status'),
            models.Index(fields=['dataset_version_id', 'bucket', 'status'], name='idx_workitem_ds_bucket_status'),
            models.Index(fields=['fact_id', 'source'], name='idx_workitem_fact_source'),
        ]

    def __str__(self) -> str:
        return f'workitem-{self.pk}'


class FinalFact(models.Model):
    """复审终裁结果（D2 三桶复审：补充 workitem/预标/annotation 关联）。"""

    id = models.BigAutoField(primary_key=True)
    fact_id = models.BigIntegerField(null=True, blank=True)
    workitem_id = models.BigIntegerField(null=True, blank=True)
    source = models.CharField(max_length=16, null=True, blank=True)
    dataset_version_id = models.IntegerField(null=True, blank=True)
    image_id = models.IntegerField(null=True, blank=True)
    ls_task_id = models.IntegerField(null=True, blank=True)
    annotation_id = models.BigIntegerField(null=True, blank=True)  # 复审后写回的 LS Annotation
    action = models.CharField(
        max_length=24, null=True, blank=True
    )  # accepted_prediction/edited/relabeled/no_defect/unlabelable
    verdict = models.CharField(max_length=32, null=True, blank=True)  # defect_confirmed/false_alarm/uncertain
    class_id = models.IntegerField(null=True, blank=True)
    boxes = models.JSONField(null=True, blank=True)
    note = models.TextField(null=True, blank=True)  # 复审备注（与 final_reason 的原因码分开）
    decided_by = models.IntegerField(null=True, blank=True)
    decided_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        app_label = 'aoi_review'
        db_table = '"aoi_review"."final_fact"'
        constraints = [
            # P1：一个 workitem 至多一条终裁（NULL 不参与唯一性，PG 语义）
            models.UniqueConstraint(fields=['workitem_id'], name='uniq_final_fact_workitem'),
        ]


class FeedbackSuggestion(models.Model):
    """R1~R4 回流建议。"""

    id = models.AutoField(primary_key=True)
    workitem_id = models.BigIntegerField(null=True, blank=True)
    image_id = models.IntegerField(null=True, blank=True)
    rule_code = models.CharField(max_length=8, null=True, blank=True)  # R1~R4
    suggestion = models.TextField(null=True, blank=True)
    status = models.CharField(max_length=16, default='suggested')  # suggested/confirmed/rejected
    confirmed_by = models.IntegerField(null=True, blank=True)
    confirmed_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        app_label = 'aoi_review'
        db_table = '"aoi_review"."feedback_suggestion"'


class BadImage(models.Model):
    """坏图清单（B 回传）：``UNIQUE(station_code, seq)``。"""

    id = models.AutoField(primary_key=True)
    station_code = models.CharField(max_length=32)
    station_name = models.CharField(max_length=64, null=True, blank=True)
    seq = models.BigIntegerField(null=True, blank=True)
    captured_at = models.DateTimeField(null=True, blank=True)
    error_code = models.CharField(max_length=16, null=True, blank=True)
    image_key = models.TextField(null=True, blank=True)
    instance_code = models.CharField(max_length=32, null=True, blank=True)
    handled = models.BooleanField(default=False)
    handled_by = models.IntegerField(null=True, blank=True)
    note = models.TextField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        app_label = 'aoi_review'
        db_table = '"aoi_review"."bad_image"'
        constraints = [models.UniqueConstraint(fields=['station_code', 'seq'], name='uniq_bad_station_seq')]

    def __str__(self) -> str:
        return f'bad-{self.pk}'
