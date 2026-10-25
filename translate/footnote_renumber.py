"""
Renumber a book's New Testament footnotes 1, 2, 3… in reading order (the Numbering part of the
clean-up page, /translate/footnotes/cleanup/). A note added between two others gets a letter
(8a, 7c); this gives every note in the book a whole number again, in the order readers meet them.

A footnote's number is in four places, all rewritten in one transaction:
- its row: new_testament.<book>_footnotes.footnote_id ('Mat-8');
- each link to it in verse HTML (new_testament.nt.rbt):
  <a class="sdfootnoteanc" href="?footnote=2-4-8&amp;book=Mat"><sup>8</sup></a>;
- the same links in translated verses (verse_translations.verse_text), whose source_hash moves
  to the renumbered English, so they stay current and aren't translated again;
- translated footnotes (verse_translations.footnote_id 'Matthew-8').

Notes no verse links to are numbered after the rest. A link to a note that doesn't exist keeps
its place in the order (and stays broken). A marker that named another verse in its link gets
its own verse.

Replaces scripts/resequence_new_v2.py, which wrote a renumbered copy into another schema.
"""
import collections
import hashlib
import re
from datetime import datetime

from django.db import connection, transaction
from django.db.models import Q

from search.models import VerseTranslation
from search.translation_utils import source_fingerprint
from translate.footnote_maintenance import PlanOutdated, TABLE_RE, abbrev_of, clear_cache, footnote_tables, full_book

BACKUP_KIND = 'rbt-footnote-renumber-backup'
HREF_RE = re.compile(r'\?footnote=(\d+)-(\d+)-([0-9A-Za-z]+)(&amp;|&)book=([0-9A-Za-z]+)')
# A whole link, or a bare ?footnote= outside one; one pass, so a renumbered link is never renumbered again.
LINK_RE = re.compile(r'(<a\b[^>]*>)(.*?)(</a>)|' + HREF_RE.pattern, re.S | re.I)
MARKER_BODY_RE = re.compile(r'\s*<sup\b[^>]*>[^<]*</sup>\s*', re.I)
SUP_RE = re.compile(r'(<sup\b[^>]*>)[^<]*(</sup>)', re.I)
REF_RE = re.compile(r'[0-9A-Za-z]+')
TMP = '~r~'  # ids are moved through this prefix so that 8→9 and 9→10 never collide


def _ref_key(ref):
    """Natural order: 2 < 10 < 10a < xx."""
    m = re.match(r'(\d*)(.*)', ref)
    return (int(m.group(1)) if m.group(1) else float('inf'), m.group(2))


def _sha(text):
    return hashlib.sha256((text or '').encode('utf-8')).hexdigest()


def numbering(order, stored_refs):
    """
    order: refs in the order the book's links meet them; stored_refs: refs that have a row.
    Returns {old ref: new ref} for every ref: linked ones 1, 2, 3…, then the unlinked notes.
    """
    unlinked = sorted(set(stored_refs) - set(order), key=_ref_key)
    return {old: str(n) for n, old in enumerate(list(order) + unlinked, 1)}


def renumber_links(html, abbrev, mapping, chapter, verse):
    """
    html with its links to this book's footnotes renumbered (mapping: old ref → new ref).
    A marker (<a class="sdfootnoteanc">, just a <sup>) also shows the new number and names its
    own verse; other links ("See footnote.") keep their text and the verse they name.
    Returns (html, moved): moved lists (verse the marker named, ref) for markers that named another.
    """
    moved = []

    def href(m, marker):
        ch, vs, ref, amp, book = m.groups()
        if book != abbrev or ref not in mapping:
            return m.group(0)
        if marker and (int(ch), int(vs)) != (chapter, verse):
            moved.append((f'{ch}:{vs}', ref))
            ch, vs = chapter, verse
        return f'?footnote={ch}-{vs}-{mapping[ref]}{amp}book={book}'

    def link(m):
        if m.group(1) is None:
            return href(HREF_RE.match(m.group(0)), marker=False)
        open_tag, body, close = m.group(1, 2, 3)
        h = HREF_RE.search(open_tag)
        if not h or h.group(5) != abbrev or h.group(3) not in mapping:
            return m.group(0)
        marker = 'sdfootnoteanc' in open_tag and MARKER_BODY_RE.fullmatch(body) is not None
        open_tag = open_tag[:h.start()] + href(h, marker) + open_tag[h.end():]
        if marker:
            body = SUP_RE.sub(lambda s: f'{s.group(1)}{mapping[h.group(3)]}{s.group(2)}', body, count=1)
        return open_tag + body + close

    return LINK_RE.sub(link, html), moved


