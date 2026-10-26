"""
Old Testament verse editor (/translate/ot/) and its JSON endpoints.

One set of word cards replaces the old interlinear cards + verse-edit cards: each card
shows the Hebrew, the gloss and morphology (edited in place and saved on the spot), the
lexicon chips (opened in the lexicon side panel) and the token's footnote. The paraphrase
is edited inline with a toolbar and autosaves, with the same optimistic-concurrency check
the NT chapter editor uses (a verse changed elsewhere is never overwritten).
"""
import hashlib
import json
import logging
import re
from datetime import datetime
from functools import wraps

import pythonbible as bible
from django.contrib.auth.decorators import login_required
from django.http import JsonResponse
from django.shortcuts import redirect, render
from django.urls import reverse
from django.views.decorators.http import require_GET, require_POST

from search.models import Genesis, GenesisFootnotes, TranslationUpdates
from search.seo_utils import book_to_slug
from translate.db_utils import execute_query, table_has_column
from translate.translator import (
    book_abbreviations,
    build_heb_interlinear,
    convert_book_name,
    new_testament_books,
    old_testament_books,
    ot_prev_next_references,
    split_strong_refs,
)
from translate.views import (
    _apply_gemini_preferences,
    _clear_reader_cache,
    _invalidate_reader_cache,
    _safe_save_update,
)

logger = logging.getLogger(__name__)

MAX_HTML_LENGTH = 100_000
NIQQUD_RE = re.compile('[֑-ֽֿׁ-ׇׅ]|־')
# Attributes the browser or other page scripts add to live content (base.html's tooltip
# set-up marks every .tooltip-container); never part of stored HTML.
_EDITOR_ATTR_RE = re.compile(r'\s(?:contenteditable|draggable|spellcheck|data-tooltip-init|data-ote-[a-z-]+)="[^"]*"')

GLOSS_SCOPES = ('word', 'consonantal', 'niqqud')

HEBREWDATA_COLUMNS = (
    "id, Ref, Eng, Heb1, Heb2, Heb3, Heb4, Heb5, Heb6, morph, uniq, Strongs, color, html, "
    "heb1_n, heb2_n, heb3_n, heb4_n, heb5_n, heb6_n, combined_heb, combined_heb_niqqud, footnote, morphology"
)


# --------------------------------------------------------------------------- helpers

def _hash(text):
    return hashlib.sha1((text or '').encode('utf-8')).hexdigest()


def _strip_niqqud(text):
    return NIQQUD_RE.sub('', text or '').strip()


def _strip_editor_artifacts(html):
    return _EDITOR_ATTR_RE.sub('', html or '')


def login_json(view):
    """login_required that answers JSON 401 instead of redirecting to the login page."""
    @wraps(view)
    def wrapper(request, *args, **kwargs):
        if not request.user.is_authenticated:
            return JsonResponse({'error': 'Login required.'}, status=401)
        return view(request, *args, **kwargs)
    return wrapper


def _json_body(request):
    try:
        return json.loads(request.body or b'{}')
    except (ValueError, UnicodeDecodeError):
        return None


def _verse_ref_parts(ref):
    """'Gen.1.1-03' or 'Gen.1.1' → ('Gen', '1', '1') or None."""
    if not ref:
        return None
    base = str(ref).split('-')[0]
    parts = base.split('.')
    if len(parts) < 3 or not all(parts[:3]):
        return None
    return parts[0], parts[1], parts[2]


def _book_name(code):
    return convert_book_name(code) or code


def _reference_label(verse_ref):
    parts = _verse_ref_parts(verse_ref)
    if not parts:
        return verse_ref or ''
    return f'{_book_name(parts[0])} {parts[1]}:{parts[2]}'


def _log(version, verse_ref, text):
    _safe_save_update(TranslationUpdates(
        date=datetime.now(), version=version, reference=_reference_label(verse_ref), update_text=text,
    ))


def _invalidate(verse_ref, field=None):
    """Clear the verse's reader cache. Translations are made from the paraphrase, so only a
    paraphrase edit (field='paraphrase') deletes them, to be made again; glosses, morphology,
    footnotes and the Genesis literal keep them."""
    parts = _verse_ref_parts(verse_ref)
    if not parts:
        return []
    clear = _invalidate_reader_cache if field == 'paraphrase' else _clear_reader_cache
    return clear(_book_name(parts[0]), parts[1], parts[2])


