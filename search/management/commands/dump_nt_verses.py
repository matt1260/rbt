import json

from django.core.management.base import BaseCommand

from search.db_utils import execute_query


class Command(BaseCommand):
    help = 'Dump every NT verse (new_testament.nt.rbt) as JSON, for the chapter editor round-trip audit (chapter-editor/scripts/roundtrip.ts)'

    def add_arguments(self, parser):
        parser.add_argument('output', help='Path of the JSON file to write')

    def handle(self, *args, **options):
        rows = execute_query(
            "SELECT book, chapter, startVerse, rbt FROM new_testament.nt ORDER BY nt_id",
            fetch='all',
        ) or []
        verses = [
            {'ref': f'{book} {chapter}:{verse}', 'html': html}
            for book, chapter, verse, html in rows
            if html
        ]
        with open(options['output'], 'w', encoding='utf-8') as handle:
            json.dump(verses, handle, ensure_ascii=False)
        self.stdout.write(f'Wrote {len(verses)} verses to {options["output"]}')
