"""
Build search/data/brenton_versification.json, which tells the verse page which Brenton
Septuagint verse (table englxxup) belongs beside an Old Testament verse of the RBT reader.

The numberings disagree. The reader follows the Hebrew in some books (Psalms, with titles counted
as verses; Hosea) and the English in others (Exodus 22, Joel, Malachi); Brenton follows the
Septuagint (Psalm 82 is its Psalm 81, Jeremiah 25-51 are rearranged, Nehemiah is 2 Esdras 11-23).
The old lookup used the reader's chapter:verse for all of them, so Psalm 82:6 showed Psalm 83.

    reader verse  -> Masoretic verse    match the verse's consonants (old_testament.hebrewdata)
                                        against the CATSS Masoretic text (catss.hebrew_token)
    Masoretic     -> Septuagint verse   the [chapter.verse] / [verse] marks CATSS puts on the aligned
                                        Greek (catss.greek_token); an unmarked verse continues the
                                        numbering of the verse before it in the same chapter
    Septuagint    -> Brenton row        englxxup uses that numbering, except where Brenton's own
                                        edition differs (BRENTON_SHIFTS)

The file lists only the verses whose Brenton reference differs from the reader's, mapping
"chapter:verse" to "BOOK chapter:verse", or to null where the Greek has no such verse (the column
then stays empty rather than showing the wrong verse).

    python manage.py build_brenton_versification [--report] [--audit FILE.tsv]
"""
import csv
import difflib
import json
import os
import re
from collections import Counter, defaultdict

from django.conf import settings
from django.core.management.base import BaseCommand
from django.db import connection

# Reader book name, hebrewdata code, CATSS code (the Greek text Brenton translated), englxxup code.
BOOKS = [
    ('Genesis', 'Gen', 'GEN', 'GEN'), ('Exodus', 'Exo', 'EXO', 'EXO'), ('Leviticus', 'Lev', 'LEV', 'LEV'),
    ('Numbers', 'Num', 'NUM', 'NUM'), ('Deuteronomy', 'Deu', 'DEU', 'DEU'), ('Joshua', 'Jos', 'JSB', 'JOS'),
    ('Judges', 'Jdg', 'JDB', 'JDG'), ('Ruth', 'Rut', 'RUT', 'RUT'), ('1 Samuel', '1Sa', '1SA', '1SA'),
    ('2 Samuel', '2Sa', '2SA', '2SA'), ('1 Kings', '1Ki', '1KI', '1KI'), ('2 Kings', '2Ki', '2KI', '2KI'),
    ('1 Chronicles', '1Ch', '1CH', '1CH'), ('2 Chronicles', '2Ch', '2CH', '2CH'), ('Ezra', 'Ezr', 'EZR', 'EZR'),
    ('Nehemiah', 'Neh', 'NEH', 'EZR'), ('Esther', 'Est', 'EST', 'ESG'), ('Job', 'Job', 'JOB', 'JOB'),
    ('Psalms', 'Psa', 'PSA', 'PSA'), ('Proverbs', 'Pro', 'PRO', 'PRO'), ('Ecclesiastes', 'Ecc', 'ECC', 'ECC'),
    ('Song of Solomon', 'Sng', 'SNG', 'SNG'), ('Isaiah', 'Isa', 'ISA', 'ISA'), ('Jeremiah', 'Jer', 'JER', 'JER'),
    ('Lamentations', 'Lam', 'LAM', 'LAM'), ('Ezekiel', 'Eze', 'EZK', 'EZK'), ('Daniel', 'Dan', 'DTH', 'DAG'),
    ('Hosea', 'Hos', 'HOS', 'HOS'), ('Joel', 'Joe', 'JOL', 'JOL'), ('Amos', 'Amo', 'AMO', 'AMO'),
    ('Obadiah', 'Oba', 'OBA', 'OBA'), ('Jonah', 'Jon', 'JON', 'JON'), ('Micah', 'Mic', 'MIC', 'MIC'),
    ('Nahum', 'Nah', 'NAH', 'NAM'), ('Habakkuk', 'Hab', 'HAB', 'HAB'), ('Zephaniah', 'Zep', 'ZEP', 'ZEP'),
    ('Haggai', 'Hag', 'HAG', 'HAG'), ('Zechariah', 'Zec', 'ZEC', 'ZEC'), ('Malachi', 'Mal', 'MAL', 'MAL'),
]
CHAPTER_OFFSET = {'Nehemiah': 10}  # Brenton's Nehemiah is 2 Esdras 11-23
_PRO_30_LETTERS = 'fghiklmnopqrst'  # Brenton 24:22a-e are Greek-only lines; 22f-22t are Hebrew 30:1-14


