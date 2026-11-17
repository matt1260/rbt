"""
Which English-numbered verse (LITV, Julia Smith) belongs beside an Old Testament verse of the reader.

The reader numbers verses as the Hebrew text does (Psalm titles are verses; Hosea 12:1 is English
11:12); LITV and Smith use the English numbers. search/data/english_versification.json lists the
reader verses whose English number differs; it is made by `manage.py build_english_versification`.
"""
import json
import os
from functools import lru_cache

from django.conf import settings

TABLE_PATH = os.path.join(settings.BASE_DIR, 'search', 'data', 'english_versification.json')


@lru_cache(maxsize=1)
def _table():
    try:
        with open(TABLE_PATH, encoding='utf-8') as fh:
            return json.load(fh)
    except (OSError, ValueError):
        return {}


def english_reference(book, chapter, verse):
    """(chapter, verse) as strings in the English numbering, for a reader verse."""
    try:
        key = f'{int(chapter)}:{int(verse)}'
    except (TypeError, ValueError):
        return str(chapter), str(verse)
    entry = _table().get(book, {}).get(key)
    if not entry:
        return str(int(chapter)), str(int(verse))
    eng_chapter, eng_verse = entry.split(':', 1)
    return eng_chapter, eng_verse


def english_note(book, chapter, verse):
    """' <span class="lxx-ref">(Eng. 8:4)</span>' when the English number differs, else ''."""
    eng_chapter, eng_verse = english_reference(book, chapter, verse)
    try:
        same = (int(eng_chapter), int(eng_verse)) == (int(chapter), int(verse))
    except (TypeError, ValueError):
        same = True
    return '' if same else f' <span class="lxx-ref">(Eng. {eng_chapter}:{eng_verse})</span>'
