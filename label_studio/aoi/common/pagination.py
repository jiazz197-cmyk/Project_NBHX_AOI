"""分页约定（契约 §2.5）：``?page=&page_size=`` → ``{total, items}``。"""

from __future__ import annotations

from typing import Any, Iterable, Sequence

from rest_framework.request import Request

__all__ = ['DEFAULT_PAGE_SIZE', 'MAX_PAGE_SIZE', 'get_page_params', 'paginate']

DEFAULT_PAGE_SIZE = 20
MAX_PAGE_SIZE = 200


def _positive_int(value: Any, default: int) -> int:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return default
    return parsed if parsed > 0 else default


def get_page_params(request: Request) -> tuple[int, int]:
    """返回 ``(page, page_size)``；非法值回落默认。"""
    page = _positive_int(request.query_params.get('page'), 1)
    page_size = _positive_int(request.query_params.get('page_size'), DEFAULT_PAGE_SIZE)
    return page, min(page_size, MAX_PAGE_SIZE)


def paginate(request: Request, items: Iterable[Any] | Sequence[Any]) -> dict[str, Any]:
    """对内存列表分页，返回 ``{total, items}``。"""
    materialized = list(items)
    page, page_size = get_page_params(request)
    start = (page - 1) * page_size
    return {
        'total': len(materialized),
        'items': materialized[start : start + page_size],
    }
