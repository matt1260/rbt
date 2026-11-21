"""
Tests for section headings in AI paraphrases (search/paraphrase.py): headings in model
output, the prompt rules, setting a heading, and the studio's "Suggest headings". DB access
is mocked, so no test database is needed:

    python manage.py test search.test_paraphrase_headings
"""
import json
from types import SimpleNamespace
from unittest import mock

from bs4 import BeautifulSoup
from django.test import RequestFactory, SimpleTestCase

from search import paraphrase as pp
from translate import paraphrase_api as api

MEDIA = [pp.Media(n=1, verse='2', html='<div class="tooltip-container"><img src="a.jpg"/><div class="tooltip"><b>Seed</b> notes</div></div>',
                  kind='image', caption='Seed notes', title='Seed')]


def staff(is_staff=True):
    return SimpleNamespace(is_authenticated=True, is_staff=is_staff, username='editor')


def top_level(html):
    return [node.name for node in BeautifulSoup(html, 'html.parser').children if getattr(node, 'name', None)]


class HeadingsInOutputTests(SimpleTestCase):
    def finalize(self, raw):
        return pp.finalize_output(raw, MEDIA, ['1', '2', '3'])[0]

    def test_keeps_a_heading_before_a_paragraph(self):
        html = self.finalize('<h5>Woken up on the <span style="color: blue;">Third Day</span></h5><p data-v="1-3">Text.</p>')
        self.assertEqual(top_level(html)[:2], ['h5', 'p'])
        self.assertIn('<h5>Woken up on the <span style="color: blue;">Third Day</span></h5>', html)

    def test_drops_misplaced_headings(self):
        html = self.finalize(
            '<h5>Twice</h5><h5>Kept</h5><p data-v="1">One.</p>'   # two in a row: the first goes
            '<p data-v="2">Two <h5>Inside</h5> words.</p>'         # inside a paragraph
            '<h5> </h5><p data-v="3">Three.</p>'                   # empty
            '<h5>At the end</h5>'                                  # nothing after it
            '<h2>Other level</h2>'
        )
        soup = BeautifulSoup(html, 'html.parser')
        self.assertEqual([h.get_text() for h in soup.find_all('h5')], ['Kept'])
        self.assertNotIn('Other level', html)
        self.assertNotIn('Inside', html)

    def test_a_media_marker_in_a_heading_goes_to_its_verse_paragraph(self):
        html = self.finalize('<h5>Seed <rbt-media n="1"></rbt-media></h5><p data-v="1">One.</p><p data-v="2-3">Two.</p>')
        soup = BeautifulSoup(html, 'html.parser')
        self.assertIsNone(soup.find('h5').find('button'))
        self.assertIsNotNone(soup.find('p', attrs={'data-v': '2-3'}).find('button', class_='pp-cue'))


class HeadingPromptTests(SimpleTestCase):
    def setUp(self):
        patcher = mock.patch.object(pp, 'published_headings', return_value=['Sold by the Brothers'])
        patcher.start()
        self.addCleanup(patcher.stop)
        glossary = mock.patch.object(pp, 'glossary_block', return_value='')
        glossary.start()
        self.addCleanup(glossary.stop)

    def test_headings_are_off_unless_asked_for(self):
        prompt = pp.build_system_prompt('Be smooth.')
        self.assertIn(pp.NO_HEADINGS, prompt)
        self.assertNotIn(pp.HEADING_RULES, prompt)

    def test_asking_for_headings_adds_the_rules_and_examples(self):
        prompt = pp.build_system_prompt('Be smooth.', headings=True)
        self.assertIn(pp.HEADING_RULES, prompt)
        self.assertIn('- Sold by the Brothers', prompt)
        self.assertNotIn(pp.NO_HEADINGS, prompt)

    def test_section_notes_come_from_the_verse_headings(self):
        verses = [('1', 'Text<h5>Love Fallen Short</h5>'), ('2', 'More'), ('3', '<h5> </h5><h5>Sweet  Water</h5>')]
        notes = pp.section_notes(verses)
        self.assertEqual(notes, [('1', 'Love Fallen Short'), ('3', 'Sweet Water')])
        prompt = pp.build_user_prompt('John', 2, '[1] Text', [], notes)
        self.assertIn('RBT SECTION NOTES', prompt)
        self.assertIn('[3] Sweet Water', prompt)
        self.assertNotIn('RBT SECTION NOTES', pp.build_user_prompt('John', 2, '[1] Text', []))