def _token_row(token_id):
    return execute_query(
        "SELECT id, Ref, Eng, combined_heb, combined_heb_niqqud, uniq, color, morphology "
        "FROM old_testament.hebrewdata WHERE id = %s;",
        (token_id,), fetch='one',
    )


def _verse_prefix(ref):
    """'Gen.1.1-03' → 'Gen.1.1-' (the LIKE prefix of every word in that verse)."""
    return ref.split('-')[0] + '-'


def _verse_token_ids(prefix, column, value):
    rows = execute_query(
        f"SELECT id FROM old_testament.hebrewdata WHERE Ref LIKE %s AND {column} = %s;",
        (f'{prefix}%', value), fetch='all',
    ) or []
    return [row[0] for row in rows]


def _rebuild_literal(verse_ref):
    """ot.literal is the verse's glosses in word order; keep it in step with gloss edits."""
    prefix = _verse_prefix(verse_ref)
    rows = execute_query(
        "SELECT Eng FROM old_testament.hebrewdata WHERE Ref LIKE %s ORDER BY Ref ASC;",
        (f'{prefix}%',), fetch='all',
    ) or []
    literal = ' '.join(filter(None, (row[0] for row in rows))).replace("אֵת- ", "אֵת-")
    execute_query("UPDATE old_testament.ot SET literal = %s WHERE Ref = %s;", (literal, prefix[:-1]))
    return literal


def _genesis_record(verse_ref):
    """The Genesis table row for a Gen.c.v ref (the reader renders Genesis from it), else None."""
    parts = _verse_ref_parts(verse_ref)
    if not parts or parts[0] != 'Gen':
        return None
    try:
        return Genesis.objects.filter(chapter=int(parts[1]), verse=int(parts[2])).first()
    except (TypeError, ValueError):
        return None


# The verse texts the editor can change. Every OT book has a paraphrase (on the verse's
# first hebrewdata row, mirrored to old_testament.ot). Genesis keeps both of its texts in
# the genesis table the reader renders from: html is the RBT Hebrew literal, rbt_reader the
# paraphrase. Other books build their literal from the word glosses, edited on the cards.
TEXT_FIELDS = ('literal', 'paraphrase')
GENESIS_COLUMNS = {'literal': 'html', 'paraphrase': 'rbt_reader'}
TEXT_LABELS = {'literal': 'RBT Hebrew literal', 'paraphrase': 'Paraphrase'}
# TranslationUpdates.version values, matching what the older editors logged.
TEXT_LOG_VERSIONS = {('Gen', 'literal'): 'Hebrew Literal', ('Gen', 'paraphrase'): 'Hebrew Translation'}


def _text_fields(verse_ref):
    """The editable verse texts for this verse, in display order."""
    return list(TEXT_FIELDS) if _genesis_record(verse_ref) is not None else ['paraphrase']


def _stored_text(verse_ref, field):
    """A verse text as the reader shows it, or None when this verse has no such text."""
    record = _genesis_record(verse_ref)
    if record is not None:
        return getattr(record, GENESIS_COLUMNS[field]) or ''
    if field != 'paraphrase':
        return None
    row = execute_query("SELECT html FROM old_testament.hebrewdata WHERE Ref = %s;", (f'{verse_ref}-01',), fetch='one')
    if not row:
        return None
    if row[0] is not None:
        return row[0]
    ot_row = execute_query("SELECT html FROM old_testament.ot WHERE Ref = %s;", (verse_ref,), fetch='one')
    return (ot_row[0] if ot_row else '') or ''


def _write_text(verse_ref, field, html):
    record = _genesis_record(verse_ref)
    if record is not None:
        column = GENESIS_COLUMNS[field]
        setattr(record, column, html)
        record.save(update_fields=[column])
        return
    execute_query("UPDATE old_testament.hebrewdata SET html = %s WHERE Ref = %s;", (html, f'{verse_ref}-01'))
    execute_query("UPDATE old_testament.ot SET html = %s WHERE Ref = %s;", (html, verse_ref))

# Footnotes are linked from verse text as ?footnote=<id>. Genesis keeps its own notes table
# (search GenesisFootnotes, ids like 1-4-15b: chapter-verse-number); other books note a word
# (hebrewdata.footnote, ids like Sng-6-5-08 for the row Sng.6.5-08).
NOTE_LINK_RE = re.compile(r'\?footnote=([0-9A-Za-z-]+)')
GENESIS_NOTE_RE = re.compile(r'^(\d+)-(\d+)-([0-9A-Za-z]+)$')
WORD_NOTE_RE = re.compile(r'^([1-3]?[A-Za-z]+)-(\d+)-(\d+)-(\d+)$')