def _table(cur, abbrev):
    for table in footnote_tables(cur):
        if abbrev_of(table) == abbrev:
            return table
    raise ValueError(f'No footnote table for {abbrev!r}.')


def plan_renumber(abbrev, translations=True, lock=False):
    """
    What renumbering one book (abbreviation: 'Mat', '1Co') would change; writes nothing.
    lock (inside a transaction) holds the rows read until it ends. Returns a dict:
    changes (each number that changes, with where it's first linked), renames (ids to move),
    verses (verse HTML before and after), moved, missing, unlinked, odd (ids not like 'Mat-8'),
    footnote_translations, verse_translations, needed, and token (changes when the inputs do).
    """
    name = full_book(abbrev)
    with connection.cursor() as cur:
        table = _table(cur, abbrev)
        cur.execute('SELECT verseid, book, chapter, startverse, rbt FROM new_testament.nt WHERE rbt LIKE %s ORDER BY nt_id'
                    + (' FOR UPDATE' if lock else ''), (f'%book={abbrev}%',))
        verses = cur.fetchall()
        cur.execute(f'SELECT footnote_id FROM new_testament.{table}' + (' FOR UPDATE' if lock else ''))
        stored = collections.Counter(r[0] for r in cur.fetchall())

    prefix = f'{abbrev}-'
    refs = {fid[len(prefix):] for fid in stored if fid.startswith(prefix) and REF_RE.fullmatch(fid[len(prefix):])}
    odd = sorted(fid for fid in stored if not (fid.startswith(prefix) and fid[len(prefix):] in refs))
    order, first = [], {}
    for _verseid, book, ch, vs, html in verses:
        for m in HREF_RE.finditer(html or ''):
            if m.group(5) == abbrev and m.group(3) not in first:
                first[m.group(3)] = {'book': full_book(book), 'chapter': int(ch), 'verse': int(vs)}
                order.append(m.group(3))
    mapping = numbering(order, refs)

    plan = {'book': abbrev, 'name': name, 'table': table, 'total': len(mapping), 'changes': [], 'renames': [],
            'verses': [], 'moved': [], 'missing': [], 'unlinked': [], 'odd': odd,
            'footnote_translations': [], 'verse_translations': [], 'translations_counted': translations}
    for old, new in mapping.items():
        item = {'old': old, 'new': new, 'place': first.get(old)}
        if old not in refs:
            plan['missing'].append(item)
        if old not in first:
            plan['unlinked'].append(item)
        if old != new:
            plan['changes'].append(item)
            if old in refs:
                plan['renames'].append((old, new, stored[prefix + old]))
    for verseid, book, ch, vs, html in verses:
        new_html, moved = renumber_links(html or '', abbrev, mapping, int(ch), int(vs))
        place = {'book': full_book(book), 'chapter': int(ch), 'verse': int(vs)}
        if new_html != (html or ''):
            plan['verses'].append({'verseid': verseid, **place, 'old': html, 'new': new_html})
        plan['moved'] += [{'ref': ref, 'new': mapping[ref], 'named': named, 'place': place} for named, ref in moved]

    digest = hashlib.sha256()
    for verseid, _book, _ch, _vs, html in verses:
        digest.update(f'{verseid}\0{html}\0'.encode('utf-8'))
    for fid in sorted(stored.elements()):
        digest.update(f'{fid}\0'.encode('utf-8'))
    plan['token'] = digest.hexdigest()
    plan['needed'] = bool(plan['renames'] or plan['verses'])
    if translations and plan['needed']:
        _plan_translations(plan, mapping)
    return plan


