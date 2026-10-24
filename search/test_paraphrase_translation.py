"""
Tests for translated paraphrases (search/paraphrase_translation.py) and the page
translator's key fallback. The translator is mocked, so no API key or database is needed:

    python manage.py test search.test_paraphrase_translation
"""
import re
from types import SimpleNamespace
from unittest import mock

from bs4 import BeautifulSoup
from django.test import SimpleTestCase

from search import paraphrase as pp
from search import paraphrase_translation as pt
from search import translation_utils as tu

MEDIA = [
    pp.Media(n=1, verse='1', html='<div class="tooltip-container"><img src="a.jpg"/><div class="tooltip"><b>Seed</b> notes</div></div>',
             kind='image', caption='Seed notes', title='Seed'),
]
ENGLISH, _ = pp.finalize_output(
    '<p data-v="1-2">In the beginning <span style="color: blue;">was</span> the Word.<rbt-media n="1"></rbt-media></p>'
    '<blockquote data-v="3" class="pp-poetry">All things<br>came to be.</blockquote>',
    MEDIA, ['1', '2', '3'],
)


def fake_blocks(verses, language, chapter=None):
    """The 'translation': each block uppercased, as a model would return it."""
    return {n: text.upper().replace('<RBT-MEDIA N=', '<rbt-media n=').replace('</RBT-MEDIA>', '</rbt-media>')
            .replace('<SPAN STYLE="COLOR: BLUE;">', '<span style="color: blue;">').replace('</SPAN>', '</span>')
            .replace('<BR/>', '<br/>').replace('<BR>', '<br>')
            for n, text in verses.items()}


def fake_notes(notes, language):
    return {key: html.replace('Seed', 'Ziarno').replace('notes', 'uwagi') for key, html in notes.items()}


class TranslateHtmlTests(SimpleTestCase):
    def translate(self, blocks=fake_blocks, notes=fake_notes):
        with mock.patch.object(pt, 'RETRY_AFTER_SECONDS', 0), \
                mock.patch.object(pt, 'translate_chapter_batch', side_effect=blocks), \
                mock.patch.object(pt, 'translate_footnotes_batch', side_effect=notes):
            return pt.translate_html(ENGLISH, 'pl', chapter=1)

    def test_translates_text_and_keeps_structure(self):
        html = self.translate()
        soup = BeautifulSoup(html, 'html.parser')
        p, quote = soup.find('p'), soup.find('blockquote')
        self.assertIn('IN THE BEGINNING', p.get_text())
        self.assertEqual(p['data-v'], '1-2')
        self.assertEqual(quote['class'], ['pp-poetry'])
        self.assertIsNotNone(quote.find('br'))
        self.assertIsNotNone(p.find('span', style='color: blue;'))
        # Anchors for #v links are rebuilt.
        self.assertEqual([a['id'] for a in soup.select('.pp-anchor')], ['v1', 'v2', 'v3'])

    def test_cue_is_rebuilt_from_translated_notes(self):
        soup = BeautifulSoup(self.translate(), 'html.parser')
        cue = soup.select_one('p button.pp-cue')
        self.assertEqual(cue['data-media'], '1')
        self.assertIn('Ziarno', cue['title'])
        note = soup.select_one('.pp-media-store template[data-media="1"] .tooltip')
        self.assertIn('Ziarno', note.decode_contents())
        self.assertIsNotNone(soup.select_one('.pp-media-store img[src="a.jpg"]'))

    def test_model_never_sees_cue_markup_or_anchors(self):
        sent = {}

        def capture(verses, language, chapter=None):
            sent.update(verses)
            return fake_blocks(verses, language)
        self.translate(blocks=capture)
        self.assertEqual(set(sent), {1, 2})
        self.assertIn('<rbt-media n="1"></rbt-media>', sent[1])
        for leftover in ('pp-cue', 'pp-anchor', '<button', '<svg', '<img'):
            self.assertNotIn(leftover, ''.join(sent.values()))

    def test_a_dropped_image_goes_back_in_its_paragraph(self):
        def drop(verses, language, chapter=None):
            return {n: re.sub(r'<rbt-media[^>]*></rbt-media>', '', t) for n, t in fake_blocks(verses, language).items()}
        soup = BeautifulSoup(self.translate(blocks=drop), 'html.parser')
        self.assertIsNotNone(soup.select_one('p button.pp-cue[data-media="1"]'))

    def test_scripts_from_the_model_are_removed(self):
        def evil(verses, language, chapter=None):
            return {n: t + '<script>alert(1)</script><img src=x onerror=alert(1)>' for n, t in verses.items()}
        html = self.translate(blocks=evil)
        self.assertNotIn('script', html)
        self.assertNotIn('onerror', html)

    def test_a_missing_paragraph_is_retried_then_fails(self):
        calls = []

        def lose_two(verses, language, chapter=None):
            calls.append(set(verses))
            return {n: t for n, t in fake_blocks(verses, language).items() if n != 2}
        with self.assertRaises(RuntimeError):
            self.translate(blocks=lose_two)
        self.assertEqual(calls, [{1, 2}, {2}])

    def test_error_text_counts_as_missing(self):
        def broken(verses, language, chapter=None):
            return {n: '[Translation error: boom]' for n in verses}
        with self.assertRaises(RuntimeError):
            self.translate(blocks=broken)

    def test_quota_exhausted_fails(self):
        with self.assertRaisesRegex(RuntimeError, 'quota'):
            self.translate(blocks=lambda verses, language, chapter=None: {'__quota_exceeded__': True})

    def test_untranslated_note_stays_in_english(self):
        soup = BeautifulSoup(self.translate(notes=lambda notes, language: {}), 'html.parser')
        self.assertIn('Seed', soup.select_one('.pp-media-store .tooltip').decode_contents())


