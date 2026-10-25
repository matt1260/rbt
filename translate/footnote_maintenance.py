"""
NT footnote clean-up: plan, apply, back up and restore (used by the clean-up page at
/translate/footnotes/cleanup/ and by `manage.py normalize_footnotes`).

A plan lists, for the chosen books:
- footnotes whose HTML the normaliser (translate/footnote_cleanup.py) changes; one whose
  visible wording would change is never planned, only listed;
- repeated footnote ids (John's table has no unique index) whose copies are identical, or
  all but one empty: the extra rows are dropped; differing copies are only listed;
- translated footnotes (verse_translations) cleaned the same way, with their source_hash
  moved to the cleaned English, so they stay current (only markup changes, not wording);
- the verses whose reader cache must be cleared.

apply_plan() writes it in one transaction and returns the backup to keep;
restore_backup() puts a backup back.
"""
import collections
import re
from datetime import datetime

from django.db import connection, transaction

from search.models import VerseTranslation
from search.translation_utils import source_fingerprint
from translate.footnote_cleanup import _letters, normalize as normalize_uncached, normalize_cached as normalize
from translate.translator import convert_book_name

ANCHOR_RE = re.compile(r'\?footnote=(\d+)-(\d+)-([0-9A-Za-z]+)(?:&amp;|&)book=([0-9A-Za-z]+)')
ID_RE = re.compile(r'^[0-9A-Za-z]+-\d+[a-z]{0,3}$')
TABLE_RE = re.compile(r'^[a-z0-9_]+$')


# ------------------------------------------------------------------ tables and names
def footnote_tables(cursor):
    cursor.execute(
        "SELECT table_name FROM information_schema.tables "
        "WHERE table_schema = 'new_testament' AND table_name LIKE '%%footnotes' ORDER BY 1"
    )
    return [r[0] for r in cursor.fetchall()]


def has_vrs(cursor, table):
    """Only some footnote tables have the (mostly empty) vrs column."""
    cursor.execute(
        "SELECT 1 FROM information_schema.columns WHERE table_schema = 'new_testament' "
        "AND table_name = %s AND column_name = 'vrs'", (table,))
    return cursor.fetchone() is not None


def abbrev_of(table):
    """mat_footnotes → Mat; table_1co_footnotes → 1Co."""
    name = table[len('table_'):] if table.startswith('table_') else table
    code = name[:-len('_footnotes')]
    return code[0].upper() + code[1:] if not code[0].isdigit() else code[0] + code[1].upper() + code[2:]


def full_book(abbrev):
    return convert_book_name(abbrev) or abbrev


def translation_keys(abbrev, ref):
    """verse_translations keys a footnote by full book name, with and without the space."""
    full = full_book(abbrev)
    return {f'{full}-{ref}', f'{full.replace(" ", "")}-{ref}'}