def _plan_translations(plan, mapping):
    abbrev, name = plan['book'], plan['name']
    names = sorted({name, name.replace(' ', '')})
    keys = {}
    for old, new, _rows in plan['renames']:
        for n in names + [abbrev]:
            keys[f'{n}-{old}'] = f'{n}-{new}'
    if keys:
        for pk, fid in VerseTranslation.objects.filter(book__in=names, footnote_id__in=list(keys)).values_list('pk', 'footnote_id'):
            plan['footnote_translations'].append({'pk': pk, 'old': fid, 'new': keys[fid]})

    english = {(v['chapter'], v['verse']): (v['old'], v['new']) for v in plan['verses']}
    rows = (VerseTranslation.objects.filter(book__in=names, footnote_id__isnull=True)
            .filter(Q(chapter__in={ch for ch, _ in english}) | Q(verse_text__contains=f'book={abbrev}'))
            .only('pk', 'chapter', 'verse', 'verse_text', 'source_hash'))
    for t in rows:
        text = t.verse_text or ''
        new_text, _ = renumber_links(text, abbrev, mapping, t.chapter, t.verse)
        new_hash = t.source_hash
        if (t.chapter, t.verse) in english:
            old_en, new_en = english[(t.chapter, t.verse)]
            if t.source_hash == source_fingerprint(old_en):
                new_hash = source_fingerprint(new_en)
        if new_text != text or new_hash != t.source_hash:
            plan['verse_translations'].append({'pk': t.pk, 'old_text': t.verse_text, 'new_text': new_text,
                                               'old_hash': t.source_hash, 'new_hash': new_hash})


def _rename(cur, table, pairs, expected=None):
    """Rename footnote ids [(old, new)] in one table, in two steps so no two ids ever collide."""
    if not pairs:
        return 0
    olds, news = [o for o, _ in pairs], [n for _, n in pairs]
    cur.execute(f'UPDATE new_testament.{table} SET footnote_id = %s || footnote_id WHERE footnote_id = ANY(%s)', (TMP, olds))
    moved = cur.rowcount
    if expected is not None and moved != expected:
        raise PlanOutdated('The footnotes changed while renumbering; nothing was written.')
    cur.execute(f'UPDATE new_testament.{table} AS t SET footnote_id = m.new '
                f'FROM unnest(%s::text[], %s::text[]) AS m(old, new) WHERE t.footnote_id = %s || m.old', (olds, news, TMP))
    if cur.rowcount != moved:
        raise PlanOutdated('The footnotes changed while renumbering; nothing was written.')
    return moved


def make_backup(plan):
    """What apply_renumber() changes, to put it back with restore_renumber()."""
    b = plan['book']
    return {
        'kind': BACKUP_KIND, 'created': datetime.now().isoformat(timespec='seconds'),
        'book': b, 'name': plan['name'], 'table': plan['table'],
        'renames': [[f'{b}-{old}', f'{b}-{new}'] for old, new, _rows in plan['renames']],
        'verses': [{'verseid': v['verseid'], 'book': v['book'], 'chapter': v['chapter'], 'verse': v['verse'],
                    'rbt': v['old'], 'now': _sha(v['new'])} for v in plan['verses']],
        'footnote_translations': [{'pk': t['pk'], 'footnote_id': t['old'], 'now': t['new']} for t in plan['footnote_translations']],
        'verse_translations': [{'pk': t['pk'], 'verse_text': t['old_text'], 'source_hash': t['old_hash']}
                               for t in plan['verse_translations']],
    }


