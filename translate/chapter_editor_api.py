"""
JSON endpoints for the inline NT chapter editor (chapter-editor/ React app).

Staff only. The editor loads a chapter's verse HTML straight from the DB (bypassing
the reader cache), saves one verse at a time with optimistic concurrency, edits the
footnotes shown in the chapter's footnote pop-up the same way, and fetches the Greek
interlinear for the verse-ref hover popup.
"""
import hashlib
import json
import logging
import re
from datetime import datetime
from functools import wraps

from bs4 import BeautifulSoup
from django.http import JsonResponse
from django.views.decorators.http import require_GET, require_POST

from search.views.chapter_views_part1 import fetch_greek_interlinear_rows
from translate.db_utils import execute_query
from translate.translator import book_abbreviations, new_testament_books
from search.views.translation_views import _nt_footnote_table
from search.models import TranslationUpdates
from translate.views import _invalidate_reader_cache, _safe_save_update, save_nt_verse_html

logger = logging.getLogger(__name__)

MAX_VERSE_HTML_LENGTH = 100_000
# Autosaves of the same verse within this window update one TranslationUpdates row.
LOG_COALESCE_SECONDS = 10 * 60

# Attributes/elements the browser or ProseMirror can leave behind; never part of stored verse HTML.
_EDITOR_ATTR_RE = re.compile(r'\s(?:contenteditable|draggable|spellcheck)="[^"]*"')
_EDITOR_ELEMENT_RE = re.compile(
    r'<(?:img|br)\s+class="ProseMirror-(?:separator|trailingBreak)"[^>]*>'
)


def _verse_hash(html):
    return hashlib.sha1((html or '').encode('utf-8')).hexdigest()


def _strip_editor_artifacts(html):
    html = _EDITOR_ELEMENT_RE.sub('', html)
    return _EDITOR_ATTR_RE.sub('', html)


def staff_json(view):
    """Like user_passes_test(is_staff) but answers with JSON 403 instead of a login redirect."""
    @wraps(view)
    def wrapper(request, *args, **kwargs):
        user = request.user
        if not (user.is_authenticated and user.is_staff):
            return JsonResponse({'error': 'Staff login required.'}, status=403)
        return view(request, *args, **kwargs)
    return wrapper


def _nt_book_abbrev(book):
    if book not in new_testament_books:
        return None
    return book_abbreviations.get(book, book)


def _parse_int(value):
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


@require_GET
@staff_json
def chapter(request):
    """GET ?book=&chapter= → {verses: [{verse, html, hash}]} in reading order."""
    book = request.GET.get('book', '')
    chapter_num = _parse_int(request.GET.get('chapter'))
    book_abbrev = _nt_book_abbrev(book)
    if not book_abbrev or chapter_num is None:
        return JsonResponse({'error': 'Unknown NT book or chapter.'}, status=400)

    rows = execute_query(
        """
        SELECT startVerse, rbt
        FROM new_testament.nt
        WHERE book = %s AND chapter = %s
        ORDER BY startVerse
        """,
        (book_abbrev, chapter_num),
        fetch='all',
    ) or []

    verses = [
        {'verse': str(verse), 'html': html or '', 'hash': _verse_hash(html)}
        for verse, html in rows
    ]
    return JsonResponse({'book': book, 'chapter': chapter_num, 'verses': verses})


@require_POST
@staff_json
def save_verse(request):
    """
    POST JSON {book, chapter, verse, html, base_hash} → {hash}.

    base_hash is the hash of the HTML the editor started from. If the stored verse has
    changed since (e.g. edited on the verse edit page), nothing is written and a 409
    returns the current HTML so the editor can reload it.
    """
    try:
        payload = json.loads(request.body)
    except (ValueError, UnicodeDecodeError):
        return JsonResponse({'error': 'Invalid JSON.'}, status=400)

    book = payload.get('book', '')
    chapter_num = _parse_int(payload.get('chapter'))
    verse_num = _parse_int(payload.get('verse'))
    html = payload.get('html')
    base_hash = payload.get('base_hash')
    book_abbrev = _nt_book_abbrev(book)

    if not book_abbrev or chapter_num is None or verse_num is None:
        return JsonResponse({'error': 'Unknown NT book, chapter or verse.'}, status=400)
    if not isinstance(html, str) or not isinstance(base_hash, str):
        return JsonResponse({'error': 'html and base_hash are required.'}, status=400)
    if len(html) > MAX_VERSE_HTML_LENGTH:
        return JsonResponse({'error': 'Verse HTML is too long.'}, status=400)

    row = execute_query(
        """
        SELECT verseID, rbt
        FROM new_testament.nt
        WHERE book = %s AND chapter = %s AND startVerse = %s
        """,
        (book_abbrev, chapter_num, verse_num),
        fetch='one',
    )
    if not row:
        return JsonResponse({'error': 'Verse not found.'}, status=404)

    verse_id, current_html = row
    if _verse_hash(current_html) != base_hash:
        return JsonResponse(
            {'error': 'This verse was changed elsewhere.', 'html': current_html or '', 'hash': _verse_hash(current_html)},
            status=409,
        )

    html = _strip_editor_artifacts(html)
    if html == (current_html or ''):
        return JsonResponse({'hash': base_hash, 'saved': False})

    save_nt_verse_html(verse_id, html, book, chapter_num, verse_num, coalesce_seconds=LOG_COALESCE_SECONDS)
    logger.info('[CHAPTER EDITOR] %s saved %s %s:%s', request.user.username, book, chapter_num, verse_num)
    return JsonResponse({'hash': _verse_hash(html), 'saved': True})


