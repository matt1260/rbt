"""
Read-only scholarship lookups for agents (Phase 2 of the rbt/ abilities).

Verses and chapters with their Hebrew/Greek and interlinear words, Hebrew and Greek word
search, lexicon entries, every occurrence of a word with the RBT gloss at each, footnotes,
and the edit log. Nothing here writes anything, and nothing touches the translation queue
(search/agent_translation.py); translation agents may consult these when the English they
are translating is ambiguous or grammatically unusual.

Reached through the private agent API (search/views/agent_api.py) from the WordPress
abilities rbt/get-verse, rbt/get-chapter, rbt/search-hebrew, rbt/search-greek,
rbt/get-lexeme, rbt/get-occurrences, rbt/get-footnotes and rbt/get-revisions.
"""
import re
from collections import Counter
from html import unescape

from search.db_utils import execute_query

MAX_LIMIT = 500
TAG = re.compile(r'<[^>]+>')
SPACE = re.compile(r'\s+')
NIQQUD = re.compile(r'[֑-ֽֿׁ-ׇׅ]')
# old_testament.hebrewdata refs use these prefixes where old_testament.ot.book differs.
HEBREWDATA_PREFIX_BOOK = {'Joe': 'Joel', 'Nah': 'Nahum'}
SPECIAL = ('Joseph and Aseneth', 'Gospel of Judas')


def _text(html):
    """Plain text of an HTML fragment (tags removed, entities decoded, spaces collapsed)."""
    return SPACE.sub(' ', unescape(TAG.sub(' ', html or ''))).strip()


# Embedded in verse HTML but not part of the verse: image/video notes and footnote markers.
NOT_VERSE_TEXT = ('video', 'audio', 'img', 'sup', '.tooltip-container', '.tooltip', '.tooltip2', 'a.sdfootnoteanc',
                  '.pp-media-store', 'template')


def _verse_text(html):
    """The words of a verse: its HTML without media, notes or footnote markers, as plain text."""
    if not html:
        return ''
    from bs4 import BeautifulSoup
    soup = BeautifulSoup(html, 'html.parser')
    for node in soup.select(', '.join(NOT_VERSE_TEXT)):
        node.decompose()
    return _text(str(soup))


def _limit(value, default=50):
    try:
        return max(1, min(int(value or default), MAX_LIMIT))
    except (TypeError, ValueError):
        return default


def _offset(value):
    try:
        return max(0, int(value or 0))
    except (TypeError, ValueError):
        return 0


# ---------------------------------------------------------------------------
# Books and references

def resolve_book(name):
    """(canonical book name, abbreviation, 'genesis'|'ot'|'nt'|'special') for a book name or abbreviation."""
    from translate.translator import (
        book_abbreviations, convert_book_name, new_testament_books, normalize_book_name, old_testament_books,
    )
    if not name or not str(name).strip():
        raise ValueError('book is required')
    raw = str(name).strip()
    if raw in SPECIAL:
        return raw, raw, 'special'
    book = normalize_book_name(raw) if raw not in book_abbreviations else raw
    if book not in book_abbreviations:
        converted = convert_book_name(raw)
        if converted and converted in book_abbreviations:
            book = converted
        elif raw in HEBREWDATA_PREFIX_BOOK:
            book = HEBREWDATA_PREFIX_BOOK[raw]
        else:
            raise ValueError(f'Unknown book {raw!r}')
    book = normalize_book_name(book)
    abbr = book_abbreviations.get(book) or book_abbreviations.get(book.replace(' ', ''))
    if book == 'Genesis':
        return book, abbr, 'genesis'
    if book in new_testament_books or book.replace(' ', '') in new_testament_books:
        return book, abbr, 'nt'
    if book in old_testament_books or book.replace(' ', '') in old_testament_books:
        return book, abbr, 'ot'
    raise ValueError(f'Unknown book {raw!r}')


def _ref_parts(ref):
    """'Gen.1.1-03' -> (book, chapter, verse, word position)."""
    from translate.translator import convert_book_name
    m = re.match(r'^([1-3]?[A-Za-z]+)\.(\d+)\.(\d+)(?:-(\d+))?', ref or '')
    if not m:
        return None, None, None, None
    prefix = m.group(1)
    book = HEBREWDATA_PREFIX_BOOK.get(prefix) or convert_book_name(prefix) or prefix
    return book, int(m.group(2)), int(m.group(3)), int(m.group(4)) if m.group(4) else None