def _note_target(note_id):
    """('genesis', chapter, verse) or ('word', 'Sng.6.5-08') for a footnote id, else None."""
    match = GENESIS_NOTE_RE.match(note_id or '')
    if match:
        return 'genesis', int(match.group(1)), int(match.group(2))
    match = WORD_NOTE_RE.match(note_id or '')
    if match:
        code, chapter, verse, word = match.groups()
        return 'word', f'{code}.{chapter}.{verse}-{word}'
    return None


def _stored_note(note_id):
    """(target, stored html) for a footnote id: '' when it has no text yet (a Genesis note is
    created on save), None when it can't exist (unknown id, or no such word)."""
    target = _note_target(note_id)
    if target is None:
        return None, None
    if target[0] == 'genesis':
        html = GenesisFootnotes.objects.filter(footnote_id=note_id).values_list('footnote_html', flat=True).first()
        return target, html or ''
    row = execute_query("SELECT footnote FROM old_testament.hebrewdata WHERE Ref = %s;", (target[1],), fetch='one')
    return target, (row[0] or '') if row else None


def _verse_notes(texts_html):
    """The footnotes linked from a verse's texts, in order: [{id, number, html, hash, kind}]."""
    notes, seen = [], set()
    for html in texts_html:
        for note_id in NOTE_LINK_RE.findall(html or ''):
            if note_id in seen:
                continue
            seen.add(note_id)
            target, stored = _stored_note(note_id)
            if target is None or stored is None:
                continue
            notes.append({'id': note_id, 'number': note_id.rsplit('-', 1)[-1], 'html': stored,
                          'hash': _hash(stored), 'kind': target[0]})
    return notes


def _resolve_location(request):
    """
    Work out which verse the page shows from ?ref=Gen.1.1, ?q=Genesis 1:1 or
    ?book=Genesis&chapter=1&verse=1. Returns (book name, chapter, verse, hebrewdata prefix,
    invalid-reference message).
    """
    invalid = ''
    book = request.GET.get('book')
    chapter = request.GET.get('chapter')
    verse = request.GET.get('verse')
    query = request.GET.get('q')
    ref_param = request.GET.get('ref')

    code = None
    if ref_param:
        parts = _verse_ref_parts(ref_param.strip())
        if parts:
            # The words live under the Ref (Joe.3.6), but the book, chapter and verse the site
            # shows come from old_testament.ot (Jol 4:6 → Joel 4:6); they differ in a few books.
            ref_code, ref_chapter, ref_verse = parts
            row = execute_query(
                "SELECT book, chapter, verse FROM old_testament.ot WHERE Ref = %s LIMIT 1;",
                ('.'.join(parts),), fetch='one',
            )
            if row and row[0]:
                return _book_name(row[0]), str(row[1]), str(row[2]), f'{ref_code}.{ref_chapter}.{ref_verse}-', ''
            code, chapter, verse = parts
            book = _book_name(code)
    elif not book and query:
        found = bible.get_references(query)
        if found:
            ref = found[0]
            book = ref.book.name.title()
            chapter = str(ref.start_chapter)
            verse = str(ref.start_verse)
        else:
            invalid = f'No verse matches "{query}".'

    if not book:
        book, chapter, verse = 'Genesis', '1', '1'
    chapter = str(chapter or '1')
    verse = str(verse or '1')
    if book in new_testament_books:
        return book, chapter, verse, None, 'This editor is for Old Testament books; use /edit/ for the New Testament.'

    if code is None:
        code = book_abbreviations.get(book, book)
        # hebrewdata.Ref can differ from book/chapter/verse (e.g. Joel 4:6 is Joe.3.6);
        # old_testament.ot has both, so resolve through it.
        row = execute_query(
            "SELECT Ref FROM old_testament.ot WHERE book = %s AND chapter = %s AND verse = %s LIMIT 1;",
            (code, chapter, verse), fetch='one',
        )
        if row and row[0]:
            parts = _verse_ref_parts(str(row[0]).strip())
            if parts:
                code, ref_chapter, ref_verse = parts
                return book, chapter, verse, f'{code}.{ref_chapter}.{ref_verse}-', invalid
    return book, chapter, verse, f'{code}.{chapter}.{verse}-', invalid