@require_GET
@staff_json
def interlinear(request):
    """GET ?book=&chapter=&verse= → {words: [...]} for the verse-ref hover popup."""
    book = request.GET.get('book', '')
    chapter_num = _parse_int(request.GET.get('chapter'))
    verse_num = _parse_int(request.GET.get('verse'))
    if not _nt_book_abbrev(book) or chapter_num is None or verse_num is None:
        return JsonResponse({'error': 'Unknown NT book, chapter or verse.'}, status=400)

    words = [
        {key: word[key] for key in ('strongs', 'translit', 'lemma', 'english', 'morph', 'morph_desc')}
        for word in fetch_greek_interlinear_rows(book, chapter_num, verse_num)
    ]
    return JsonResponse({'words': words})


# A footnote's own reference within its book: "70a" in ?footnote=2-5-70a&book=Joh.
_FOOTNOTE_REF_RE = re.compile(r'^[0-9]+[a-z]{0,3}$', re.I)


def _footnote_location(book_abbrev, ref):
    """(table, footnote_id) of an NT footnote, e.g. ('joh_footnotes', 'Joh-70a')."""
    return _nt_footnote_table(book_abbrev), f'{book_abbrev}-{ref}'


def _normalize_footnote_html(html):
    """As the footnote edit page saves it (translate/views.py edit_footnote): no editor
    attributes, and paragraphs and lists carry the rbt_footnote class."""
    soup = BeautifulSoup(_strip_editor_artifacts(html), 'html.parser')
    for tag in soup.find_all(True):
        for attr in ('data-start', 'data-end'):
            tag.attrs.pop(attr, None)
    for tag in soup.find_all(['p', 'ul']):
        classes = tag.get('class', [])
        if 'rbt_footnote' not in classes:
            tag['class'] = classes + ['rbt_footnote']
    return str(soup)


@staff_json
def footnote(request):
    """
    GET ?book=&ref= → {html, hash}: one NT footnote's stored HTML.
    POST JSON {book, chapter, verse, ref, html, base_hash} → {hash, html}: save it. As with
    verses, a footnote changed elsewhere since base_hash is not overwritten (409).
    """
    if request.method == 'GET':
        book, ref = request.GET.get('book', ''), request.GET.get('ref', '')
    elif request.method == 'POST':
        try:
            payload = json.loads(request.body)
        except (ValueError, UnicodeDecodeError):
            return JsonResponse({'error': 'Invalid JSON.'}, status=400)
        book, ref = payload.get('book', ''), str(payload.get('ref', ''))
    else:
        return JsonResponse({'error': 'GET or POST only.'}, status=405)

    book_abbrev = _nt_book_abbrev(book)
    if not book_abbrev or not _FOOTNOTE_REF_RE.match(ref):
        return JsonResponse({'error': 'Unknown NT book or footnote.'}, status=400)
    table, footnote_id = _footnote_location(book_abbrev, ref)
    row = execute_query(
        f'SELECT footnote_html FROM new_testament.{table} WHERE footnote_id = %s',
        (footnote_id,),
        fetch='one',
    )
    if not row:
        return JsonResponse({'error': 'Footnote not found.'}, status=404)
    current_html = row[0] or ''

    if request.method == 'GET':
        return JsonResponse({'html': current_html, 'hash': _verse_hash(current_html)})

    chapter_num = _parse_int(payload.get('chapter'))
    verse_num = _parse_int(payload.get('verse'))
    html = payload.get('html')
    base_hash = payload.get('base_hash')
    if chapter_num is None or verse_num is None or not isinstance(html, str) or not isinstance(base_hash, str):
        return JsonResponse({'error': 'chapter, verse, html and base_hash are required.'}, status=400)
    if len(html) > MAX_VERSE_HTML_LENGTH:
        return JsonResponse({'error': 'Footnote HTML is too long.'}, status=400)
    if _verse_hash(current_html) != base_hash:
        return JsonResponse(
            {'error': 'This footnote was changed elsewhere.', 'html': current_html, 'hash': _verse_hash(current_html)},
            status=409,
        )

    html = _normalize_footnote_html(html)
    if html != current_html:
        execute_query(
            f'UPDATE new_testament.{table} SET footnote_html = %s WHERE footnote_id = %s',
            (html, footnote_id),
        )
        _safe_save_update(TranslationUpdates(
            date=datetime.now(),
            version='New Testament Footnote',
            reference=f'{book} {chapter_num}:{verse_num} - {footnote_id}',
            update_text=f'Updated footnote for Footnote <b>{footnote_id}</b>:<br> {html}.',
        ))
        _invalidate_reader_cache(book, chapter_num, verse_num)
        logger.info('[CHAPTER EDITOR] %s saved footnote %s (%s %s:%s)', request.user.username, footnote_id, book, chapter_num, verse_num)
    return JsonResponse({'hash': _verse_hash(html), 'html': html})