class StateTests(SimpleTestCase):
    english = SimpleNamespace(html=ENGLISH)

    def state(self, row, language='pl'):
        with mock.patch.object(pt.paraphrase, 'published_for', return_value=row):
            return pt.state('John', 1, language, english=self.english)

    def test_states(self):
        self.assertEqual(self.state(None), (None, 'missing'))
        current = SimpleNamespace(source_hash=pp.html_hash(ENGLISH))
        self.assertEqual(self.state(current), (current, 'current'))
        old = SimpleNamespace(source_hash='older')
        self.assertEqual(self.state(old), (old, 'stale'))

    def test_english_and_unknown_languages_are_not_translated(self):
        self.assertEqual(self.state(None, 'en'), (None, ''))
        self.assertEqual(self.state(None, 'xx'), (None, ''))


class KeyFallbackTests(SimpleTestCase):
    def test_invalid_and_spent_keys_move_on(self):
        self.assertTrue(tu._try_next_key("400 invalid_argument. {'message': 'api key not valid. please pass a valid api key.'}"))
        self.assertTrue(tu._try_next_key('429 resource exhausted'))
        self.assertTrue(tu._try_next_key("503 unavailable. {'message': 'this model is currently experiencing high demand.'}"))
        self.assertFalse(tu._try_next_key('500 internal error'))

    def test_generate_skips_a_rejected_key(self):
        used = []

        def client(api_key, **options):
            used.append(api_key)
            if api_key == 'bad':
                raise Exception('400 INVALID_ARGUMENT. API key not valid. Please pass a valid API key.')
            return SimpleNamespace(models=SimpleNamespace(generate_content=lambda **kw: SimpleNamespace(text=' ok ')))
        with mock.patch.object(tu, 'GEMINI_API_KEYS', ['bad', 'good']), mock.patch.object(tu.genai, 'Client', side_effect=client):
            self.assertEqual(tu._generate('hi'), 'ok')
        self.assertEqual(used, ['bad', 'good'])
