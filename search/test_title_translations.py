"""
Tests for search/title_translations.py: translated book titles and the Judas heading go
stale when the English title changes. No database needed:

    python manage.py test search.test_title_translations
"""
from types import SimpleNamespace

from django.test import SimpleTestCase

from search import title_translations as titles
from search.translation_utils import source_fingerprint


def row(book, verse=0, text='T', source_hash=None):
    return SimpleNamespace(book=book, verse=verse, verse_text=text, source_hash=source_hash)


class TitleTranslationTests(SimpleTestCase):
    def test_english_titles(self):
        self.assertEqual(titles.english_title('Isaiah'), 'He Who Is Liberates')
        self.assertEqual(titles.english_title('1John'), 'First Favored')  # stored without the space
        self.assertEqual(titles.english_title('Gospel of Judas'), 'Gospel of Praised One (Judas)')
        self.assertEqual(titles.title_source('Gospel of Judas', 3), 'Gospel of Praised One')
        self.assertEqual(titles.english_title('Unknown Book'), 'Unknown Book')

    def test_current_and_stale(self):
        fresh = row('Jude', source_hash=source_fingerprint('Praised'))
        old = row('Jude', source_hash=source_fingerprint('Confessor'))
        self.assertTrue(titles.is_current(fresh))
        self.assertFalse(titles.is_current(old))
        self.assertFalse(titles.is_current(row('Jude', source_hash=titles.STALE)))
        self.assertTrue(titles.is_current(row('John')))  # saved before fingerprints: trusted
        self.assertFalse(titles.is_current(row('Jude')))  # ...unless the title was renamed since
        self.assertFalse(titles.is_current(row('Gospel of Judas', 3)))
        heading = row('Gospel of Judas', 3, source_hash=source_fingerprint('Gospel of Praised One'))
        self.assertTrue(titles.is_current(heading))

    def test_current_text_falls_back_to_english(self):
        self.assertEqual(titles.current_text(row('Jude', text='Alabado', source_hash=source_fingerprint('Praised'))), 'Alabado')
        self.assertIsNone(titles.current_text(row('Jude', text='Confesor', source_hash=titles.STALE)))
        self.assertIsNone(titles.current_text(row('Jude', text='', source_hash=source_fingerprint('Praised'))))
        self.assertIsNone(titles.current_text(None))