def brenton_shift(code, chapter, verse):
    """Where Brenton's edition numbers a Septuagint verse differently from CATSS (Rahlfs)."""
    if code == 'MAL' and chapter == 3 and 19 <= verse <= 24:
        return 4, verse - 18
    if code == 'PRO' and chapter == 30:
        return (24, f'22{_PRO_30_LETTERS[verse - 1]}') if verse <= 14 else (24, verse + 20)
    if code == 'PRO' and chapter == 31 and verse <= 9:
        return 24, verse + 53
    return chapter, verse


STOPWORDS = set('''the and of to a in that he i his him for is was with be they them shall not it all their as by
you thy thee thou unto upon from on this are have which my me said will who but there were or an at so out up your one into
when we had her she what our us its no also then even before because these those over'''.split())


def words(text):
    return {w.rstrip('s') for w in re.findall(r'[a-z]{3,}', (text or '').lower()) if w not in STOPWORDS}


def similarity(a, b):
    return len(a & b) / min(len(a), len(b)) if a and b else 0.0


def brenton_has(brenton, code, lxx, offset=0):
    chapter, verse = brenton_shift(code, *lxx)
    return (code, str(chapter + offset), str(verse)) in brenton


OUT_PATH = os.path.join(settings.BASE_DIR, 'search', 'data', 'brenton_versification.json')
LETTERS = re.compile(r'[א-ת]')
FINALS = str.maketrans('ךםןףץ', 'כמנפצ')
GROUP_ID = re.compile(r'^[0-9A-Z]+\.(\d+)\.(\d+)\.\d+$')
LXX_MARK = re.compile(r'^\[(?:(\d+)\.)?(\d+)\]$')  # [81.6] or [6]; [[..]] doublets and 10:26a-style marks are skipped
GREEK_LETTER = re.compile(r'[Ͱ-Ͽἀ-῿]')


def consonants(text):
    return ''.join(LETTERS.findall(text or '')).translate(FINALS)


def masoretic_token(surface):
    """CATSS Hebrew-column tokens that are the Masoretic text itself (not retroversions or notes)."""
    if not surface or surface[0] in '=^<{([' or surface.startswith('**') or surface.startswith('־־'):
        return False
    return bool(LETTERS.search(surface))


