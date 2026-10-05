"""
Translated book titles and the Gospel of Judas heading (VerseTranslation rows with
chapter=0: verse 0 is a book's RBT title, verse 3 the Judas heading phrase).

Each row records a fingerprint of the English it was translated from (source_hash), so a
title changed in search/rbt_titles.py shows up as stale: pages then fall back to the
English title, and refresh_stale_titles() (the translation dashboard's "Refresh titles")
re-translates every stale one. Rows saved before titles had a fingerprint (NULL) are
trusted, as for verses, except for the titles renamed since (RENAMED_BEFORE_FINGERPRINTS).
"""
import logging
import re

from search.models import VerseTranslation
from search.rbt_titles import rbt_books
from search.translation_utils import is_translation_current, source_fingerprint

logger = logging.getLogger(__name__)

JUDAS_BOOK = 'Gospel of Judas'
JUDAS_HEADING = 'Gospel of Praised One'
TITLE_VERSE = 0
JUDAS_HEADING_VERSE = 3
# Display titles for books rbt_books doesn't cover.
TITLE_OVERRIDES = {JUDAS_BOOK: 'Gospel of Praised One (Judas)'}
# source_hash of a translation known to be out of date (set by migration 0017).
STALE = 'stale'
# Titles renamed before their translations carried a fingerprint: an unfingerprinted
# (NULL) translation of one of these is of the old title. (Covered here rather than only
# by migration 0017, which production may not have run.)
RENAMED_BEFORE_FINGERPRINTS = {
    ('Isaiah', TITLE_VERSE), ('Jeremiah', TITLE_VERSE), ('Jude', TITLE_VERSE),
    (JUDAS_BOOK, TITLE_VERSE), (JUDAS_BOOK, JUDAS_HEADING_VERSE),
}


def english_title(book):
    """The English RBT title of a book, as it is translated (stored names may lack the space in '1John')."""
    display = re.sub(r'(\d+)([a-zA-Z]+)', r'\1 \2', book)
    return TITLE_OVERRIDES.get(display) or rbt_books.get(display, display)


def title_source(book, verse):
    """The English a chapter-0 title row translates."""
    return JUDAS_HEADING if (book == JUDAS_BOOK and verse == JUDAS_HEADING_VERSE) else english_title(book)


def is_current(row):
    """True unless the row was translated from different English than the title has now."""
    if row.source_hash is None and (row.book, row.verse) in RENAMED_BEFORE_FINGERPRINTS:
        return False
    return is_translation_current(row.source_hash, source_fingerprint(title_source(row.book, row.verse)))


def current_text(row):
    """The row's translated text if it's still current, else None (callers show the English)."""
    return row.verse_text if row is not None and row.verse_text and is_current(row) else None


def _title_rows():
    """Title rows that can be stale: fingerprinted ones, and unfingerprinted ones of renamed titles."""
    from django.db.models import Q

    rows = VerseTranslation.objects.filter(chapter=0, footnote_id__isnull=True)
    titles = Q(verse=TITLE_VERSE) | Q(book=JUDAS_BOOK, verse=JUDAS_HEADING_VERSE)
    renamed = Q()
    for book, verse in RENAMED_BEFORE_FINGERPRINTS:
        renamed |= Q(book=book, verse=verse)
    return rows.filter(titles).filter(Q(source_hash__isnull=False) | (Q(source_hash__isnull=True) & renamed))


def stale_titles():
    """Title rows whose English has changed since they were translated."""
    return [row for row in _title_rows().order_by('language_code', 'book', 'verse') if not is_current(row)]


def stale_summary():
    """{'total': n, 'titles': [{'english', 'languages'}]} for the dashboard."""
    by_title = {}
    for row in stale_titles():
        by_title.setdefault(title_source(row.book, row.verse), set()).add(row.language_code)
    titles = [{'english': english, 'languages': len(languages)} for english, languages in sorted(by_title.items())]
    return {'total': sum(t['languages'] for t in titles), 'titles': titles}


def translate_title(book, verse, language):
    """Translate one title into `language`; None if the model call failed."""
    from search.translation_utils import translate_chapter_batch

    english = title_source(book, verse)
    # Key 0 gets translate_chapter_batch's title prompt (the meaning of the words, not the
    # traditional book name); the Judas heading has always been translated as text.
    key = TITLE_VERSE if verse == TITLE_VERSE else JUDAS_HEADING_VERSE
    translated = (translate_chapter_batch({key: english}, language).get(key) or '').strip()
    if not translated or translated.startswith('[Translation'):
        return None
    return translated


def save_title(book, verse, language, text):
    """Store a translated title, replacing any earlier rows for it (older code could leave duplicates)."""
    english = title_source(book, verse)
    rows = VerseTranslation.objects.filter(book=book, chapter=0, verse=verse, language_code=language, footnote_id__isnull=True)
    rows.delete()
    VerseTranslation.objects.create(
        book=book, chapter=0, verse=verse, language_code=language, verse_text=text,
        status='completed', source_hash=source_fingerprint(english),
    )


def refresh_stale_titles(log=logger.info):
    """Re-translate every stale title row. Returns (refreshed, failed) counts."""
    refreshed = failed = 0
    for row in stale_titles():
        text = translate_title(row.book, row.verse, row.language_code)
        if text is None:
            failed += 1
            log(f'[TITLES] {row.book} ({row.verse}) -> {row.language_code}: translation failed')
            continue
        save_title(row.book, row.verse, row.language_code, text)
        refreshed += 1
        log(f'[TITLES] {row.book} ({row.verse}) -> {row.language_code}: {text}')
    return refreshed, failed