def _ot_prefixes(book, abbr):
    """Ref prefixes an OT book's verses may be stored under (the abbreviation, plus e.g. 'Joe' for Joel)."""
    return [abbr] + [p for p, b in HEBREWDATA_PREFIX_BOOK.items() if b == book and p != abbr]


def _strongs_list(field):
    from translate.translator import split_strong_refs
    return split_strong_refs(field or '')


def _hebrew_words(ref_prefix):
    rows = execute_query(
        'SELECT ref, eng, combined_heb_niqqud, combined_heb, morph, morphology, strongs, footnote '
        'FROM old_testament.hebrewdata WHERE ref LIKE %s ORDER BY ref', (f'{ref_prefix}-%',), fetch='all') or []
    return [{
        'position': _ref_parts(r[0])[3], 'hebrew': r[2] or '', 'consonantal': r[3] or '', 'gloss': r[1] or '',
        'strongs': _strongs_list(r[6]), 'morph': r[4] or '', 'morphology': r[5] or '', 'footnote': r[7] or None,
    } for r in rows]


def _greek_words(book, chapter, verse):
    from search.views.chapter_views_part1 import fetch_greek_interlinear_rows
    return [{
        'position': n, 'greek': w.get('raw_lemma') or w.get('lemma'), 'headword': w.get('logeion'),
        'transliteration': w.get('translit'), 'gloss': w.get('english'), 'strongs': w.get('strongs'),
        'morph': w.get('morph'), 'morphology': w.get('morph_desc'), 'variant_note': w.get('variant'),
    } for n, w in enumerate(fetch_greek_interlinear_rows(book, chapter, verse) or [], start=1)]


def _footnote_ids(*htmls):
    from search.views.footnote_views import FOOTNOTE_LINK_PATTERN
    seen = []
    for html in htmls:
        for fid in re.findall(FOOTNOTE_LINK_PATTERN, html or ''):
            fid = unescape(fid)
            if fid not in seen:
                seen.append(fid)
    return seen


# ---------------------------------------------------------------------------
# Verses and chapters

def get_verse(book, chapter, verse, parallels=True, interlinear=True):
    """One verse: RBT literal and paraphrase, the Hebrew or Greek, the interlinear words
    (word, gloss, Strong's, parsing), footnote ids and the parallel translations."""
    book, abbr, kind = resolve_book(book)
    chapter, verse = int(chapter), int(verse)
    out = {'book': book, 'chapter': chapter, 'verse': verse, 'reference': f'{book} {chapter}:{verse}'}
    if kind == 'special':
        return _special_verse(book, chapter, verse, out)
    if kind == 'genesis':
        from search.models import Genesis
        row = Genesis.objects.filter(chapter=chapter, verse=verse).first()
        if not row:
            raise ValueError(f'No verse {out["reference"]}')
        literal, paraphrase, original, ref = row.html, row.rbt_reader, row.hebrew, f'Gen.{chapter}.{verse}'
    elif kind == 'ot':
        # The reader follows each verse's ref (English numbering where it differs, as in Joel and
        # Malachi); old_testament.ot's chapter/verse columns are the Hebrew numbering.
        row = None
        for prefix in _ot_prefixes(book, abbr):
            row = execute_query('SELECT ref, html, literal, hebrew, chapter, verse FROM old_testament.ot WHERE ref=%s',
                                (f'{prefix}.{chapter}.{verse}',), fetch='one')
            if row:
                break
        if not row:
            row = execute_query('SELECT ref, html, literal, hebrew, chapter, verse FROM old_testament.ot WHERE book=%s '
                                'AND chapter=%s AND verse=%s', (abbr, str(chapter), str(verse)), fetch='one')
        if not row:
            raise ValueError(f'No verse {out["reference"]}')
        ref, paraphrase, literal, original, heb_ch, heb_v = row
        if (str(heb_ch), str(heb_v)) != (str(chapter), str(verse)):
            out['hebrew_numbering'] = f'{book} {heb_ch}:{heb_v}'
    else:
        row = execute_query('SELECT rbt, versetext FROM new_testament.nt WHERE book=%s AND chapter=%s AND startverse=%s',
                            (abbr, chapter, verse), fetch='one')
        if not row:
            raise ValueError(f'No verse {out["reference"]}')
        literal, original = row
        paraphrase, ref = None, None
    out['language'] = 'greek' if kind == 'nt' else 'hebrew'
    out['original'] = _text(original)
    out['literal'] = {'text': _verse_text(literal), 'html': literal}
    if paraphrase and paraphrase != literal:
        out['paraphrase'] = {'text': _verse_text(paraphrase), 'html': paraphrase}
    if interlinear:
        out['words'] = _greek_words(book, chapter, verse) if kind == 'nt' else _hebrew_words(ref)
    out['footnote_ids'] = _footnote_ids(literal, paraphrase)
    if parallels:
        out['parallels'] = _parallels(book, chapter, verse)
    return out


