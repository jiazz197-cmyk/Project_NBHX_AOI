"""D5 收尾：MinIO 模式下 ``file.url`` 输出同源相对路径。

本部署 MinIO 关签名（``AWS_QUERYSTRING_AUTH=False``），图片统一走 LS 自带的
同源鉴权代理路由 ``data/upload/<path>``（``UploadedFileResponse``）。但上游
``S3Boto3Storage.url`` 固定拼 ``{protocol}//{custom_domain}/{key}``，而 MinIO
设置块按 ``HOSTNAME`` 计算 ``custom_domain``——``HOSTNAME`` 为空时得到
``https:///data/upload/...`` 这类**空主机绝对地址**；任务读取期
``Task.resolve_uris``（tasks/models.py）会把它换进任务 ``data.image``，LSF 按该
绝对地址解析 → ``ERR_LOADING_HTTP``（标注页图片全挂）。

因此本类对 ``upload/`` 前缀的存储对象键（FileUpload 命名空间）输出
``{MEDIA_URL}{key}`` 相对路径（默认 ``/data/upload/<key>``），随页面 origin 解析、
与代理路由对齐；其余媒体名（export/avatars 等，LS 均走专用 API 端点下载）原样
回退上游 ``url()``，行为不变。
"""

from __future__ import annotations

from django.conf import settings
from storages.backends.s3boto3 import S3Boto3Storage


class SameOriginS3Boto3Storage(S3Boto3Storage):
    """MinIO 后端的同源 URL 变体（仅接管 ``upload/`` 对象键的 ``url()``）。

    其余行为（endpoint、bucket、签名开关等）全部继承上游 ``S3Boto3Storage``。
    """

    def url(self, name, parameters=None, expire=None, http_method=None):
        if not isinstance(name, str) or not name or name.startswith(('http://', 'https://', '/')):
            return name
        if settings.UPLOAD_DIR and name.startswith(f'{settings.UPLOAD_DIR}/'):
            prefix = settings.MEDIA_URL or '/data/'
            return f'{prefix}{name}'
        return super().url(name, parameters=parameters, expire=expire, http_method=http_method)