def _word_counts(column, values):
    values = [v for v in set(values) if v]
    if not values:
        return {}
    rows = execute_query(
        f"SELECT {column}, COUNT(*) FROM old_testament.hebrewdata WHERE {column} = ANY(%s) GROUP BY {column};",
        (values,), fetch='all',
    ) or []
    return {row[0]: row[1] for row in rows}


def _lexicon_strongs(strong_refs):
    """Canonical H<int> numbers of the lexical (non-grammatical) Strong's refs of a token."""
    numbers = []
    for ref in strong_refs:
        digits = re.sub(r'\D', '', ref)
        if digits and int(digits) < 9000:
            canonical = f'H{int(digits)}'
            if canonical not in numbers:
                numbers.append(canonical)
    return numbers


def _chapter_rows(prefix):
    """[(verse number, paraphrase html)] for the chapter panel, in verse order."""
    chapter_prefix = prefix.rsplit('.', 1)[0] + '.'
    code, chapter = chapter_prefix.split('.')[:2]
    if code == 'Gen':
        try:
            return [
                (str(verse), html or '')
                for verse, html in Genesis.objects.filter(chapter=int(chapter)).order_by('verse').values_list('verse', 'rbt_reader')
            ]
        except (TypeError, ValueError):
            return []
    rows = execute_query(
        """
        SELECT Ref, html FROM old_testament.hebrewdata
        WHERE Ref LIKE %s AND html IS NOT NULL
        ORDER BY CAST(SPLIT_PART(SPLIT_PART(Ref, '.', 3), '-', 1) AS INTEGER) ASC
        """,
        (f'{chapter_prefix}%',), fetch='all',
    ) or []
    seen = set()
    result = []
    for ref, html in rows:
        verse = ref.split('.')[2].split('-')[0]
        if verse in seen:
            continue
        seen.add(verse)
        result.append((verse, html))
    return result


def _chapter_numbers(code):
    rows = execute_query(
        "SELECT DISTINCT chapter FROM old_testament.ot WHERE book = %s;", (code,), fetch='all',
    ) or []
    numbers = []
    for (chapter,) in rows:
        try:
            numbers.append(int(chapter))
        except (TypeError, ValueError):
            continue
    return sorted(numbers)


# --------------------------------------------------------------------------- page

def legacy_translate_redirect(request):
    """
    The old translator (/translate/, /translate/translate/, /RBT/translate/) is replaced by
    this editor. Its links keep working: the query string (?book=&chapter=&verse=, ?ref=,
    ?q=) carries over unchanged. NT books go to the NT verse editor instead.
    """
    query = request.META.get('QUERY_STRING', '')
    target = '/edit/' if request.GET.get('book') in new_testament_books else reverse('ot_editor')
    return redirect(f'{target}?{query}' if query else target)