def _parallels(book, chapter, verse):
    """Smith, LITV and Brenton as the verse page shows them (each in its own numbering)."""
    from search.views.chapter_views_part1 import get_results
    try:
        data = get_results(book, chapter, verse, 'en') or {}
    except Exception:  # noqa: BLE001 - parallels are a convenience
        return {}
    out = {}
    for key, label in (('slt', 'Julia Smith (1876)'), ('litv', 'LITV'), ('eng_lxx', 'Brenton Septuagint')):
        text = _text(data.get(key) if isinstance(data.get(key), str) else '')
        if text:
            out[label] = text
    return out


def _special_verse(book, chapter, verse, out):
    if book == 'Joseph and Aseneth':
        row = execute_query('SELECT greek, english FROM joseph_aseneth.aseneth WHERE chapter=%s AND verse=%s',
                            (str(chapter), str(verse)), fetch='one') \
            or execute_query('SELECT greek, english FROM joseph_aseneth.aseneth WHERE chapter=%s AND verse=%s',
                             (chapter, verse), fetch='one')
        if not row:
            raise ValueError(f'No verse {out["reference"]}')
        out.update(language='greek', original=_text(row[0]), literal={'text': _verse_text(row[1]), 'html': row[1]})
        return out
    rows = execute_query('SELECT line_num, coptic, greek, english, notes FROM gospel_of_judas.judas_interlinear '
                         'WHERE codex=%s ORDER BY line_num', (chapter,), fetch='all') or []
    out.update(reference=f'Gospel of Judas, codex page {chapter}', language='coptic', lines=[
        {'line': r[0], 'coptic': r[1], 'greek': r[2], 'english': r[3], 'notes': r[4]} for r in rows])
    return out


def get_chapter(book, chapter, text_format='text', original=True):
    """A whole chapter, verse by verse: literal, paraphrase (where different) and the Hebrew/Greek."""
    book, abbr, kind = resolve_book(book)
    chapter = int(chapter)
    fmt = (lambda h: h or '') if text_format == 'html' else _verse_text
    verses = []
    if kind == 'genesis':
        from search.models import Genesis
        for r in Genesis.objects.filter(chapter=chapter).order_by('verse'):
            verses.append((r.verse, r.html, r.rbt_reader, r.hebrew))
    elif kind == 'ot':
        rows = []
        for prefix in _ot_prefixes(book, abbr):
            rows = execute_query('SELECT ref, literal, html, hebrew FROM old_testament.ot WHERE ref LIKE %s',
                                 (f'{prefix}.{chapter}.%',), fetch='all') or []
            if rows:
                break
        verses = sorted(((_ref_parts(ref)[2], lit, html, heb) for ref, lit, html, heb in rows), key=lambda x: x[0])
    elif kind == 'nt':
        rows = execute_query('SELECT startverse, rbt, versetext FROM new_testament.nt WHERE book=%s AND chapter=%s '
                             'ORDER BY startverse', (abbr, chapter), fetch='all') or []
        verses = [(int(v), rbt, None, greek) for v, rbt, greek in rows]
    elif book == 'Joseph and Aseneth':
        rows = execute_query('SELECT verse, english, greek FROM joseph_aseneth.aseneth WHERE chapter=%s',
                             (str(chapter),), fetch='all') or []
        verses = sorted(((int(v), eng, None, gr) for v, eng, gr in rows if str(v).isdigit()), key=lambda x: x[0])
    else:
        return get_verse(book, chapter, 1)
    if not verses:
        raise ValueError(f'No chapter {book} {chapter}')
    out = []
    for v, literal, paraphrase, orig in verses:
        item = {'verse': v, 'literal': fmt(literal)}
        if paraphrase and paraphrase != literal:
            item['paraphrase'] = fmt(paraphrase)
        if original:
            item['original'] = _text(orig)
        out.append(item)
    return {'book': book, 'chapter': chapter, 'language': 'greek' if kind in ('nt', 'special') else 'hebrew',
            'verses': out}