STORED = pp.finalize_output('<p data-v="1">One.</p><blockquote data-v="2">Two.</blockquote><p data-v="3">Three.</p>',
                            MEDIA, ['1', '2', '3'])[0]


class SetHeadingTests(SimpleTestCase):
    def test_adds_replaces_and_removes_a_heading(self):
        html = pp.set_heading(STORED, 1, 'The <Quote> & More')
        soup = BeautifulSoup(html, 'html.parser')
        self.assertEqual(top_level(html)[:4], ['p', 'h5', 'blockquote', 'p'])
        self.assertEqual(soup.find('h5').get_text(), 'The <Quote> & More')   # text, not markup
        self.assertNotIn('<quote>', html.lower())
        html = pp.set_heading(html, 1, 'Changed')
        self.assertEqual([h.get_text() for h in BeautifulSoup(html, 'html.parser').find_all('h5')], ['Changed'])
        self.assertNotIn('<h5', pp.set_heading(html, 1, '  '))

    def test_unknown_paragraph(self):
        with self.assertRaises(IndexError):
            pp.set_heading(STORED, 3, 'X')


class ParseSuggestionsTests(SimpleTestCase):
    def test_reads_json_in_fences_and_cleans_options(self):
        raw = '```json\n{"sections": [{"before": 3, "options": ["<b>Sweet</b> Water", "Sweet Water", "x"]},' \
              '{"before": "1", "options": ["Woken Up"]}]}\n```'
        self.assertEqual(pp.parse_heading_suggestions(raw, 3), [
            {'index': 0, 'options': ['Woken Up']},
            {'index': 2, 'options': ['Sweet Water', 'x']},
        ])

    def test_drops_bad_entries(self):
        raw = json.dumps({'sections': [
            {'before': 0, 'options': ['Too early']}, {'before': 9, 'options': ['Too late']},
            {'before': 2, 'options': ['A' * 200, 7]}, {'before': 2, 'options': ['Duplicate place']},
            {'before': True, 'options': ['Bool']}, 'junk', {'before': 2, 'options': ['Second try']},
        ]})
        self.assertEqual(pp.parse_heading_suggestions(raw, 3), [{'index': 1, 'options': ['Duplicate place']}])

    def test_nothing_usable_is_an_error(self):
        for raw in ('no json here', '{"sections": []}', '{"sections": [{"before": 1, "options": [""]}]}'):
            with self.assertRaises(ValueError):
                pp.parse_heading_suggestions(raw, 3)


class SuggestionJobTests(SimpleTestCase):
    @mock.patch.object(pp, 'cache')
    def test_a_running_job_that_outlived_its_worker_reads_as_failed(self, cache):
        cache.get.return_value = {'status': 'running', 'started': 0}
        self.assertEqual(pp.heading_suggestions('u')['status'], 'failed')

    @mock.patch.object(pp.threading, 'Thread')
    @mock.patch.object(pp, 'cache')
    def test_start_runs_once(self, cache, thread):
        cache.get.return_value = None
        row = SimpleNamespace(uid='u', pk=1)
        self.assertEqual(pp.start_heading_suggestions(row, 'openai', 'gpt-5.6-terra')['status'], 'running')
        thread.return_value.start.assert_called_once()
        cache.get.return_value = {'status': 'running', 'started': 9e18}
        pp.start_heading_suggestions(row, 'openai', 'gpt-5.6-terra')
        self.assertEqual(thread.call_count, 1)

    @mock.patch.object(pp, 'chapter_verses', return_value=[('2', 'x<h5>Sweet Water</h5>')])
    @mock.patch.object(pp, 'cache')
    @mock.patch.object(pp, 'ChapterParaphrase')
    def test_the_worker_stores_the_suggestions(self, rows, cache, chapter_verses):
        rows.objects.get.return_value = SimpleNamespace(book='John', chapter=2, html=STORED)
        calls = []

        def model(name, system, user):
            calls.append((system, user))
            return '{"sections": [{"before": 2, "options": ["Sweet Water"]}]}', {}
        with mock.patch.dict(pp.PROVIDERS, {'openai': model}), \
                mock.patch.object(pp, 'published_headings', return_value=[]), mock.patch.object(pp, 'close_old_connections'):
            pp._run_heading_suggestions(1, 'openai', 'gpt-5.6-terra', 'key', 100.0)
        stored = cache.set.call_args.args[1]
        self.assertEqual(stored['status'], 'done')
        self.assertEqual(stored['sections'], [{'index': 1, 'options': ['Sweet Water']}])
        system, user = calls[0]
        self.assertIn('[2] (verses 2) Two.', user)
        self.assertIn('[2] Sweet Water', user)      # the RBT section note
        self.assertIn('Return only JSON', system)