@login_required
def ot_editor(request):
    book, chapter, verse, prefix, invalid = _resolve_location(request)
    context = {
        'page_title': f'{book} {chapter}:{verse}',
        'book': book,
        'chapter_num': chapter,
        'verse_num': verse,
        'invalid_message': invalid,
        'tokens': [],
    }
    if prefix is None:
        return render(request, 'ot_editor.html', context)

    code = prefix.split('.')[0]
    has_lxx = table_has_column('old_testament', 'hebrewdata', 'lxx')
    columns = HEBREWDATA_COLUMNS + (', lxx' if has_lxx else '')
    rows = execute_query(
        f"SELECT {columns} FROM old_testament.hebrewdata WHERE Ref LIKE %s ORDER BY Ref ASC;",
        (f'{prefix}%',), fetch='all',
    ) or []
    rows = [tuple(row) for row in rows]
    verse_ref = prefix[:-1]
    context.update({
        'verse_ref': verse_ref,
        'verse_label': f'{book} {chapter}:{verse}',
        'chapters': _chapter_numbers(book_abbreviations.get(book, code)),
        'chapter_rows': _chapter_rows(prefix),
    })
    if not rows:
        context['invalid_message'] = invalid or f'No Hebrew words are stored for {verse_ref}.'
        return render(request, 'ot_editor.html', context)

    prev_ref, next_ref = ot_prev_next_references(verse_ref)

    texts = []
    for field in _text_fields(verse_ref):
        html = _stored_text(verse_ref, field) or ''
        texts.append({'key': field, 'label': TEXT_LABELS[field], 'html': html, 'hash': _hash(html)})
    ot_row = execute_query("SELECT literal FROM old_testament.ot WHERE Ref = %s;", (verse_ref,), fetch='one')
    literal = (ot_row[0] if ot_row else '') or ''

    try:
        smith_row = execute_query(
            "SELECT content FROM smith_translation.verses WHERE book = %s AND chapter = %s AND verse = %s;",
            (book, chapter, verse), fetch='one',
        )
        smith = smith_row[0] if smith_row else ''
    except Exception:
        smith = ''


    _, _, _, _, hebrew_clean, cards = build_heb_interlinear(rows, show_edit_buttons=True)
    cards_by_id = {card['id']: card for card in cards}

    consonantal = [row[20] for row in rows]
    pointed = [row[21] for row in rows]
    counts_consonantal = _word_counts('combined_heb', consonantal)
    counts_pointed = _word_counts('combined_heb_niqqud', pointed)

    tokens = []
    for row in rows:
        token_id, ref, eng = row[0], row[1], row[2]
        morph = row[9] or ''
        strongs = row[11] or ''
        strong_refs = split_strong_refs(strongs)
        card = cards_by_id.get(token_id, {})
        hebrew_marked = card.get('hebrew') or (row[21] or '')
        tokens.append({
            'id': token_id,
            'ref': ref,
            'number': ref.split('-')[-1],
            'english': eng or '',
            'hebrew_marked': hebrew_marked,
            'hebrew_plain': _strip_niqqud(re.sub(r'<[^>]+>', '', hebrew_marked)),
            'hebrew_niqqud': row[21] or '',
            'consonantal': row[20] or '',
            'morph': morph,
            'morphology': row[23] or '',
            'gender': row[12] if row[12] in ('m', 'f') else '0',
            'unique': str(row[10]) == '1',
            'strongs': strongs,
            'strongs_display': ' · '.join(strong_refs),
            'lexicon_strongs': _lexicon_strongs(strong_refs),
            'lexicon_html': card.get('strongs') or '',
            'lxx_words': card.get('lxx_words') or [],
            'lxx_data': card.get('lxx_data') or [],
            'footnote': row[22] or '',
            'footnote_hash': _hash(row[22] or ''),
            'footnote_marker': f'?footnote={ref.replace(".", "-")}',
            'count_consonantal': counts_consonantal.get(row[20], 1),
            'count_niqqud': counts_pointed.get(row[21], 1),
            'is_hayah': 'H1961' in strong_refs,
        })

    context.update({
        'tokens': tokens,
        'hebrew_text': ' '.join(hebrew_clean),
        'texts': texts,
        'active_text_label': TEXT_LABELS['paraphrase'],
        'literal': literal,
        'smith': smith,
        'verse_notes': _verse_notes([t['html'] for t in texts]),
        'prev_ref': prev_ref or '#',
        'next_ref': next_ref or '#',
        'reader_url': f'/{book_to_slug(book) or book}/{chapter}/{verse}/',
    })
    return render(request, 'ot_editor.html', _apply_gemini_preferences(request, context))


# --------------------------------------------------------------------------- JSON API

@require_POST
@login_json
def save_gloss(request):
    """
    POST {id, english, scope} → {english, updated, literal, verse_ids}.

    scope: 'word' changes this row only; 'consonantal' every row with the same consonants;
    'niqqud' every row with the same pointing (both skip rows flagged unique, except this one).
    """
    payload = _json_body(request)
    if payload is None:
        return JsonResponse({'error': 'Invalid JSON.'}, status=400)
    try:
        token_id = int(payload.get('id'))
    except (TypeError, ValueError):
        return JsonResponse({'error': 'id is required.'}, status=400)
    english = payload.get('english')
    scope = payload.get('scope') or 'consonantal'
    if not isinstance(english, str) or scope not in GLOSS_SCOPES:
        return JsonResponse({'error': 'english and a valid scope are required.'}, status=400)
    english = english.strip()
    if len(english) > 500:
        return JsonResponse({'error': 'Gloss is too long.'}, status=400)

    row = _token_row(token_id)
    if not row:
        return JsonResponse({'error': 'Word not found.'}, status=404)
    _, ref, old_english, consonantal, pointed, unique, _, _ = row
    prefix = _verse_prefix(ref)

    if scope == 'word' or str(unique) == '1':
        updated = execute_query("UPDATE old_testament.hebrewdata SET Eng = %s WHERE id = %s;", (english, token_id))
        verse_ids = [token_id]
        how = 'this word only' if scope == 'word' else 'a uniquely defined word'
    else:
        column, value = ('combined_heb_niqqud', pointed) if scope == 'niqqud' else ('combined_heb', consonantal)
        updated = execute_query(
            f"UPDATE old_testament.hebrewdata SET Eng = %s WHERE {column} = %s AND uniq = '0';",
            (english, value),
        )
        verse_ids = _verse_token_ids(prefix, column, value)
        how = f'{updated} words {"with" if scope == "niqqud" else "without"} niqqud'

    literal = _rebuild_literal(ref)
    _log('Hebrew Literal', ref, f'Updated RBT translation for Hebrew {pointed} from "{old_english}" to "{english}" ({how})')
    _invalidate(ref)
    logger.info('[OT EDITOR] %s gloss %s: %r -> %r (%s)', request.user.username, ref, old_english, english, scope)
    return JsonResponse({'english': english, 'updated': updated, 'literal': literal, 'verse_ids': verse_ids})