# ---------------------------------------------------------------------------
# Search

def _book_prefix_clause(book, column):
    if not book:
        return '', ()
    name, abbr, kind = resolve_book(book)
    prefixes = {abbr} | {p for p, b in HEBREWDATA_PREFIX_BOOK.items() if b == name}
    return ' AND (' + ' OR '.join([f'{column} LIKE %s'] * len(prefixes)) + ')', tuple(f'{p}.%' for p in prefixes)


def search_hebrew(query, field='form', book=None, limit=50, offset=0):
    """Hebrew words by form (with or without vowel points), RBT gloss, Strong's number or parsing.

    field: 'form' | 'gloss' | 'strongs' | 'morph'."""
    from translate.translator import get_strongs_numeric_value
    q = (query or '').strip()
    if not q:
        raise ValueError('query is required')
    limit, offset = _limit(limit), _offset(offset)
    where, params = _book_prefix_clause(book, 'ref')
    if field == 'form':
        if NIQQUD.search(q):
            cond, args = 'combined_heb_niqqud LIKE %s', (f'%{q}%',)
        else:
            cond, args = 'combined_heb LIKE %s', (f'%{NIQQUD.sub("", q)}%',)
    elif field == 'gloss':
        cond, args = 'eng ILIKE %s', (f'%{q}%',)
    elif field == 'morph':
        cond, args = '(morph ILIKE %s OR morphology ILIKE %s)', (f'%{q}%', f'%{q}%')
    elif field == 'strongs':
        number = get_strongs_numeric_value(q.upper() if q.upper().startswith('H') else f'H{q}')
        if number is None:
            raise ValueError(f'Not a Hebrew Strong\'s number: {q!r}')
        cond, args = 'strongs LIKE %s', (f'%{number}%',)
    else:
        raise ValueError("field must be 'form', 'gloss', 'strongs' or 'morph'")
    rows = execute_query(
        f'SELECT ref, eng, combined_heb_niqqud, combined_heb, strongs, morph, morphology FROM old_testament.hebrewdata '
        f'WHERE {cond}{where} ORDER BY id LIMIT %s', args + params + (5000,), fetch='all') or []
    if field == 'strongs':  # a bare substring match is unsafe ('853' is inside '8530'): confirm each
        rows = [r for r in rows if any(get_strongs_numeric_value(s) == number for s in _strongs_list(r[4]))]
    total = len(rows)
    hits = []
    for r in rows[offset:offset + limit]:
        b, c, v, pos = _ref_parts(r[0])
        hits.append({'reference': f'{b} {c}:{v}', 'book': b, 'chapter': c, 'verse': v, 'position': pos,
                     'hebrew': r[2], 'consonantal': r[3], 'gloss': r[1], 'strongs': _strongs_list(r[4]),
                     'morph': r[5], 'morphology': r[6]})
    return {'query': q, 'field': field, 'total': total, 'capped': total >= 5000, 'offset': offset, 'results': hits}


