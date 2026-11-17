"""
Which Brenton Septuagint verse (table englxxup) belongs beside an Old Testament verse of the reader.

The reader, the Hebrew and the Septuagint number many verses differently (Psalm 82 is the
Septuagint's Psalm 81; Jeremiah 25-51 are rearranged; Nehemiah is 2 Esdras 11-23). The table in
search/data/brenton_versification.json lists the reader verses whose Brenton verse has another
reference, or none at all; it is made by `manage.py build_brenton_versification`.
"""
import json
import os
from functools import lru_cache

from django.conf import settings

TABLE_PATH = os.path.join(settings.BASE_DIR, 'search', 'data', 'brenton_versification.json')
SEPTUAGINT_BOOK_NAMES = {('Nehemiah', 'EZR'): '2 Esdras'}
_UNLISTED = object()


@lru_cache(maxsize=1)
def _table():
    try:
        with open(TABLE_PATH, encoding='utf-8') as fh:
            return json.load(fh)
    except (OSError, ValueError):
        return {}


def brenton_reference(book, chapter, verse, default_code):
    """(englxxup book code, chapter, verse) as strings for a reader verse, or None when the
    Septuagint has no such verse. Unlisted verses keep the reader's numbers under default_code."""
    try:
        key = f'{int(chapter)}:{int(verse)}'
    except (TypeError, ValueError):
        return (default_code, str(chapter), str(verse)) if default_code else None
    entry = _table().get(book, {}).get(key, _UNLISTED)
    if entry is _UNLISTED:
        return (default_code, str(int(chapter)), str(int(verse))) if default_code else None
    if not entry:
        return None
    code, chapter_verse = entry.split(' ', 1)
    lxx_chapter, lxx_verse = chapter_verse.split(':', 1)
    return code, lxx_chapter, lxx_verse


def brenton_label(book, reference, default_code, chapter, verse):
    """'2 Esdras 11:1' / '81:6' when Brenton numbers the verse differently, else ''."""
    code, lxx_chapter, lxx_verse = reference
    try:
        own = (default_code, str(int(chapter)), str(int(verse)))
    except (TypeError, ValueError):
        own = (default_code, str(chapter), str(verse))
    if (code, lxx_chapter, lxx_verse) == own:
        return ''
    name = SEPTUAGINT_BOOK_NAMES.get((book, code), '')
    return f'{name} {lxx_chapter}:{lxx_verse}'.strip()
