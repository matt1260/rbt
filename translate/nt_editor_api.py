"""
JSON endpoints for the NT verse editor (/edit/?book=…&chapter=…&verse=…).

Saving the verse and its footnotes goes through chapter_editor_api (save_verse, footnote),
which check for edits made elsewhere and store footnotes in the clean form. This module
adds what the verse editor needs on top:

- state: the verse HTML and every footnote it links to, read from the database (the
  page itself may come from the reader cache);
- create_footnote: a new footnote with the next free number for its place in the book,
  plus the marker to put in the verse;
- normalize_footnote: a footnote's HTML in the clean form, without saving it.
"""
import html as html_lib
import json
import logging
import re
from datetime import datetime

from django.http import JsonResponse
from django.views.decorators.http import require_GET, require_POST

from search.models import TranslationUpdates
from search.views.translation_views import _nt_footnote_table
from translate.chapter_editor_api import (
    MAX_VERSE_HTML_LENGTH, _nt_book_abbrev, _parse_int, _strip_editor_artifacts, _verse_hash, staff_json,
)
from translate.db_utils import execute_query
from translate.footnote_cleanup import normalize as normalize_footnote
from translate.views import _invalidate_reader_cache, _safe_save_update

logger = logging.getLogger(__name__)

# A footnote marker in verse HTML: ?footnote=<chapter>-<verse>-<ref>&book=<abbrev>.
ANCHOR_RE = re.compile(r'\?footnote=(\d+)-(\d+)-([0-9A-Za-z]+)(?:&amp;|&)book=([0-9A-Za-z]+)')
REF_RE = re.compile(r'^(\d+)([a-z]*)$')


def _json_body(request):
    try:
        return json.loads(request.body or b'{}')
    except (ValueError, UnicodeDecodeError):
        return None


def _footnote_rows(table, footnote_id):
    """Stored copies of a footnote (John's table has no unique index, so there can be several)."""
    return [r[0] or '' for r in execute_query(
        f'SELECT footnote_html FROM new_testament.{table} WHERE footnote_id = %s', (footnote_id,), fetch='all',
    ) or []]


def _footnote_entry(abbrev, ref):
    table = _nt_footnote_table(abbrev)
    footnote_id = f'{abbrev}-{ref}'
    copies = _footnote_rows(table, footnote_id)
    html = next((c for c in copies if c.strip()), copies[0] if copies else '')
    result = normalize_footnote(html) if copies else None
    return {
        'ref': ref,
        'footnote_id': footnote_id,
        'exists': bool(copies),
        'copies': len(copies),
        'html': html,
        'hash': _verse_hash(html),
        'needs_cleanup': bool(result and result.changed),
        'cleanup': result.changes if result else [],
    }


@require_GET
@staff_json
def state(request):
    """GET ?book=&chapter=&verse= → {html, hash, footnotes: [...]} for the verse, from the DB."""
    book = request.GET.get('book', '')
    chapter = _parse_int(request.GET.get('chapter'))
    verse = _parse_int(request.GET.get('verse'))
    abbrev = _nt_book_abbrev(book)
    if not abbrev or chapter is None or verse is None:
        return JsonResponse({'error': 'Unknown NT book, chapter or verse.'}, status=400)
    row = execute_query(
        'SELECT rbt FROM new_testament.nt WHERE book = %s AND chapter = %s AND startVerse = %s',
        (abbrev, chapter, verse), fetch='one',
    )
    if not row:
        return JsonResponse({'error': 'Verse not found.'}, status=404)
    html = row[0] or ''
    refs = []
    for m in ANCHOR_RE.finditer(html):
        if m.group(3) not in refs:
            refs.append(m.group(3))
    return JsonResponse({
        'book': book, 'abbrev': abbrev, 'chapter': chapter, 'verse': verse,
        'html': html, 'hash': _verse_hash(html),
        'footnotes': [_footnote_entry(abbrev, ref) for ref in refs],
    })


def _ref_key(ref):
    m = REF_RE.match(ref or '')
    return (int(m.group(1)), m.group(2)) if m else None


def _next_suffix(suffix):
    """'' → 'a', 'a' → 'b', 'z' → 'za'."""
    if not suffix:
        return 'a'
    if suffix[-1] == 'z':
        return suffix + 'a'
    return suffix[:-1] + chr(ord(suffix[-1]) + 1)