def search_greek(query, field='form', book=None, limit=50, offset=0):
    """Greek New Testament words by form, RBT gloss, Strong's number or parsing.

    field: 'form' | 'gloss' | 'strongs' | 'morph'."""
    q = (query or '').strip()
    if not q:
        raise ValueError('query is required')
    limit, offset = _limit(limit), _offset(offset)
    where, params = _book_prefix_clause(book, 'verse')
    if field == 'form':
        cond, args = '(lemma ILIKE %s OR translit ILIKE %s)', (f'%{q}%', f'%{q}%')
    elif field == 'gloss':
        cond, args = 'english ILIKE %s', (f'%{q}%',)
    elif field == 'morph':
        cond, args = '(morph ILIKE %s OR morph_desc ILIKE %s)', (f'%{q}%', f'%{q}%')
    elif field == 'strongs':
        digits = re.sub(r'\D', '', q)
        if not digits:
            raise ValueError(f'Not a Greek Strong\'s number: {q!r}')
        cond, args = r"strongs::text ~ %s", (rf'(^|[^0-9]){int(digits)}([^0-9]|$)',)
    else:
        raise ValueError("field must be 'form', 'gloss', 'strongs' or 'morph'")
    total = execute_query(f'SELECT count(*) FROM rbt_greek.strongs_greek WHERE {cond}{where}', args + params, fetch='one')[0]
    rows = execute_query(
        f'SELECT verse, lemma, translit, english, strongs, morph, morph_desc FROM rbt_greek.strongs_greek '
        f'WHERE {cond}{where} ORDER BY verse LIMIT %s OFFSET %s', args + params + (limit, offset), fetch='all') or []
    hits = []
    for r in rows:
        b, c, v, pos = _ref_parts(r[0])
        hits.append({'reference': f'{b} {c}:{v}', 'book': b, 'chapter': c, 'verse': v, 'position': pos,
                     'greek': r[1], 'transliteration': r[2], 'gloss': r[3], 'strongs': r[4],
                     'morph': r[5], 'morphology': r[6]})
    return {'query': q, 'field': field, 'total': total, 'offset': offset, 'results': hits}


# ---------------------------------------------------------------------------
# Lexicon and occurrences

def _parse_strongs(strongs):
    s = (strongs or '').strip().upper()
    m = re.match(r'^([HG])0*(\d+)[A-Z]?$', s)
    if not m:
        raise ValueError(f"strongs must look like 'H1254' or 'G3056', not {strongs!r}")
    return m.group(1), int(m.group(2))


def get_lexeme(strongs):
    """Lexicon data for a Strong's number: Hebrew from Strong's, BDB, Fürst and Gesenius (with the
    RBT's own notes where it has them); Greek from the RBT interlinear (no Greek dictionary is stored)."""
    lang, number = _parse_strongs(strongs)
    if lang == 'H':
        from translate.translator import get_lexicon_word_data
        data = get_lexicon_word_data(f'H{number}')
        if not data:
            raise ValueError(f'No lexicon entry for H{number}')
        return {
            'strongs': f'H{number}', 'language': 'hebrew', 'lemma': data.get('lemma'), 'transliteration': data.get('xlit'),
            'pronunciation': data.get('pron'), 'derivation': data.get('derivation'),
            'strongs_definition': data.get('strongs_def'), 'kjv_usage': data.get('kjv_def'),
            'rbt_note': _text(data.get('description_html')) or None,
            'bdb': _text(data.get('bdb_html'))[:6000] or None,
            'fuerst': [{'form': e.get('lexeme_form') or e.get('hebrew_word'), 'part_of_speech': e.get('part_of_speech'),
                        'root': e.get('root'), 'definition': _text(e.get('definition_html') or e.get('definition'))[:2000],
                        'page': e.get('source_page')} for e in (data.get('fuerst_entries') or [])],
            'gesenius': [{k: (_text(v)[:2000] if isinstance(v, str) else v) for k, v in e.items()}
                         for e in (data.get('gesenius_entries') or [])][:5],
            'occurrence_count': data.get('occurrence_count'),
            'related_words': data.get('related_words'),
            'url': f'https://read.realbible.tech/lexicon/hebrew/h{number}/',
        }
    from search.greek_headwords import logeion_url
    pattern = rf'(^|[^0-9]){number}([^0-9]|$)'
    rows = execute_query('SELECT lemma, translit, english FROM rbt_greek.strongs_greek WHERE strongs::text ~ %s',
                         (pattern,), fetch='all') or []
    if not rows:
        raise ValueError(f'No Greek occurrences of G{number}')
    forms = Counter(r[0] for r in rows if r[0])
    glosses = Counter((r[2] or '').strip() for r in rows if r[2])
    headword = None
    try:
        from search.greek_headwords import logeion_headword
        headword = logeion_headword(None, str(number), forms.most_common(1)[0][0])
    except Exception:  # noqa: BLE001
        pass
    return {
        'strongs': f'G{number}', 'language': 'greek', 'headword': headword,
        'occurrence_count': len(rows),
        'forms': [{'form': f, 'count': n} for f, n in forms.most_common(20)],
        'rbt_glosses': [{'gloss': g, 'count': n} for g, n in glosses.most_common(20)],
        'logeion': logeion_url(headword) if headword else None,
        'note': 'No Greek dictionary is stored; forms and glosses are from the RBT interlinear.',
    }


