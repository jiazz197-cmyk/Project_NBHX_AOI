"""aoi DRF 权限基类与权限点工厂（契约 §3.1）。

D1–D2：**恒放行**（RBAC 四表与判定属 D4，见平台 A 契约 §3.1）；但每个视图必须通过
:func:`aoi_permission` 声明自己对应的权限点，D4 只需改 :meth:`AoiPermission.has_permission`
的实现，不必回头给几十个视图补注解。

用法（**不要**直接把实例放进 ``permission_classes``——DRF 会无参实例化每一项）::

    class ModelPublishView(AoiAPIView):
        permission_classes = [aoi_permission('training.publish')]

``has_permission`` 仍然要求登录（匿名 → 40100，与 D1–D2 的 ``IsAuthenticated`` 行为一致）。
"""

from __future__ import annotations

from typing import Any

from rest_framework.permissions import BasePermission, IsAuthenticated

__all__ = ['AoiPermission', 'aoi_permission', 'IsAuthenticatedAoi']


class AoiPermission(BasePermission):
    """模块级权限点占位（``perm_code`` 由 :func:`aoi_permission` 固化在子类上）。"""

    #: 由 :func:`aoi_permission` 生成的子类覆盖
    perm_code: str | None = None

    # D4: 接 aoi_core RBAC（user_role → role_permission → permission.code），结果按用户缓存 5 分钟
    def has_permission(self, request, view) -> bool:
        return bool(getattr(request.user, 'is_authenticated', False))  # D4: 追加 perm_code 判定

    def has_object_permission(self, request, view, obj) -> bool:
        return bool(getattr(request.user, 'is_authenticated', False))  # D4: 追加 perm_code 判定

    def __repr__(self) -> str:  # pragma: no cover - 调试用
        return f'{type(self).__name__}({self.perm_code!r})'


def aoi_permission(perm_code: str) -> type[AoiPermission]:
    """生成声明了 ``perm_code`` 的权限类（可安全放进 ``permission_classes``）。

    >>> class V(AoiAPIView):
    ...     permission_classes = [aoi_permission('training.publish')]
    """
    if not isinstance(perm_code, str) or not perm_code:
        raise ValueError('perm_code must be a non-empty string')
    return type(
        f'AoiPermission_{perm_code.replace(".", "_")}',
        (AoiPermission,),
        {'perm_code': perm_code},
    )


#: 常用别名：仅要求登录（aoi 视图统一显式声明，避免继承全局 HasObjectPermission）
IsAuthenticatedAoi: Any = IsAuthenticated