# ------------------------------------------------------------------ plan
def plan_cleanup(books=None, translations=True, only_ids=None):
    """
    books: abbreviations (Mat, 1Co…) or None for every book; only_ids: footnote ids to limit
    the plan to (e.g. {'Mat-8'}). Returns a plan dict (see the module docstring).
    """
    with connection.cursor() as cur:
        tables = footnote_tables(cur)
        if books:
            wanted = {b.lower() for b in books}
            tables = [t for t in tables if abbrev_of(t).lower() in wanted]

        cur.execute('SELECT book, chapter, startVerse, rbt FROM new_testament.nt')
        locations = collections.defaultdict(set)
        for book, chapter, verse, rbt in cur.fetchall():
            for m in ANCHOR_RE.finditer(rbt or ''):
                locations[(m.group(4), m.group(3))].add((int(chapter), int(verse)))

        plan = {'books': [abbrev_of(t) for t in tables], 'tables': tables, 'updates': [], 'deletes': [],
                'conflicts': [], 'wording': [], 'review': [], 'placeholders': [], 'orphans': [],
                'unchanged': 0, 'rows': 0, 'translations': [], 'kinds': collections.Counter(), 'cache': set()}
        for table in tables:
            abbrev = abbrev_of(table)
            name = full_book(abbrev)
            vrs_col = 'vrs' if has_vrs(cur, table) else 'NULL'
            cur.execute(f'SELECT ctid::text, footnote_id, footnote_html, {vrs_col} FROM new_testament.{table} ORDER BY footnote_id')
            groups = collections.defaultdict(list)
            for ctid, fid, html, vrs in cur.fetchall():
                if only_ids and fid not in only_ids:
                    continue
                groups[fid].append({'ctid': ctid, 'html': html or '', 'vrs': vrs})
                plan['rows'] += 1
            for fid, rows in groups.items():
                ref = fid.split('-', 1)[1] if '-' in fid else fid
                where = sorted(locations.get((abbrev, ref), ()))
                place = [{'book': name, 'chapter': ch, 'verse': vs} for ch, vs in where]
                if not ID_RE.match(fid):
                    plan['placeholders'].append({'fid': fid, 'table': table, 'ref': ref, 'places': place})
                if not where:
                    plan['orphans'].append({'fid': fid, 'table': table, 'ref': ref, 'places': place})
                keep = rows[0]
                if len(rows) > 1:
                    cleaned = [normalize(r['html']).html for r in rows]
                    if len({h for h in cleaned if h.strip()}) > 1:
                        plan['conflicts'].append({'fid': fid, 'table': table, 'ref': ref, 'copies': len(rows), 'places': place})
                        continue
                    keep = next((r for r, h in zip(rows, cleaned) if h.strip()), rows[0])
                    for r in rows:
                        if r is not keep:
                            plan['deletes'].append({'table': table, 'fid': fid, 'ctid': r['ctid'], 'html': r['html'], 'vrs': r['vrs']})
                    for ch, vs in where:
                        plan['cache'].add((name, ch, vs))
                result = normalize(keep['html'])
                if result.review and any('maths' in r for r in result.review):
                    plan['review'].append({'fid': fid, 'table': table, 'ref': ref, 'places': place})
                if result.text_changed:
                    plan['wording'].append({'fid': fid, 'table': table, 'ref': ref, 'places': place})
                    continue
                if not result.changed:
                    plan['unchanged'] += 1
                    continue
                for k in result.changes:
                    plan['kinds'][k.split(' (')[0]] += 1
                plan['updates'].append({'table': table, 'fid': fid, 'ctid': keep['ctid'], 'old': keep['html'],
                                        'new': result.html, 'changes': result.changes, 'abbrev': abbrev,
                                        'ref': ref, 'places': place, 'copies': len(rows)})
                for ch, vs in where:
                    plan['cache'].add((name, ch, vs))

    if translations and plan['updates']:
        by_key = {}
        for u in plan['updates']:
            for key in translation_keys(u['abbrev'], u['ref']):
                by_key[key] = u
        for t in VerseTranslation.objects.filter(footnote_id__in=list(by_key)).exclude(footnote_text__isnull=True):
            u = by_key[t.footnote_id]
            change = _translation_change(t, u['old'], u['new'])
            if change:
                plan['translations'].append(change)
    return plan


def translation_count(plan):
    """How many translated footnotes the plan's footnotes have (cheap; for display)."""
    keys = set()
    for u in plan['updates']:
        keys |= translation_keys(u['abbrev'], u['ref'])
    return VerseTranslation.objects.filter(footnote_id__in=list(keys)).exclude(footnote_text__isnull=True).count() if keys else 0


def per_book(plan):
    """Counts per book, in plan order: [{abbrev, name, updates, deletes, issues}]."""
    rows = {b: {'abbrev': b, 'name': full_book(b), 'updates': 0, 'deletes': 0, 'issues': 0} for b in plan['books']}
    for u in plan['updates']:
        rows[u['abbrev']]['updates'] += 1
    for d in plan['deletes']:
        rows[abbrev_of(d['table'])]['deletes'] += 1
    for key in ('orphans', 'placeholders', 'conflicts', 'wording', 'review'):
        for it in plan[key]:
            rows[abbrev_of(it['table'])]['issues'] += 1
    return list(rows.values())


def _translation_change(t, old_english, new_english):
    """The cleaned text and re-stamped hash for one translated footnote, or None."""
    text = t.footnote_text or ''
    new_text = text if text.startswith('[Translation error') else normalize_uncached(text).html  # not cached: many, applied once
    new_hash = t.source_hash
    if t.source_hash == source_fingerprint(old_english):
        new_hash = source_fingerprint(new_english)
    if new_text == text and new_hash == t.source_hash:
        return None
    return {'pk': t.pk, 'footnote_id': t.footnote_id, 'lang': t.language_code, 'old_text': text,
            'new_text': new_text, 'old_hash': t.source_hash, 'new_hash': new_hash}


# ------------------------------------------------------------------ apply / backup / restore
def make_backup(plan):
    """Everything apply_plan() would overwrite: all rows of each touched id, and translations."""
    touched = {(u['table'], u['fid']) for u in plan['updates']} | {(d['table'], d['fid']) for d in plan['deletes']}
    backup = {'kind': 'rbt-footnote-backup', 'created': datetime.now().isoformat(timespec='seconds'),
              'books': plan['books'], 'footnotes': [], 'translations': []}
    with connection.cursor() as cur:
        for table, fid in sorted(touched):
            vrs_col = 'vrs' if has_vrs(cur, table) else 'NULL'
            cur.execute(f'SELECT footnote_id, footnote_html, {vrs_col} FROM new_testament.{table} WHERE footnote_id = %s', (fid,))
            for row in cur.fetchall():
                backup['footnotes'].append({'table': table, 'footnote_id': row[0], 'footnote_html': row[1], 'vrs': row[2]})
    backup['translations'] = [{'pk': t['pk'], 'footnote_text': t['old_text'], 'source_hash': t['old_hash']}
                              for t in plan['translations']]
    return backup