def apply_renumber(abbrev, token):
    """
    Renumber the book as planned, if nothing changed since the plan with this token was made
    (PlanOutdated otherwise). Returns (summary, backup); backup is None if nothing needed doing.
    """
    with transaction.atomic():
        plan = plan_renumber(abbrev, lock=True)
        if plan['token'] != token:
            raise PlanOutdated(f'{plan["name"]} changed since this page was loaded; reload to see the new numbering. Nothing was written.')
        if not plan['needed']:
            return {'renumbered': 0, 'verses': 0, 'translations': 0, 'cache_keys': 0}, None
        backup = make_backup(plan)
        with connection.cursor() as cur:
            for v in plan['verses']:
                cur.execute('UPDATE new_testament.nt SET rbt = %s WHERE verseid = %s AND rbt = %s', (v['new'], v['verseid'], v['old']))
                if cur.rowcount != 1:
                    raise PlanOutdated(f'{v["book"]} {v["chapter"]}:{v["verse"]} changed while renumbering; nothing was written.')
            _rename(cur, plan['table'], [(f'{abbrev}-{o}', f'{abbrev}-{n}') for o, n, _rows in plan['renames']],
                    expected=sum(rows for _o, _n, rows in plan['renames']))
        for t in plan['footnote_translations']:
            VerseTranslation.objects.filter(pk=t['pk'], footnote_id=t['old']).update(footnote_id=t['new'])
        for t in plan['verse_translations']:
            VerseTranslation.objects.filter(pk=t['pk']).update(verse_text=t['new_text'], source_hash=t['new_hash'])
    cleared = clear_cache({(v['book'], v['chapter'], v['verse']) for v in plan['verses']})
    return {'renumbered': len(plan['changes']), 'verses': len(plan['verses']),
            'translations': len(plan['footnote_translations']) + len(plan['verse_translations']), 'cache_keys': cleared}, backup


def restore_renumber(backup):
    """
    Put the old numbers back from make_backup()'s backup. Refuses (PlanOutdated) if a verse it
    touched was edited since, or an old number was given to a new note: undoing would lose that.
    """
    table = backup.get('table', '')
    if backup.get('kind') != BACKUP_KIND or not TABLE_RE.match(table) or not table.endswith('_footnotes'):
        raise ValueError('Not a renumbering backup.')
    pairs = [(new, old) for old, new in backup['renames']]
    with transaction.atomic():
        with connection.cursor() as cur:
            cur.execute('SELECT verseid, rbt FROM new_testament.nt WHERE verseid = ANY(%s) FOR UPDATE',
                        ([v['verseid'] for v in backup['verses']],))
            now = dict(cur.fetchall())
            edited = [v for v in backup['verses'] if _sha(now.get(v['verseid'])) != v['now']]
            if edited:
                v = edited[0]
                raise PlanOutdated(f'{len(edited)} verse(s), e.g. {v["book"]} {v["chapter"]}:{v["verse"]}, changed after the '
                                   'renumbering, so it can’t be undone automatically. Nothing was written.')
            cur.execute(f'SELECT footnote_id FROM new_testament.{table} WHERE footnote_id = ANY(%s)', ([o for _, o in pairs],))
            taken = {r[0] for r in cur.fetchall()} - {n for n, _ in pairs}
            if taken:
                raise PlanOutdated(f'{", ".join(sorted(taken))} was added after the renumbering, so the old numbers '
                                   'can’t be put back. Nothing was written.')
            moved = _rename(cur, table, pairs)
            for v in backup['verses']:
                cur.execute('UPDATE new_testament.nt SET rbt = %s WHERE verseid = %s', (v['rbt'], v['verseid']))
        for t in backup.get('footnote_translations', []):
            VerseTranslation.objects.filter(pk=t['pk'], footnote_id=t['now']).update(footnote_id=t['footnote_id'])
        for t in backup.get('verse_translations', []):
            VerseTranslation.objects.filter(pk=t['pk']).update(verse_text=t['verse_text'], source_hash=t['source_hash'])
    cleared = clear_cache({(v['book'], v['chapter'], v['verse']) for v in backup['verses']})
    return {'footnote_rows': moved, 'verses': len(backup['verses']),
            'translations': len(backup.get('footnote_translations', [])) + len(backup.get('verse_translations', [])),
            'cache_keys': cleared}
