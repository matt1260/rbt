"""
Translated paraphrases: a chapter's published English paraphrase, translated for readers of
the other site languages by the page translator (search/translation_utils.py, the
GEMINI_API_KEYS pool), the way the word-for-word text is.

A translation is a published ChapterParaphrase row in that language. Its source_hash is the
hash of the English HTML it was made from, so an edit to the English makes it stale; a stale
translation is still shown while a new one is made. A translation is started the first time
a reader opens the paraphrase in that language (static/reader-paraphrase.js), in a
background thread.

Each paragraph and each image's notes are translated separately and put back with the
inline editor's sanitising (paraphrase._clean_edit), so the model never handles image cues,
verse anchors or the media store: cues go out as <rbt-media n="N"> markers and are rebuilt
from the stored media.
"""

import logging
import threading
import time
import uuid

import nh3
from bs4 import BeautifulSoup
from django.db import close_old_connections, transaction
from django.utils import timezone

from search import paraphrase
from search.models import ChapterParaphrase
from search.translation_utils import SUPPORTED_LANGUAGES, translate_chapter_batch, translate_footnotes_batch

logger = logging.getLogger(__name__)

PROVIDER = 'gemini'
MODEL = 'gemini-3.8-flash'  # what translate_chapter_batch uses
PROMPT_NAME = 'Translation'
CREATED_BY = 'translator'
# Top-level elements whose text is translated; anything else (the media store, a stray cue)
# is kept as it is.
TRANSLATABLE = ('p', 'blockquote', 'h5', 'ul', 'ol')
BLOCKS_PER_CALL = 12
NOTES_PER_CALL = 12
# Pause before retrying paragraphs the translator missed (usually an overloaded model).
RETRY_AFTER_SECONDS = 30


def translatable(language):
    return language != 'en' and language in SUPPORTED_LANGUAGES


def is_current(row, english):
    return bool(row and english) and row.source_hash == paraphrase.html_hash(english.html)


def state(book, chapter, language, english=None):
    """
    How the paraphrase stands in `language`: (row to show or None, status), status being
    'current', 'stale' (shown, but made from an older English text), 'missing',
    or '' (no English paraphrase, or not a translatable language).
    """
    english = english or paraphrase.published_for(book, chapter)
    if not english or not translatable(language):
        return None, ''
    row = paraphrase.published_for(book, chapter, language)
    if not row:
        return None, 'missing'
    return row, 'current' if is_current(row, english) else 'stale'


def status(book, chapter, language):
    """What the reader page polls for: {'status': 'done'|'running'|'failed'|'missing'|'unavailable', ...}."""
    english = paraphrase.published_for(book, chapter)
    if not english or not translatable(language):
        return {'status': 'unavailable'}
    paraphrase.expire_stale(book, chapter)
    row, how = state(book, chapter, language, english)
    if row:
        return {'status': 'done', 'html': row.html, 'current': how == 'current'}
    latest = ChapterParaphrase.objects.filter(
        book=book, chapter=chapter, language_code=language,
    ).only('status', 'error').first()
    if latest and latest.status in ('pending', 'running'):
        return {'status': 'running'}
    if latest and latest.status == 'failed':
        return {'status': 'failed'}
    return {'status': 'missing'}


def start(book, chapter, language):
    """Start translating the English paraphrase unless a current translation exists or one is
    already being made. Returns status() as it now stands."""
    english = paraphrase.published_for(book, chapter)
    if not english or not translatable(language):
        return {'status': 'unavailable'}
    paraphrase.expire_stale(book, chapter)
    with transaction.atomic():
        # Locking the English row makes simultaneous starts for a chapter take turns, so
        # only the first creates a translation.
        english = ChapterParaphrase.objects.select_for_update().get(pk=english.pk)
        row, how = state(book, chapter, language, english)
        busy = ChapterParaphrase.objects.filter(
            book=book, chapter=chapter, language_code=language, status__in=['pending', 'running'],
        ).exists()
        if how == 'current' or busy:
            return status(book, chapter, language)
        job = ChapterParaphrase.objects.create(
            batch_id=uuid.uuid4(), book=book, chapter=chapter, language_code=language,
            provider=PROVIDER, model_name=MODEL, prompt_name=PROMPT_NAME, created_by=CREATED_BY,
            source_hash=paraphrase.html_hash(english.html),
        )
        # The thread uses its own DB connection, so the row must be committed first.
        transaction.on_commit(lambda: threading.Thread(
            target=run, args=(job.pk, english.html), name=f'paraphrase-{language}-{job.uid}', daemon=True,
        ).start())
    logger.info('[PARAPHRASE] translating %s %s into %s', book, chapter, language)
    return {'status': 'running'}