class Command(BaseCommand):
    help = 'Build search/data/brenton_versification.json (reader verse -> Brenton Septuagint verse).'

    def add_arguments(self, parser):
        parser.add_argument('--report', action='store_true', help='Print per-book statistics.')
        parser.add_argument('--audit', help='Also write every verse (reader, Masoretic, Brenton) to this TSV.')

    def handle(self, *args, report=False, audit=None, **options):
        brenton = self._brenton_texts()
        glosses = self._glosses()
        mapping, totals, audit_rows = {}, Counter(), []
        for name, site_code, catss_code, brenton_code in BOOKS:
            site_verses = self._site_verses(site_code)
            mt_order, mt_text, mt_groups, group_mark, with_greek = self._catss_verses(catss_code)
            site_to_mt = self._align(site_verses, mt_order, mt_text)
            offset = CHAPTER_OFFSET.get(name, 0)
            mt_to_lxx = self._septuagint_numbers(
                mt_order, mt_groups, group_mark,
                lambda cv, b=brenton_code, o=offset: brenton_has(brenton, b, cv, o))
            records = []
            for (sc, sv), _text in site_verses:
                mt = site_to_mt.get((sc, sv))
                source = 'unmatched'
                if mt is None:
                    lxx = (sc, sv)  # keep the reader's own numbers
                elif mt not in with_greek:
                    lxx, source = None, 'no_greek'
                else:
                    lxx, source = mt_to_lxx[mt]
                candidate = None
                if lxx is not None:
                    chapter, verse = brenton_shift(brenton_code, *lxx)
                    key = (brenton_code, str(chapter + offset), str(verse))
                    candidate = key if key in brenton else None
                baseline = (brenton_code, str(sc + offset), str(sv))
                target, verdict = self._accept(name, source, candidate, baseline, brenton,
                                               words(glosses.get(f'{site_code}.{sc}.{sv}', '')))
                records.append([sc, sv, mt, source, candidate, baseline, target, verdict])
            self._settle_runs(name, records)

            book_map, stats = {}, Counter()
            for sc, sv, mt, source, candidate, baseline, target, verdict in records:
                stats[verdict] += 1
                if target is None:
                    book_map[f'{sc}:{sv}'] = None
                elif target != (brenton_code, str(sc), str(sv)):
                    book_map[f'{sc}:{sv}'] = f'{target[0]} {target[1]}:{target[2]}'
                if audit:
                    audit_rows.append((name, f'{sc}:{sv}', f'{mt[0]}:{mt[1]}' if mt else '', source, verdict,
                                       ' '.join(candidate) if candidate else '',
                                       ' '.join(target) if target else ''))
            if book_map:
                mapping[name] = book_map
            totals.update(stats)
            if report:
                self.stdout.write(f'{name:16s} verses {len(site_verses):5d}  ' +
                                  '  '.join(f'{k} {v}' for k, v in sorted(stats.items())))

        os.makedirs(os.path.dirname(OUT_PATH), exist_ok=True)
        with open(OUT_PATH, 'w', encoding='utf-8') as fh:
            json.dump(mapping, fh, ensure_ascii=False, sort_keys=True, separators=(',', ':'))
            fh.write('\n')
        if audit:
            with open(audit, 'w', encoding='utf-8', newline='') as fh:
                csv.writer(fh, delimiter='\t').writerows(audit_rows)
        self.stdout.write(self.style.SUCCESS(
            f'Wrote {OUT_PATH}: ' + ', '.join(f'{k} {v}' for k, v in sorted(totals.items()))))

    @staticmethod
    def _accept(name, source, candidate, baseline, brenton, gloss_words):
        """Choose between the CATSS-derived Brenton verse and the reader's own numbers.

        A CATSS mark that moves a verse to another chapter (Psalms, Jeremiah, 3 Kingdoms) is
        systematic and is trusted. Other remappings rest on weaker ground: CATSS divides a few
        chapters differently from the Masoretic text (Joshua 22 joins 20-21; Lamentations 1 counts
        the Greek prologue as a verse), and a mark within a chapter can cover only part of a verse.
        Those are kept only if the Brenton verse fits RBT's word glosses for the reader verse about
        as well as the verse with the reader's own number. The glosses share the reader's numbering,
        which LITV and Smith (English numbering) do not."""
        if candidate == baseline:
            return baseline, 'same'
        old = similarity(words(brenton.get(baseline)), gloss_words) if baseline in brenton else None
        if candidate is None and source != 'no_greek':
            # A computed reference Brenton does not have points at a numbering quirk, not at a
            # missing verse: fall back to the reader's own number.
            return (baseline, 'kept_old') if old is not None else (None, 'empty')
        if candidate is None:
            # The Greek lacks the verse: leave the column empty unless the reader-numbered verse
            # plainly is this verse (Brenton sometimes supplies what the Vatican text lacks).
            if old is not None and old >= 0.35:
                return baseline, 'kept_old_greek_lacks'
            return None, 'empty'
        if name == 'Psalms' or source == 'chapter_mark' or old is None:
            return candidate, 'remapped'
        new = similarity(words(brenton.get(candidate)), gloss_words)
        if new >= old - 0.05:
            return candidate, 'remapped'
        return baseline, 'kept_old'

    @staticmethod
    def _settle_runs(name, records):
        """Word overlap with the glosses is noisy verse by verse but reliable over a run: a chapter
        renumbered by one fixed shift (Exodus 22 in English vs Hebrew numbering, Daniel 4 +3) is
        right as a whole, and a CATSS division quirk (Joshua 22, Lamentations 1) is wrong as a
        whole. So weakly-founded remappings sharing a chapter and a shift are kept or dropped
        together, by majority, when there are at least three of them."""
        if name == 'Psalms':
            return
        runs = defaultdict(list)
        for record in records:
            sc, sv, mt, source, candidate, baseline, target, verdict = record
            if source in ('mark', 'own', 'carried') and candidate and candidate != baseline \
                    and candidate[2].isdigit() and verdict in ('remapped', 'kept_old'):
                shift = (int(candidate[1]) - int(baseline[1]), int(candidate[2]) - int(baseline[2]))
                runs[(sc, shift)].append(record)
        for run in runs.values():
            if len(run) < 3:
                continue
            accepted = sum(1 for r in run if r[7] == 'remapped')
            keep_new = accepted >= len(run) - accepted
            for r in run:
                r[6], r[7] = (r[4], 'remapped') if keep_new else (r[5], 'kept_old')

    def _brenton_texts(self):
        texts = {}
        with connection.cursor() as cur:
            cur.execute('SELECT book, chapter, "startVerse", "endVerse", "verseText" FROM englxxup')
            for book, chapter, start, end, text in cur.fetchall():
                start, end = str(start), str(end)
                verses = range(int(start), int(end) + 1) if start.isdigit() and end.isdigit() else [start]
                for verse in verses:
                    texts[(book, str(chapter), str(verse))] = text or ''
        return texts

    def _glosses(self):
        with connection.cursor() as cur:
            cur.execute("SELECT split_part(ref, '-', 1), string_agg(coalesce(eng, ''), ' ') "
                        "FROM old_testament.hebrewdata GROUP BY 1")
            return dict(cur.fetchall())

    # -- sources --------------------------------------------------------------------------------

    def _site_verses(self, code):
        """[((chapter, verse), consonants)] in reading order for one reader book."""
        with connection.cursor() as cur:
            cur.execute(
                "SELECT split_part(ref, '-', 1), string_agg(combined_heb, ' ' ORDER BY id) "
                "FROM old_testament.hebrewdata WHERE ref LIKE %s GROUP BY 1", (f'{code}.%',))
            rows = []
            for ref, text in cur.fetchall():
                parts = ref.split('.')
                if len(parts) == 3 and parts[1].isdigit() and parts[2].isdigit():
                    rows.append(((int(parts[1]), int(parts[2])), consonants(text)))
        return sorted(rows)

    def _catss_verses(self, code):
        """A CATSS book's Masoretic verses: order, consonants, groups, each group's Septuagint mark,
        and the verses that have any Greek at all."""
        text, groups = defaultdict(list), defaultdict(list)
        group_marks, with_greek = defaultdict(Counter), set()
        with connection.cursor() as cur:
            cur.execute("SELECT group_id, surface FROM catss.hebrew_token WHERE group_id LIKE %s "
                        "ORDER BY group_id, token_order", (f'{code}.%',))
            for group_id, surface in cur.fetchall():
                m = GROUP_ID.match(group_id)
                if not m:
                    continue
                key = (int(m.group(1)), int(m.group(2)))
                if key not in groups:
                    groups[key] = []
                if masoretic_token(surface):
                    text[key].append(consonants(surface))
                    if not groups[key] or groups[key][-1] != group_id:
                        groups[key].append(group_id)  # only groups with Hebrew text vote on numbering
            cur.execute("SELECT group_id, surface FROM catss.greek_token WHERE group_id LIKE %s", (f'{code}.%',))
            for group_id, surface in cur.fetchall():
                m = GROUP_ID.match(group_id)
                if not m:
                    continue
                key = (int(m.group(1)), int(m.group(2)))
                surface = (surface or '').strip()
                mark = LXX_MARK.match(surface)
                if mark:
                    group_marks[group_id][(int(mark.group(1)) if mark.group(1) else None, int(mark.group(2)))] += 1
                elif GREEK_LETTER.search(surface) and not surface.startswith('{'):
                    with_greek.add(key)
        order = sorted(groups)
        joined = {k: ''.join(text[k]) for k in order}
        marks = {g: c.most_common(1)[0][0] for g, c in group_marks.items()}
        return order, joined, groups, marks, with_greek

    def _septuagint_numbers(self, mt_order, mt_groups, group_mark, exists):
        """Masoretic (chapter, verse) -> Septuagint (chapter, verse).

        A verse takes the CATSS mark its aligned groups carry (when marked groups are at least as
        many as unmarked ones). An unmarked verse keeps its own number, unless another verse's
        mark holds that number or Brenton has no such verse: then it continues the numbering of
        the verse before it (CATSS marks the start of a renumbered run, e.g. Psalm 115:1 =
        Septuagint 113:9, and leaves 115:9-17 unmarked). Carrying every offset forward would be
        wrong after short reorderings such as the commandments in Exodus 20:13-15."""
        explicit = {}
        for key in mt_order:
            votes, unmarked = Counter(), 0
            for group_id in mt_groups[key]:
                mark = group_mark.get(group_id)
                if mark is None:
                    unmarked += 1
                else:
                    votes[(mark[0] if mark[0] is not None else key[0], mark[1])] += 1
            if votes:
                best, count = votes.most_common(1)[0]
                if count >= unmarked:
                    explicit[key] = best
        claimed = {}
        for key, lxx in explicit.items():
            claimed.setdefault(lxx, key)
        result, prev = {}, None
        for key in mt_order:
            lxx = explicit.get(key)
            source = 'mark' if lxx is None or lxx[0] == key[0] else 'chapter_mark'
            if lxx is None:
                lxx, source = key, 'own'
                if claimed.get(lxx, key) != key or not exists(lxx):
                    if prev and prev[0][0] == key[0]:
                        follow = (prev[1][0], prev[1][1] + 1)
                        if claimed.get(follow, key) == key and exists(follow):
                            lxx, source = follow, 'carried'
            result[key] = (lxx, source)
            prev = (key, lxx)
        return result

    def _align(self, site_verses, mt_order, mt_text):
        """Reader (chapter, verse) -> Masoretic (chapter, verse), by consonant text."""
        by_text = defaultdict(list)
        for key in mt_order:
            by_text[mt_text[key]].append(key)
        index = {key: i for i, key in enumerate(mt_order)}
        result, last = {}, -1
        for site_key, text in site_verses:
            exact = by_text.get(text, []) if text else []
            if exact:
                # Identical verses (refrains) are taken in reading order.
                after = [k for k in exact if index[k] > last]
                pick = (after or exact)[0]
                result[site_key] = pick
                last = index[pick]
                continue
            # Ketiv/qere spellings or a verse divided differently: the closest Masoretic verse near
            # where the previous one matched.
            lo, hi = max(0, last - 3), min(len(mt_order), last + 6)
            best, best_ratio = None, 0.0
            for key in mt_order[lo:hi]:
                ratio = difflib.SequenceMatcher(None, text, mt_text[key], autojunk=False).ratio()
                if ratio > best_ratio:
                    best, best_ratio = key, ratio
            if best is not None and best_ratio >= 0.6:
                result[site_key] = best
                last = index[best]
        return result
