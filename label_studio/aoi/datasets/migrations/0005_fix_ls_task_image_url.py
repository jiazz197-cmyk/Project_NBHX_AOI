"""数据修复：既有 LS 任务 ``data.image`` 的裸对象键 → 同源 ``/data/`` URL。

D5 实测：``tasks.py::_image_value`` 曾在云存储（MinIO）分支直接落存储键
（``upload/<project>/<uuid8>-<filename>``），LSF 按相对路径解析 → 404 →
标注页全部图片 ERR_LOADING_HTTP。本迁移把「值与 ``FileUpload.file`` 精确匹配
且还不是绝对 URL」的任务改写为 ``MEDIA_URL`` 前缀的同源代理路径（与 tasks.py
新逻辑一致）。只前滚不回滚（改写是幂等的纯 URL 规范化）。
"""

from django.conf import settings
from django.db import migrations


def fix_task_image_urls(apps, schema_editor):
    Task = apps.get_model('tasks', 'Task')
    FileUpload = apps.get_model('data_import', 'FileUpload')

    media_url = settings.MEDIA_URL or '/data/'
    script_name = getattr(settings, 'FORCE_SCRIPT_NAME', '') or ''
    for task in Task.objects.exclude(data={}).iterator():
        data = dict(task.data or {})
        image = data.get('image')
        # 只处理「裸对象键」：非空字符串、非绝对路径/URL，且确实对应一次 LS 上传
        if not isinstance(image, str) or not image:
            continue
        if image.startswith('/') or '://' in image:
            continue
        if not FileUpload.objects.filter(file=image).exists():
            continue
        url = f"{media_url}{image.lstrip('/')}"
        if script_name and not url.startswith(f"{script_name}/"):
            url = f"{script_name}{url}"
        data['image'] = url
        Task.objects.filter(pk=task.pk).update(data=data)


class Migration(migrations.Migration):

    dependencies = [
        ('aoi_datasets', '0004_import_job'),
        # RunPython 里要摸 tasks.Task / data_import.FileUpload 历史模型，必须显式依赖其迁移节点，
        # 否则迁移期 apps 注册表里没有这两个 app（LookupError: No installed app with label 'tasks'）
        ('tasks', '0062_task_data_trgm_idx_async'),
        ('data_import', '0002_alter_fileupload_file'),
    ]

    operations = [
        migrations.RunPython(fix_task_image_urls, migrations.RunPython.noop),
    ]
