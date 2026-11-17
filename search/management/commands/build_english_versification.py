"""
Build search/data/english_versification.json, which tells the verse page which English-numbered
verse of LITV and the Julia Smith translation belongs beside an Old Testament verse of the reader.

The reader numbers the Old Testament as the Hebrew text does (Psalm titles are verses; Hosea 12:1
is English 11:12), except Exodus 21-22, which scripts/fix_exo22_versification.py converted to the
English numbers. LITV and Smith use the English numbers throughout, so the old lookup showed the
wrong verse wherever the two differ (Psalm 8:5 showed the English 8:5, which is Hebrew 8:6).

The differences are the standard Hebrew/English versification table below. A rule is applied only
where the reader's chapter really is numbered the Hebrew way, i.e. where its verse count differs
from LITV's (Isaiah 8-9, Joel, Malachi and Exodus 22 already follow the English numbers in the
reader); the Psalm titles are always applied. The file lists only the verses whose English
reference differs from the reader's, mapping "chapter:verse" to "chapter:verse".

    python manage.py build_english_versification [--report]
"""
import json
import os
from collections import Counter

from django.conf import settings
from django.core.management.base import BaseCommand
from django.db import connection

OUT_PATH = os.path.join(settings.BASE_DIR, 'search', 'data', 'english_versification.json')

# (Hebrew chapter, first verse, last verse, English chapter, verse offset): Hebrew c:v becomes
# English chapter:(v + offset) for v in first..last.
HEBREW_TO_ENGLISH = {
    'Genesis': [(32, 1, 1, 31, 54), (32, 2, 33, 32, -1)],
    'Exodus': [(7, 26, 29, 8, -25), (8, 1, 28, 8, 4)],
    'Leviticus': [(5, 20, 26, 6, -19), (6, 1, 23, 6, 7)],
    'Numbers': [(17, 1, 15, 16, 35), (17, 16, 28, 17, -15), (25, 19, 19, 26, -18),
                (30, 1, 1, 29, 39), (30, 2, 17, 30, -1)],
    'Deuteronomy': [(13, 1, 1, 12, 31), (13, 2, 19, 13, -1), (23, 1, 1, 22, 29), (23, 2, 26, 23, -1),
                    (28, 69, 69, 29, -68), (29, 1, 28, 29, 1)],
    '1 Samuel': [(21, 1, 1, 20, 41), (21, 2, 16, 21, -1), (24, 1, 1, 23, 28), (24, 2, 23, 24, -1)],
    '2 Samuel': [(19, 1, 1, 18, 32), (19, 2, 44, 19, -1)],
    '1 Kings': [(5, 1, 14, 4, 20), (5, 15, 32, 5, -14), (22, 44, 44, 22, -1), (22, 45, 54, 22, -1)],
    '2 Kings': [(12, 1, 1, 11, 20), (12, 2, 22, 12, -1)],
    '1 Chronicles': [(5, 27, 41, 6, -26), (6, 1, 66, 6, 15), (12, 5, 41, 12, -1)],
    '2 Chronicles': [(1, 18, 18, 2, -17), (2, 1, 17, 2, 1), (13, 23, 23, 14, -22), (14, 1, 14, 14, 1)],
    'Nehemiah': [(3, 33, 38, 4, -32), (4, 1, 17, 4, 6), (7, 68, 72, 7, 1), (10, 1, 1, 9, 37), (10, 2, 40, 10, -1)],
    'Job': [(40, 25, 32, 41, -24), (41, 1, 26, 41, 8)],
    'Ecclesiastes': [(4, 17, 17, 5, -16), (5, 1, 19, 5, 1)],
    'Song of Solomon': [(7, 1, 1, 6, 12), (7, 2, 14, 7, -1)],
    'Isaiah': [(8, 23, 23, 9, -22), (9, 1, 20, 9, 1), (64, 1, 11, 64, 1)],
    'Jeremiah': [(8, 23, 23, 9, -22), (9, 1, 25, 9, 1)],
    'Ezekiel': [(21, 1, 5, 20, 44), (21, 6, 37, 21, -5)],
    'Daniel': [(3, 31, 33, 4, -30), (4, 1, 34, 4, 3), (6, 1, 1, 5, 30), (6, 2, 29, 6, -1)],
    'Hosea': [(2, 1, 2, 1, 9), (2, 3, 25, 2, -2), (12, 1, 1, 11, 11), (12, 2, 15, 12, -1),
              (14, 1, 1, 13, 15), (14, 2, 10, 14, -1)],
    'Joel': [(3, 1, 5, 2, 27), (4, 1, 21, 3, 0)],
    'Jonah': [(2, 1, 1, 1, 16), (2, 2, 11, 2, -1)],
    'Micah': [(4, 14, 14, 5, -13), (5, 1, 14, 5, 1)],
    'Nahum': [(2, 1, 1, 1, 14), (2, 2, 14, 2, -1)],
    'Zechariah': [(2, 1, 4, 1, 17), (2, 5, 17, 2, -4)],
    'Malachi': [(3, 19, 24, 4, -18)],
}
# Psalms whose title is a verse of its own in Hebrew (two verses in 51, 52, 54, 60): the English
# prints the title inside verse 1, so Hebrew verse v is English v - title_verses.
PSALM_TITLE_VERSES = {p: 1 for p in (
    3, 4, 5, 6, 7, 8, 9, 12, 13, 18, 19, 20, 21, 22, 30, 31, 34, 36, 38, 39, 40, 41, 42, 44, 45, 46, 47, 48,
    49, 53, 55, 56, 57, 58, 59, 61, 62, 63, 64, 65, 67, 68, 69, 70, 75, 76, 77, 80, 81, 83, 84, 85, 88, 89,
    92, 102, 108, 140, 142)}
