"""aoi.common 通用 serializer 占位。

D1–D2 stub 的入参校验在视图/服务层完成；D4 起逐步替换为 DRF Serializer。
"""

from rest_framework import serializers

__all__ = ['EmptySerializer']


class EmptySerializer(serializers.Serializer):
    pass