def get_occurrences(strongs, limit=100, offset=0):
    """Every occurrence of a word, with the RBT gloss at each and how often each gloss is used."""
    lang, number = _parse_strongs(strongs)
    limit, offset = _limit(limit, 100), _offset(offset)
    if lang == 'H':
        from translate.translator import get_hebrew_word_occurrences
        total, rows = get_hebrew_word_occurrences(f'H{number}', limit=100000)
        items = []
        for r in rows:
            b, c, v, pos = _ref_parts(r['ref'])
            items.append({'reference': f'{b} {c}:{v}', 'book': b, 'chapter': c, 'verse': v, 'position': pos,
                          'hebrew': r.get('combined_heb_niqqud'), 'gloss': r.get('eng')})
    else:
        rows = execute_query(
            'SELECT verse, lemma, english FROM rbt_greek.strongs_greek WHERE strongs::text ~ %s ORDER BY verse',
            (rf'(^|[^0-9]){number}([^0-9]|$)',), fetch='all') or []
        items = []
        for r in rows:
            b, c, v, pos = _ref_parts(r[0])
            items.append({'reference': f'{b} {c}:{v}', 'book': b, 'chapter': c, 'verse': v, 'position': pos,
                          'greek': r[1], 'gloss': r[2]})
        total = len(items)
    glosses = Counter((i.get('gloss') or '').strip() for i in items if i.get('gloss'))
    return {'strongs': f'{lang}{number}', 'total': total,
            'gloss_distribution': [{'gloss': g, 'count': n} for g, n in glosses.most_common()],
            'offset': offset, 'occurrences': items[offset:offset + limit]}


# ---------------------------------------------------------------------------
# Footnotes and revisions

def get_footnotes(book, chapter, verse=None):
    """The footnotes of a verse (or a whole chapter), as text and HTML."""
    from search.views.footnote_views import get_footnote
    name, _, kind = resolve_book(book)
    chapter = int(chapter)
    if verse is not None:
        v = get_verse(name, chapter, int(verse), parallels=False, interlinear=False)
        located = [(fid, int(verse)) for fid in v['footnote_ids']]
    else:
        ch = get_chapter(name, chapter, text_format='html', original=False)
        located = []
        for item in ch['verses']:
            for fid in _footnote_ids(item.get('literal'), item.get('paraphrase')):
                located.append((fid, item['verse']))
    notes = []
    for fid, v in located:
        html = get_footnote(fid, name, chapter, v) or ''
        notes.append({'id': fid, 'verse': v, 'text': _text(html), 'html': html})
    return {'book': name, 'chapter': chapter, 'verse': verse, 'footnotes': notes}


def get_revisions(book=None, chapter=None, verse=None, version=None, since=None, limit=50, offset=0):
    """The edit log (newest first). Each entry records the text AFTER the edit; earlier text is
    only known where an earlier entry for the same reference exists."""
    from search.models import TranslationUpdates
    limit, offset = _limit(limit), _offset(offset)
    qs = TranslationUpdates.objects.all()
    if book:
        name, abbr, _ = resolve_book(book)
        ref = name if chapter is None else (f'{name} {int(chapter)}:' if verse is None else f'{name} {int(chapter)}:{int(verse)}')
        dotted = abbr if chapter is None else (f'{abbr}.{int(chapter)}.' if verse is None else f'{abbr}.{int(chapter)}.{int(verse)}')
        from django.db.models import Q
        exact_verse = Q(reference__iexact=ref) | Q(reference__istartswith=f'{ref} ') | Q(reference__istartswith=f'{dotted}-')
        qs = qs.filter((exact_verse if verse is not None else (Q(reference__istartswith=ref) | Q(reference__istartswith=dotted))))
    if version:
        qs = qs.filter(version__iexact=version)
    if since:
        qs = qs.filter(date__gte=since)
    total = qs.count()
    rows = qs.order_by('-date')[offset:offset + limit]
    return {'total': total, 'offset': offset, 'revisions': [{
        'date': r.date.isoformat(), 'version': r.version, 'reference': r.reference, 'text': _text(r.update_text)[:4000],
    } for r in rows], 'note': 'Each entry holds the text after the edit, not before.'}