def choose_ref(abbrev, chapter, verse, index, existing):
    """
    The number for a footnote added at `index` (markers before the caret) in this verse, so
    numbers keep reading order: the next whole number at the end of the book; between two
    notes, the next whole number if it is free and still before the following note,
    otherwise a letter after the previous one (70 → 70a, 70a → 70b).
    """
    rows = execute_query(
        'SELECT chapter, startVerse, rbt FROM new_testament.nt WHERE book = %s ORDER BY chapter, startVerse',
        (abbrev,), fetch='all',
    ) or []
    before, after = [], []
    for ch, vs, html in rows:
        refs = [m.group(3) for m in ANCHOR_RE.finditer(html or '')]
        place = (int(ch), int(vs))
        if place < (chapter, verse):
            before += refs
        elif place == (chapter, verse):
            before += refs[:index]
            after += refs[index:]
        else:
            after += refs
    prev = next((k for k in (_ref_key(r) for r in reversed(before)) if k), None)
    nxt = next((k for k in (_ref_key(r) for r in after) if k), None)
    taken = {r for r in existing}
    numbers = [k[0] for k in (_ref_key(r) for r in taken) if k]

    if nxt is None:
        return str(max(numbers + [prev[0] if prev else 0]) + 1)
    prev = prev or (0, '')
    whole = str(prev[0] + 1)
    if (prev[0] + 1, '') < nxt and whole not in taken:
        return whole
    suffix = _next_suffix(prev[1])
    while f'{prev[0]}{suffix}' in taken:
        suffix = _next_suffix(suffix)
    return f'{prev[0]}{suffix}'


def marker_html(abbrev, chapter, verse, ref):
    """The marker as stored in verse HTML (same form as the existing ones)."""
    return (f'<a class="sdfootnoteanc" href="?footnote={chapter}-{verse}-{ref}&amp;book={abbrev}" '
            f'target="_blank"><sup>{ref}</sup></a>')


@require_POST
@staff_json
def create_footnote(request):
    """
    POST {book, chapter, verse, index, heading?, html} → {ref, footnote_id, html, hash, marker}.

    Stores the new footnote (clean form) under the next free number for its place; the
    editor then puts the marker in the verse at the caret and saves the verse.
    """
    payload = _json_body(request)
    if payload is None:
        return JsonResponse({'error': 'Invalid JSON.'}, status=400)
    book = payload.get('book', '')
    chapter = _parse_int(payload.get('chapter'))
    verse = _parse_int(payload.get('verse'))
    index = _parse_int(payload.get('index'))
    abbrev = _nt_book_abbrev(book)
    body = payload.get('html')
    heading = (payload.get('heading') or '').strip()
    if not abbrev or chapter is None or verse is None or index is None or index < 0:
        return JsonResponse({'error': 'book, chapter, verse and index are required.'}, status=400)
    if not isinstance(body, str) or len(body) > MAX_VERSE_HTML_LENGTH or len(heading) > 300:
        return JsonResponse({'error': 'The footnote text is missing or too long.'}, status=400)

    content = ''
    if heading:
        content = f'<p><span class="footnote_header">{html_lib.escape(heading)}</span></p>\n'
    content += _strip_editor_artifacts(body)
    clean = normalize_footnote(content).html
    if not clean.strip():
        return JsonResponse({'error': 'Write the footnote first.'}, status=400)

    # (execute_query commits each statement, so no atomic block; one editor at a time.)
    table = _nt_footnote_table(abbrev)
    existing = [r[0].split('-', 1)[1] for r in execute_query(
        f'SELECT footnote_id FROM new_testament.{table} WHERE footnote_id LIKE %s', (f'{abbrev}-%',), fetch='all',
    ) or [] if '-' in r[0]]
    ref = choose_ref(abbrev, chapter, verse, index, existing)
    footnote_id = f'{abbrev}-{ref}'
    execute_query(f'INSERT INTO new_testament.{table} (footnote_id, footnote_html) VALUES (%s, %s)', (footnote_id, clean))

    _safe_save_update(TranslationUpdates(
        date=datetime.now(), version='New Testament Footnote',
        reference=f'{book} {chapter}:{verse} - {footnote_id}',
        update_text=f'Added footnote <b>{footnote_id}</b>:<br> {clean}',
    ))
    _invalidate_reader_cache(book, chapter, verse)
    logger.info('[NT EDITOR] %s added footnote %s (%s %s:%s)', request.user.username, footnote_id, book, chapter, verse)
    return JsonResponse({
        'ref': ref, 'footnote_id': footnote_id, 'html': clean, 'hash': _verse_hash(clean),
        'marker': marker_html(abbrev, chapter, verse, ref),
    })


@require_POST
@staff_json
def normalize_footnote_preview(request):
    """POST {html} → {html, changes, text_changed, review}: the clean form, not saved."""
    payload = _json_body(request)
    if payload is None or not isinstance(payload.get('html'), str):
        return JsonResponse({'error': 'html is required.'}, status=400)
    if len(payload['html']) > MAX_VERSE_HTML_LENGTH:
        return JsonResponse({'error': 'Footnote is too long.'}, status=400)
    result = normalize_footnote(_strip_editor_artifacts(payload['html']))
    return JsonResponse({'html': result.html, 'changes': result.changes,
                         'text_changed': result.text_changed, 'review': result.review})
