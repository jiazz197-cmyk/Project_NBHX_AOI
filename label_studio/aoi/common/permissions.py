"""aoi DRF 权限基类与权限点工厂（契约 §3.1）。

每个 aoi 视图通过 `aoi_perm` / `aoi_perm_by_method` 声明自己对应的权限点，判定由
:class:`AoiPermission` 经 :func:`aoi.core.authz.resolve_user_perms` 完成
（`user_role → role_permission → permission.code`）。

用法（**不要**直接把实例放进 ``permission_classes``——DRF 会无参实例化每一项）::

    class ModelPublishView(AoiAPIView):
        permission_classes = [aoi_permission('training.publish')]

``has_permission`` 仍然要求登录（匿名 → 40100）；``has_object_permission`` 与
``has_permission`` **同判定**——对象级规则（复审认领归属等）留在视图层业务校验。
"""

from __future__ import annotations

from typing import Any

from rest_framework.permissions import BasePermission, IsAuthenticated

__all__ = ['AoiPermission', 'aoi_permission', 'IsAuthenticatedAoi']


class AoiPermission(BasePermission):
    """模块级权限点判定（``perm_code`` 由 :func:`aoi_permission` 固化在子类上）。"""

    #: 由 :func:`aoi_permission` 生成的子类覆盖；``None`` 表示"仅需登录"
    perm_code: str | None = None

    def has_permission(self, request, view) -> bool:
        user = getattr(request, 'user', None)
        if user is None or not getattr(user, 'is_authenticated', False):
            return False
        if self.perm_code is None:
            return True

        from aoi.core.authz import resolve_user_perms

        return self.perm_code in resolve_user_perms(getattr(user, 'id', None))

    def has_object_permission(self, request, view, obj) -> bool:
        return self.has_permission(request, view)

    def __repr__(self) -> str:  # pragma: no cover - 调试用
        return f'{type(self).__name__}({self.perm_code!r})'


#: 工厂产物缓存：``aoi_perm`` 在每请求的 ``get_permissions()`` 里都会调用，避免重复 type()
_PERMISSION_CLASSES: dict[str, type[AoiPermission]] = {}


def aoi_permission(perm_code: str) -> type[AoiPermission]:
    """生成声明了 ``perm_code`` 的权限类（可安全放进 ``permission_classes``）。

    未知权限点在此**立即报错**（配置期错误，导入即失败，不留到运行期）：

    >>> class V(AoiAPIView):
    ...     permission_classes = [aoi_permission('training.publish')]
    """
    if not isinstance(perm_code, str) or not perm_code:
        raise ValueError('perm_code must be a non-empty string')

    cached = _PERMISSION_CLASSES.get(perm_code)
    if cached is not None:
        return cached

    from aoi.core.permissions import is_known_permission

    if not is_known_permission(perm_code):
        raise AssertionError(f'unknown aoi permission code: {perm_code!r}')

    cls = type(
        f'AoiPermission_{perm_code.replace(".", "_")}',
        (AoiPermission,),
        {'perm_code': perm_code},
    )
    _PERMISSION_CLASSES[perm_code] = cls
    return cls


#: 常用别名：仅要求登录（aoi 视图统一显式声明，避免继承全局 HasObjectPermission）
IsAuthenticatedAoi: Any = IsAuthenticated
