import re
import threading
from typing import Optional

try:
    from django.conf import settings
except Exception:  # pragma: no cover
    settings = None

_debug_local = threading.local()


def _normalize_book(book: Optional[str]) -> str:
    if not book:
        return ''
    return re.sub(r'[\s_]+', '', str(book)).lower()


def set_debug_context(request) -> None:
    """Set per-request verbose debug context from query params.

    Enabled only when ENABLE_VERBOSE_DEBUG is True and a debug flag is present.
    Optional filters: debug_book, debug_chapter, debug_verse.
    """
    if not settings or not getattr(settings, 'ENABLE_VERBOSE_DEBUG', False):
        _debug_local.enabled = False
        _debug_local.filters = {}
        return

    debug_flag = request.GET.get('_debug') or request.GET.get('debug')
    if debug_flag is None:
        _debug_local.enabled = False
        _debug_local.filters = {}
        return

    filters = {}
    if request.GET.get('debug_book'):
        filters['book'] = request.GET.get('debug_book')
    if request.GET.get('debug_chapter'):
        filters['chapter'] = request.GET.get('debug_chapter')
    if request.GET.get('debug_verse'):
        filters['verse'] = request.GET.get('debug_verse')

    _debug_local.enabled = True
    _debug_local.filters = filters


def should_emit_debug(*, book: Optional[str] = None, chapter: Optional[int] = None, verse: Optional[int] = None) -> bool:
    if not settings or not getattr(settings, 'ENABLE_VERBOSE_DEBUG', False):
        return False
    if not getattr(_debug_local, 'enabled', False):
        return False

    filters = getattr(_debug_local, 'filters', {}) or {}
    if 'book' in filters:
        if _normalize_book(filters['book']) != _normalize_book(book):
            return False
    if 'chapter' in filters:
        try:
            if chapter is None or int(filters['chapter']) != int(chapter):
                return False
        except (TypeError, ValueError):
            return False
    if 'verse' in filters:
        try:
            if verse is None or int(filters['verse']) != int(verse):
                return False
        except (TypeError, ValueError):
            return False

    return True