PSALM_TITLE_VERSES.update({51: 2, 52: 2, 54: 2, 60: 2})
READER_CODES = {
    'Genesis': 'Gen', 'Exodus': 'Exo', 'Leviticus': 'Lev', 'Numbers': 'Num', 'Deuteronomy': 'Deu',
    '1 Samuel': '1Sa', '2 Samuel': '2Sa', '1 Kings': '1Ki', '2 Kings': '2Ki', '1 Chronicles': '1Ch',
    '2 Chronicles': '2Ch', 'Nehemiah': 'Neh', 'Job': 'Job', 'Psalms': 'Psa', 'Ecclesiastes': 'Ecc',
    'Song of Solomon': 'Sng', 'Isaiah': 'Isa', 'Jeremiah': 'Jer', 'Ezekiel': 'Eze', 'Daniel': 'Dan',
    'Hosea': 'Hos', 'Joel': 'Joe', 'Jonah': 'Jon', 'Micah': 'Mic', 'Nahum': 'Nah', 'Zechariah': 'Zec',
    'Malachi': 'Mal',
}


class Command(BaseCommand):
    help = 'Build search/data/english_versification.json (reader verse -> English-numbered verse).'

    def add_arguments(self, parser):
        parser.add_argument('--report', action='store_true', help='Print what was applied and skipped.')

    def handle(self, *args, report=False, **options):
        with connection.cursor() as cur:
            cur.execute("SELECT split_part(ref, '.', 1), split_part(ref, '.', 2)::int, "
                        "split_part(split_part(ref, '.', 3), '-', 1)::int FROM old_testament.hebrewdata "
                        "WHERE ref ~ '^[0-9A-Za-z]+\\.[0-9]+\\.[0-9]+-' GROUP BY 1, 2, 3")
            reader = Counter()
            reader_verses = set()
            for code, chapter, verse in cur.fetchall():
                reader[(code, chapter)] += 1
                reader_verses.add((code, chapter, verse))
            cur.execute("SELECT book, chapter::int, count(*) FROM litv WHERE chapter ~ '^[0-9]+$' GROUP BY 1, 2")
            english = {(book, chapter): n for book, chapter, n in cur.fetchall()}

        mapping, totals = {}, Counter()
        for book, rules in HEBREW_TO_ENGLISH.items():
            code = READER_CODES[book]
            book_map = {}
            for chapter, first, last, eng_chapter, offset in rules:
                hebrew_numbered = reader[(code, chapter)] != english.get((book, chapter))
                if not hebrew_numbered:
                    totals['skipped (reader already English)'] += 1
                    if report:
                        self.stdout.write(f'skip   {book} {chapter}:{first}-{last} (reader numbers it the English way)')
                    continue
                for verse in range(first, last + 1):
                    if (code, chapter, verse) in reader_verses:
                        book_map[f'{chapter}:{verse}'] = f'{eng_chapter}:{verse + offset}'
                totals['rules applied'] += 1
                if report:
                    self.stdout.write(f'apply  {book} {chapter}:{first}-{last} -> {eng_chapter}:{first + offset}-{last + offset}')
            if book_map:
                mapping[book] = book_map

        psalms = {}
        for psalm, titles in PSALM_TITLE_VERSES.items():
            count = reader[('Psa', psalm)]
            for verse in range(1, count + 1):
                eng = max(1, verse - titles)
                eng = min(eng, english.get(('Psalms', psalm), eng))
                if eng != verse:
                    psalms[f'{psalm}:{verse}'] = f'{psalm}:{eng}'
        mapping['Psalms'] = psalms
        totals['psalm verses renumbered'] = len(psalms)

        with open(OUT_PATH, 'w', encoding='utf-8') as fh:
            json.dump(mapping, fh, ensure_ascii=False, sort_keys=True, separators=(',', ':'))
            fh.write('\n')
        self.stdout.write(self.style.SUCCESS(
            f'Wrote {OUT_PATH}: ' + ', '.join(f'{k} {v}' for k, v in sorted(totals.items()))))