class HeadingApiTests(SimpleTestCase):
    def setUp(self):
        self.factory = RequestFactory()
        self.uid = '00000000-0000-0000-0000-000000000001'
        self.models = {'gemini': {'models': ['gemini-3.8-flash'], 'configured': True},
                       'openai': {'models': ['gpt-5.6-terra'], 'configured': True}}

    def post(self, view, payload, user=None):
        request = self.factory.post('/x/', data=json.dumps(payload), content_type='application/json')
        request.user = user or staff()
        return view(request)

    def test_staff_only(self):
        self.assertEqual(self.post(api.suggest_headings, {}, user=staff(False)).status_code, 403)
        self.assertEqual(self.post(api.set_heading, {}, user=staff(False)).status_code, 403)

    @mock.patch.object(pp, 'start_heading_suggestions', return_value={'status': 'running'})
    @mock.patch.object(api, 'ChapterParaphrase')
    def test_suggest_checks_the_model_and_starts(self, rows, start):
        with mock.patch.object(pp, 'available_models', return_value=self.models):
            bad = self.post(api.suggest_headings, {'uid': self.uid, 'provider': 'openai', 'model': 'made-up'})
            self.assertEqual(bad.status_code, 400)
            ok = self.post(api.suggest_headings, {'uid': self.uid, 'provider': 'openai', 'model': 'gpt-5.6-terra'})
        self.assertEqual(json.loads(ok.content), {'status': 'running'})
        start.assert_called_once()

    @mock.patch.object(api, 'transaction')
    @mock.patch.object(api, 'ChapterParaphrase')
    def test_set_heading_writes_and_refuses_stale_edits(self, rows, transaction):
        row = SimpleNamespace(html=STORED, book='John', chapter=2, save=mock.Mock())
        rows.objects.select_for_update.return_value.filter.return_value.first.return_value = row
        stale = self.post(api.set_heading, {'uid': self.uid, 'index': 0, 'heading': 'X', 'base_hash': 'old'})
        self.assertEqual(stale.status_code, 409)
        row.save.assert_not_called()
        ok = self.post(api.set_heading, {'uid': self.uid, 'index': 0, 'heading': 'Woken Up', 'base_hash': pp.html_hash(STORED)})
        data = json.loads(ok.content)
        self.assertIn('<h5>Woken Up</h5>', data['html'])
        self.assertEqual(data['hash'], pp.html_hash(data['html']))
        row.save.assert_called_once()


class BuiltinPresetTests(SimpleTestCase):
    @mock.patch('search.paraphrase_presets.ParaphrasePrompt')
    def test_created_once_never_overwritten(self, prompts):
        from search import paraphrase_presets as presets
        presets.ensure_builtin_presets()
        prompts.objects.get_or_create.assert_called_once_with(
            name='RBT light smoothing', defaults={'instructions': presets.LIGHT_SMOOTHING_INSTRUCTIONS})
        self.assertIn('WHAT TO KEEP EXACTLY', presets.LIGHT_SMOOTHING_INSTRUCTIONS)
        self.assertIn('EXAMPLES', presets.LIGHT_SMOOTHING_INSTRUCTIONS)
