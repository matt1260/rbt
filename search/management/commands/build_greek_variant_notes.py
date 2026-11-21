"""
Build search/data/greek_variant_notes.json: for each NT verse, the interlinear words the Greek text
the RBT translates lacks (with a note per variant), and a note on passages Westcott-Hort print in
double brackets [[ ]]. See search/greek_variants.py for how words are matched.

    python manage.py build_greek_variant_notes [--report FILE.tsv]

Rebuild after changing new_testament.nt.versetext or the interlinear's Greek words.
"""
import csv
import json
from collections import defaultdict

from django.core.management.base import BaseCommand
from django.db import connection

from search.greek_variants import (
    TABLE_PATH, compare_with_rbt_text, double_bracket_verses,
)

NT_BOOKS = ('Mat Mar Luk Joh Act Rom 1Co 2Co Gal Eph Php Col 1Th 2Th 1Ti 2Ti Tit Phm Heb Jam '
            '1Pe 2Pe 1Jo 2Jo 3Jo Jud Rev').split()


class Command(BaseCommand):
    help = 'Build search/data/greek_variant_notes.json (NT interlinear words not in the RBT text).'

    def add_arguments(self, parser):
        parser.add_argument('--report', help='Write every note to this TSV for review.')

    def handle(self, *args, **options):
        with connection.cursor() as cursor:
            cursor.execute('SELECT book, chapter, startverse, versetext FROM new_testament.nt')
            texts = {f'{b}.{c}.{v}': t for b, c, v, t in cursor.fetchall()}
            cursor.execute('SELECT verse, lemma FROM rbt_greek.strongs_greek ORDER BY id')
            words = defaultdict(list)            # 'Act.2.44' -> [('04', '‹πιστεύοντες'), ...]
            for token, lemma in cursor.fetchall():
                ref, seq = token.rsplit('-', 1)
                words[ref].append((seq, lemma))

        def order(ref):
            book, chapter, verse = ref.split('.')
            return (NT_BOOKS.index(book) if book in NT_BOOKS else 99, int(chapter), int(verse))

        refs = sorted(set(texts) | set(words), key=order)
        bracketed = double_bracket_verses([(r, texts.get(r)) for r in refs])

        table = {}
        report = []
        faded = 0
        for n, ref in enumerate(refs):
            prev_text = texts.get(refs[n - 1]) if n else ''
            next_text = texts.get(refs[n + 1]) if n + 1 < len(refs) else ''
            seqs = [s for s, _w in words.get(ref, [])]
            absent, notes = compare_with_rbt_text(
                [w for _s, w in words.get(ref, [])], texts.get(ref), prev_text, next_text)
            entry_words = {seq: notes.index(note) for seq, note in zip(seqs, absent) if note}
            faded += len(entry_words)
            if ref in bracketed:
                notes = notes + [bracketed[ref]]
            if notes:
                table[ref] = {'notes': notes, 'words': entry_words}
                report.extend((ref, note) for note in notes)

        with open(TABLE_PATH, 'w', encoding='utf-8') as fh:
            json.dump(table, fh, ensure_ascii=False, indent=0)
            fh.write('\n')
        if options.get('report'):
            with open(options['report'], 'w', encoding='utf-8', newline='') as fh:
                csv.writer(fh, delimiter='\t').writerows([('verse', 'note')] + report)
        self.stdout.write(f'{len(table)} verses with notes, {faded} faded words, '
                          f'{len(bracketed)} verses in [[ ]] -> {TABLE_PATH}')