@require_POST
@login_json
def save_morphology(request):
    """POST {id, morphology} → {morphology}. Morphology is per row."""
    payload = _json_body(request)
    if payload is None:
        return JsonResponse({'error': 'Invalid JSON.'}, status=400)
    try:
        token_id = int(payload.get('id'))
    except (TypeError, ValueError):
        return JsonResponse({'error': 'id is required.'}, status=400)
    morphology = payload.get('morphology')
    if not isinstance(morphology, str) or len(morphology) > 500:
        return JsonResponse({'error': 'morphology is required.'}, status=400)
    row = _token_row(token_id)
    if not row:
        return JsonResponse({'error': 'Word not found.'}, status=404)
    morphology = morphology.strip()
    execute_query("UPDATE old_testament.hebrewdata SET morphology = %s WHERE id = %s;", (morphology, token_id))
    _invalidate(row[1])
    return JsonResponse({'morphology': morphology})


@require_POST
@login_json
def save_gender(request):
    """POST {id, gender: 'm'|'f'|'0'} → {gender, updated, verse_ids}. Applies to every
    non-unique row with the same consonants, as the old editor did."""
    payload = _json_body(request)
    if payload is None:
        return JsonResponse({'error': 'Invalid JSON.'}, status=400)
    try:
        token_id = int(payload.get('id'))
    except (TypeError, ValueError):
        return JsonResponse({'error': 'id is required.'}, status=400)
    gender = payload.get('gender')
    if gender not in ('m', 'f', '0'):
        return JsonResponse({'error': 'gender must be m, f or 0.'}, status=400)
    row = _token_row(token_id)
    if not row:
        return JsonResponse({'error': 'Word not found.'}, status=404)
    _, ref, _, consonantal, _, _, _, _ = row
    updated = execute_query(
        "UPDATE old_testament.hebrewdata SET color = %s WHERE combined_heb = %s AND uniq = '0';",
        (gender, consonantal),
    )
    execute_query("UPDATE old_testament.hebrewdata SET color = %s WHERE id = %s;", (gender, token_id))
    verse_ids = _verse_token_ids(_verse_prefix(ref), 'combined_heb', consonantal)
    if token_id not in verse_ids:
        verse_ids.append(token_id)
    _log('Hebrew Literal', ref, f'Updated {consonantal} in color with "{gender}" for {updated} rows.')
    _invalidate(ref)
    return JsonResponse({'gender': gender, 'updated': updated, 'verse_ids': verse_ids})