def run(pk, english_html):
    close_old_connections()
    started = time.monotonic()
    try:
        row = ChapterParaphrase.objects.get(pk=pk)
        ChapterParaphrase.objects.filter(pk=pk).update(status='running', started_at=timezone.now())
        html = translate_html(english_html, row.language_code, chapter=row.chapter)
        with transaction.atomic():
            ChapterParaphrase.objects.filter(
                book=row.book, chapter=row.chapter, language_code=row.language_code, is_published=True,
            ).update(is_published=False)
            ChapterParaphrase.objects.filter(pk=pk).update(
                status='done', html=html, is_published=True, published_at=timezone.now(),
                duration_ms=int((time.monotonic() - started) * 1000), finished_at=timezone.now(),
            )
        # Earlier translations of this chapter are never shown again.
        ChapterParaphrase.objects.filter(
            book=row.book, chapter=row.chapter, language_code=row.language_code, is_published=False,
        ).exclude(pk=pk).delete()
    except Exception as exc:
        logger.exception('Paraphrase translation %s failed', pk)
        ChapterParaphrase.objects.filter(pk=pk).update(
            status='failed', error=f'{type(exc).__name__}: {exc}'[:2000],
            duration_ms=int((time.monotonic() - started) * 1000), finished_at=timezone.now(),
        )
    finally:
        close_old_connections()


# ---------------------------------------------------------------------------
# Translating the HTML

def _chunks(items, size):
    for i in range(0, len(items), size):
        yield items[i:i + size]


def _check(translated, wanted):
    """The batch result, with the keys the translator failed on left out."""
    if translated.get('__quota_exceeded__'):
        raise RuntimeError('Translation quota exhausted.')
    failed = [text for key, text in translated.items() if key in wanted and (text or '').startswith('[Translation')]
    if failed:
        logger.warning('Paraphrase translation: %d parts failed, e.g. %s', len(failed), failed[0][:300])
    return {
        key: text for key, text in translated.items()
        if key in wanted and text and not text.startswith('[Translation')
    }


def _block_source(block):
    """A block's contents as sent to the translator: cues as <rbt-media> markers, no anchors."""
    copy = BeautifulSoup(block.decode_contents(), 'html.parser')
    for cue in copy.select('button.pp-cue'):
        n = cue.get('data-media', '')
        cue.replace_with(copy.new_tag('rbt-media', attrs={'n': n}) if n.isdigit() else '')
    for anchor in copy.select('span.pp-anchor'):
        anchor.decompose()
    return str(copy).strip()


def _cue_numbers(node):
    return [cue.get('data-media') for cue in node.select('button.pp-cue')]


def _translate_blocks(sources, language, chapter):
    """{i: translated} for {i: source}; a block the translator misses is retried once."""
    done = {}
    for attempt in range(2):
        todo = [(i, text) for i, text in sources.items() if i not in done]
        if attempt and todo:
            time.sleep(RETRY_AFTER_SECONDS)
        for chunk in _chunks(todo, BLOCKS_PER_CALL):
            batch = dict(chunk)
            done.update(_check(translate_chapter_batch(batch, language, chapter=chapter), batch))
    missing = sorted(set(sources) - set(done))
    if missing:
        raise RuntimeError(f'The translator returned no text for paragraphs {missing}.')
    return done


def _translate_notes(sources, language):
    """{key: translated} for the notes the translator managed; the rest stay in English."""
    done = {}
    for chunk in _chunks(list(sources.items()), NOTES_PER_CALL):
        batch = dict(chunk)
        done.update(_check(translate_footnotes_batch(batch, language), batch))
    return done


def translate_html(html, language, chapter=None):
    """The paraphrase HTML with its paragraphs, headings and image notes translated."""
    soup = BeautifulSoup(html, 'html.parser')

    # Notes first: cues are rebuilt from the stored media, and take their titles from them.
    notes = {}
    for template in soup.select('.pp-media-store template[data-media]'):
        note = paraphrase._note_element(template)
        # get_text() skips text inside a <template>, so the note is read from a copy.
        if note is not None and BeautifulSoup(note.decode_contents(), 'html.parser').get_text(strip=True):
            notes[f'N{template["data-media"]}'] = note
    for key, text in _translate_notes({k: n.decode_contents() for k, n in notes.items()}, language).items():
        clean = nh3.clean(
            text, tags=paraphrase.NOTE_TAGS, attributes=paraphrase.NOTE_ATTRIBUTES,
            strip_comments=True, link_rel=None, clean_content_tags={'script', 'style'},
        )
        notes[key].clear()
        notes[key].append(BeautifulSoup(clean, 'html.parser'))

    # Keys from 1: translate_chapter_batch treats verse 0 as a book title.
    blocks = {
        i: block for i, block in enumerate(
            (node for node in soup.children if getattr(node, 'name', None) in TRANSLATABLE), start=1,
        ) if block.get_text(strip=True)
    }
    translated = _translate_blocks({i: _block_source(b) for i, b in blocks.items()}, language, chapter)
    media = paraphrase.stored_media(soup)
    for i, block in blocks.items():
        cues = _cue_numbers(block)
        block.clear()
        for node in paraphrase._clean_edit(soup, translated[i]):
            block.append(node)
        # An image the translator dropped goes back at the end of its paragraph.
        for n in cues:
            if n not in _cue_numbers(block) and n.isdigit() and int(n) in media:
                paraphrase._attach_cue(block, paraphrase._cue(soup, media[int(n)]))
        if block.get('data-v'):
            paraphrase._add_anchors(soup, block)
    return str(soup).strip()