class PlanOutdated(Exception):
    """A footnote changed between planning and writing; nothing was written."""


def apply_plan(plan):
    """Write the plan in one transaction, then clear reader caches. Returns a summary dict."""
    with transaction.atomic():
        with connection.cursor() as cur:
            for d in plan['deletes']:
                cur.execute(f'DELETE FROM new_testament.{d["table"]} WHERE ctid = %s::tid AND footnote_id = %s', (d['ctid'], d['fid']))
            for u in plan['updates']:
                cur.execute(f'UPDATE new_testament.{u["table"]} SET footnote_html = %s WHERE ctid = %s::tid AND footnote_id = %s',
                            (u['new'], u['ctid'], u['fid']))
                if cur.rowcount != 1:
                    raise PlanOutdated(f'{u["fid"]} changed since the plan was made; nothing was written.')
        for t in plan['translations']:
            VerseTranslation.objects.filter(pk=t['pk']).update(footnote_text=t['new_text'], source_hash=t['new_hash'])
    cleared = clear_cache(plan['cache'])
    return {'updated': len(plan['updates']), 'deleted': len(plan['deletes']),
            'translations': len(plan['translations']), 'cache_keys': cleared}


def restore_backup(backup):
    """Put back the rows and translations saved by make_backup(). Returns a summary dict."""
    if not isinstance(backup, dict) or not isinstance(backup.get('footnotes'), list):
        raise ValueError('Not a footnote backup.')
    by_id = collections.defaultdict(list)
    for row in backup['footnotes']:
        table = row.get('table', '')
        if not TABLE_RE.match(table) or not table.endswith('_footnotes'):
            raise ValueError(f'Bad table name in backup: {table!r}')
        by_id[(table, row['footnote_id'])].append(row)
    cache = set()
    with connection.cursor() as cur:
        cur.execute('SELECT book, chapter, startVerse, rbt FROM new_testament.nt')
        anchors = collections.defaultdict(set)
        for book, chapter, verse, rbt in cur.fetchall():
            for m in ANCHOR_RE.finditer(rbt or ''):
                anchors[(m.group(4), m.group(3))].add((int(chapter), int(verse)))
    with transaction.atomic():
        with connection.cursor() as cur:
            for (table, fid), rows in by_id.items():
                cur.execute(f'DELETE FROM new_testament.{table} WHERE footnote_id = %s', (fid,))
                vrs = has_vrs(cur, table)
                for row in rows:
                    if vrs:
                        cur.execute(f'INSERT INTO new_testament.{table} (footnote_id, footnote_html, vrs) VALUES (%s, %s, %s)',
                                    (row['footnote_id'], row['footnote_html'], row.get('vrs')))
                    else:
                        cur.execute(f'INSERT INTO new_testament.{table} (footnote_id, footnote_html) VALUES (%s, %s)',
                                    (row['footnote_id'], row['footnote_html']))
                abbrev = abbrev_of(table)
                ref = fid.split('-', 1)[1] if '-' in fid else fid
                for ch, vs in anchors.get((abbrev, ref), ()):
                    cache.add((full_book(abbrev), ch, vs))
        for t in backup.get('translations', []):
            VerseTranslation.objects.filter(pk=t['pk']).update(footnote_text=t['footnote_text'], source_hash=t['source_hash'])
    return {'footnote_rows': len(backup['footnotes']), 'ids': len(by_id),
            'translations': len(backup.get('translations', [])), 'cache_keys': clear_cache(cache)}


def clear_cache(places):
    """Clear the reader cache of these (book name, chapter, verse) places; translations are kept."""
    from translate.views import _clear_reader_cache
    return sum(len(_clear_reader_cache(book, ch, vs)) for book, ch, vs in sorted(places))


# ------------------------------------------------------------------ editor saves
def carry_translations(abbrev, ref, old_html, new_html):
    """
    After an editor saves a footnote: if only its markup changed (the wording is the same),
    clean its translations the same way and keep them current (re-stamp source_hash).
    A change of wording leaves them alone, so they show as out of date. Returns how many
    translations were updated.
    """
    if not old_html or _letters(old_html) != _letters(new_html):
        return 0
    n = 0
    for t in VerseTranslation.objects.filter(footnote_id__in=list(translation_keys(abbrev, ref))).exclude(footnote_text__isnull=True):
        change = _translation_change(t, old_html, new_html)
        if change:
            VerseTranslation.objects.filter(pk=t.pk).update(footnote_text=change['new_text'], source_hash=change['new_hash'])
            n += 1
    return n