@require_POST
@login_json
def save_verse(request):
    """
    POST {verse_ref, field, html, base_hash} → {hash, saved}.

    field is 'paraphrase' (default) or, for Genesis, 'literal'. base_hash is the hash of the
    HTML the editor loaded. If the stored text changed since (another tab, an older editor),
    nothing is written and a 409 carries the current HTML so the page can reload it.
    """
    payload = _json_body(request)
    if payload is None:
        return JsonResponse({'error': 'Invalid JSON.'}, status=400)
    verse_ref = str(payload.get('verse_ref') or '').split('-')[0]
    field = payload.get('field') or 'paraphrase'
    html = payload.get('html')
    base_hash = payload.get('base_hash')
    if not _verse_ref_parts(verse_ref) or not isinstance(html, str) or not isinstance(base_hash, str):
        return JsonResponse({'error': 'verse_ref, html and base_hash are required.'}, status=400)
    if field not in TEXT_FIELDS:
        return JsonResponse({'error': 'field must be paraphrase or literal.'}, status=400)
    if len(html) > MAX_HTML_LENGTH:
        return JsonResponse({'error': 'Verse HTML is too long.'}, status=400)

    current = _stored_text(verse_ref, field)
    if current is None:
        return JsonResponse({'error': f'This verse has no stored {TEXT_LABELS[field].lower()}.'}, status=404)
    if _hash(current) != base_hash:
        return JsonResponse(
            {'error': 'This text was changed elsewhere.', 'html': current, 'hash': _hash(current)}, status=409,
        )

    html = _strip_editor_artifacts(html).strip()
    if html == current:
        return JsonResponse({'hash': base_hash, 'saved': False})

    _write_text(verse_ref, field, html)
    cleared = _invalidate(verse_ref, field)
    code = verse_ref.split('.')[0]
    version = TEXT_LOG_VERSIONS.get((code, field), 'Paraphrase')
    _log(version, verse_ref, f'Updated {TEXT_LABELS[field]} for {_reference_label(verse_ref)}: {html}')
    logger.info('[OT EDITOR] %s saved %s %s (%d cache keys cleared)', request.user.username, field, verse_ref, len(cleared))
    return JsonResponse({'hash': _hash(html), 'saved': True})


@require_GET
@login_json
def chapter_texts(request):
    """
    GET ?book=Genesis&chapter=1 → {verses: [{key, verse, ref, text, html, hash}]}: a chapter's
    editable verse texts, for the chapter page's inline editor (chapter-editor/, OT mode), which
    saves them through save_verse. key matches the page's .rbt-verse wrappers: the verse number
    for the RBT Translation (paraphrase), 'literal:N' for Genesis's Hebrew literal.
    """
    book = request.GET.get('book') or ''
    try:
        chapter = int(request.GET.get('chapter'))
    except (TypeError, ValueError):
        return JsonResponse({'error': 'book and chapter are required.'}, status=400)
    verses = []

    def add(key, verse, ref, field, html):
        verses.append({'key': key, 'verse': str(verse), 'ref': ref, 'text': field, 'html': html, 'hash': _hash(html)})

    if book == 'Genesis':
        for verse, reader, literal in Genesis.objects.filter(chapter=chapter).order_by('verse').values_list('verse', 'rbt_reader', 'html'):
            ref = f'Gen.{chapter}.{verse}'
            add(str(verse), verse, ref, 'paraphrase', reader or '')
            add(f'literal:{verse}', verse, ref, 'literal', literal or '')
    elif book in old_testament_books:
        code = book_abbreviations.get(book, book)
        for verse, _html in _chapter_rows(f'{code}.{chapter}.1-'):
            ref = f'{code}.{chapter}.{int(verse)}'
            html = _stored_text(ref, 'paraphrase')
            if html is not None:
                add(str(int(verse)), int(verse), ref, 'paraphrase', html)
    else:
        return JsonResponse({'error': 'Unknown Old Testament book.'}, status=400)
    return JsonResponse({'verses': verses})


@login_json
def footnote(request):
    """
    GET ?id=<row id> → {html, hash}; POST {id, html, base_hash} → {html, hash}.
    A token's footnote (old_testament.hebrewdata.footnote). Empty html removes it.
    """
    if request.method == 'GET':
        try:
            token_id = int(request.GET.get('id'))
        except (TypeError, ValueError):
            return JsonResponse({'error': 'id is required.'}, status=400)
        row = execute_query("SELECT footnote FROM old_testament.hebrewdata WHERE id = %s;", (token_id,), fetch='one')
        if not row:
            return JsonResponse({'error': 'Word not found.'}, status=404)
        current = row[0] or ''
        return JsonResponse({'html': current, 'hash': _hash(current)})
    if request.method != 'POST':
        return JsonResponse({'error': 'GET or POST only.'}, status=405)

    payload = _json_body(request)
    if payload is None:
        return JsonResponse({'error': 'Invalid JSON.'}, status=400)
    try:
        token_id = int(payload.get('id'))
    except (TypeError, ValueError):
        return JsonResponse({'error': 'id is required.'}, status=400)
    html = payload.get('html')
    base_hash = payload.get('base_hash')
    if not isinstance(html, str) or not isinstance(base_hash, str):
        return JsonResponse({'error': 'html and base_hash are required.'}, status=400)
    if len(html) > MAX_HTML_LENGTH:
        return JsonResponse({'error': 'Footnote is too long.'}, status=400)
    row = execute_query("SELECT Ref, footnote FROM old_testament.hebrewdata WHERE id = %s;", (token_id,), fetch='one')
    if not row:
        return JsonResponse({'error': 'Word not found.'}, status=404)
    ref, current = row[0], row[1] or ''
    if _hash(current) != base_hash:
        return JsonResponse(
            {'error': 'This footnote was changed elsewhere.', 'html': current, 'hash': _hash(current)}, status=409,
        )
    html = _strip_editor_artifacts(html).strip()
    if html != current:
        execute_query("UPDATE old_testament.hebrewdata SET footnote = %s WHERE id = %s;", (html, token_id))
        plain = re.sub(r'<a\s+.*?>(.*?)</a>', r'\1', html)
        _log('Hebrew Footnote', ref, f'Updated footnote on {ref}: {plain}')
        _invalidate(ref)
        logger.info('[OT EDITOR] %s saved footnote %s', request.user.username, ref)
    return JsonResponse({'html': html, 'hash': _hash(html)})


@login_json
def verse_note(request):
    """
    GET ?id=1-4-15b → {id, number, html, hash, kind}; POST {id, html, base_hash} → {html, hash}.
    A footnote linked from verse text (see _note_target), edited inline on the verse page. A
    Genesis note that doesn't exist yet is created; one changed elsewhere since base_hash is
    never overwritten (409 with the stored version).
    """
    if request.method == 'GET':
        note_id = request.GET.get('id') or ''
        target, stored = _stored_note(note_id)
        if stored is None:
            return JsonResponse({'error': 'Unknown footnote.'}, status=404)
        return JsonResponse({'id': note_id, 'number': note_id.rsplit('-', 1)[-1], 'html': stored,
                             'hash': _hash(stored), 'kind': target[0]})
    if request.method != 'POST':
        return JsonResponse({'error': 'GET or POST only.'}, status=405)
    payload = _json_body(request)
    if payload is None:
        return JsonResponse({'error': 'Invalid JSON.'}, status=400)
    note_id = str(payload.get('id') or '')
    html = payload.get('html')
    base_hash = payload.get('base_hash')
    if not isinstance(html, str) or not isinstance(base_hash, str):
        return JsonResponse({'error': 'id, html and base_hash are required.'}, status=400)
    if len(html) > MAX_HTML_LENGTH:
        return JsonResponse({'error': 'Footnote is too long.'}, status=400)
    target, current = _stored_note(note_id)
    if current is None:
        return JsonResponse({'error': 'Unknown footnote.'}, status=404)
    if _hash(current) != base_hash:
        return JsonResponse({'error': 'This footnote was changed elsewhere.', 'html': current, 'hash': _hash(current)}, status=409)
    html = _strip_editor_artifacts(html).strip()
    if html != current:
        plain = re.sub(r'<a\s+.*?>(.*?)</a>', r'\1', html)
        if target[0] == 'genesis':
            GenesisFootnotes.objects.update_or_create(footnote_id=note_id, defaults={'footnote_html': html})
            chapter, verse = target[1], target[2]
            _log('Hebrew Footnote', f'Gen.{chapter}.{verse}', f'Updated footnote {note_id}: {plain}')
            _clear_reader_cache('Genesis', chapter, verse)
        else:
            ref = target[1]
            execute_query("UPDATE old_testament.hebrewdata SET footnote = %s WHERE Ref = %s;", (html, ref))
            _log('Hebrew Footnote', ref, f'Updated footnote on {ref}: {plain}')
            _invalidate(ref)
        logger.info('[OT EDITOR] %s saved footnote %s', request.user.username, note_id)
    return JsonResponse({'html': html, 'hash': _hash(html)})


@require_GET
@login_json
def verse_state(request):
    """GET ?verse_ref=Gen.1.1&field=paraphrase → {html, hash, literal}: what is stored now."""
    verse_ref = str(request.GET.get('verse_ref') or '').split('-')[0]
    field = request.GET.get('field') or 'paraphrase'
    if not _verse_ref_parts(verse_ref) or field not in TEXT_FIELDS:
        return JsonResponse({'error': 'verse_ref and a valid field are required.'}, status=400)
    html = _stored_text(verse_ref, field)
    if html is None:
        return JsonResponse({'error': 'Verse text not found.'}, status=404)
    ot_row = execute_query("SELECT literal FROM old_testament.ot WHERE Ref = %s;", (verse_ref,), fetch='one')
    return JsonResponse({'html': html, 'hash': _hash(html), 'literal': (ot_row[0] if ot_row else '') or ''})
