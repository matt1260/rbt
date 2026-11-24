"""
Tests for translation by an agent (search/agent_translation.py) and its private API
(search/views/agent_api.py). Chapter extraction is faked, so no Bible tables are needed:

    python manage.py test search.test_agent_translation
"""
import hashlib
import json
from types import SimpleNamespace
from unittest import mock

from django.test import SimpleTestCase, TestCase, override_settings

from search import agent_translation as at
from search import paraphrase as pp
from search import paraphrase_translation as pt
from search import translation_utils as tu
from search.models import PromptGlossaryTerm, PromptLanguageOverride, PromptRule, TranslationJob, VerseTranslation

SOURCE_VERSES = {
    1: 'In the head <span style="color: blue;">he</span> is cutting out.',
    2: '<b>And</b> the Earth was a formless waste <a href="?footnote=1-2-1">1</a>',
}
SOURCE_NOTES = {'John-1': '<p class="rbt_footnote">The Greek <strong>λόγος</strong> is "ratio".</p>'}


def fake_extract(book, chapter, language):
    """What the worker would extract: everything for ALL_SOURCE, else only what is missing."""
    if language == at.ALL_SOURCE:
        return dict(SOURCE_VERSES), dict(SOURCE_NOTES)
    done = VerseTranslation.objects.filter(book=book, chapter=chapter, language_code=language, status='completed')
    verses = {v: t for v, t in SOURCE_VERSES.items() if not done.filter(verse=v, footnote_id__isnull=True).exists()}
    notes = {k: t for k, t in SOURCE_NOTES.items() if not done.filter(footnote_id=k).exists()}
    return verses, notes


class CheckTranslationTests(SimpleTestCase):
    def test_same_structure_passes(self):
        self.assertEqual(at.check_translation(
            SOURCE_VERSES[1], 'En la cabeza <span style="color: blue;">él</span> está cortando.', 'es'), [])

    def test_changed_attribute_fails(self):
        problems = at.check_translation(SOURCE_VERSES[1], 'En <span style="color: azul;">él</span>', 'es')
        self.assertTrue(any('HTML differs' in p for p in problems))

    def test_alt_text_may_be_translated(self):
        self.assertEqual(at.check_translation('<img src="a.jpg" alt="A seed">', '<img src="a.jpg" alt="Una semilla">', 'es'), [])

    def test_greek_must_be_copied(self):
        bad = '<p class="rbt_footnote">El griego <strong>λογος</strong> es "razón".</p>'
        self.assertTrue(any('Greek' in p for p in at.check_translation(SOURCE_NOTES['John-1'], bad, 'es')))
        good = '<p class="rbt_footnote">El griego <strong>λόγος</strong> es "razón".</p>'
        self.assertEqual(at.check_translation(SOURCE_NOTES['John-1'], good, 'es'), [])

    def test_hebrew_may_differ_when_translating_into_hebrew(self):
        self.assertEqual(at.check_translation('<b>The head</b>', '<b>הראש</b>', 'he'), [])
        self.assertTrue(at.check_translation('<b>The head</b>', '<b>הראש</b>', 'es'))

    def test_placeholders_and_empty_fail(self):
        self.assertTrue(at.check_translation('x', '[Translation error: boom]', 'es'))
        self.assertTrue(at.check_translation('x', '  ', 'es'))


@override_settings(TRANSLATION_BACKEND='agent')
class AgentModeGuardTests(SimpleTestCase):
    def test_gemini_helpers_refuse(self):
        for call in (lambda: tu.translate_chapter_batch({1: 'x'}, 'es'),
                     lambda: tu.translate_footnotes_batch({'a': 'x'}, 'es'),
                     lambda: tu.translate_verse_text('x', 'es'),
                     lambda: tu.translate_footnote_text('x', 'es')):
            with self.assertRaises(at.TranslationAPIDisabled):
                call()

    def test_worker_is_not_started(self):
        from search import translation_worker as tw
        with mock.patch.object(tw.TranslationWorker, 'start') as start:
            tw.ensure_worker_running()
        start.assert_not_called()

    @override_settings(TRANSLATION_BACKEND='gemini')
    def test_worker_starts_with_the_api_backend(self):
        from search import translation_worker as tw
        with mock.patch.object(tw.TranslationWorker, 'start') as start:
            tw.ensure_worker_running()
        start.assert_called_once()

    def test_instructions_include_the_rules_sent_to_gemini(self):
        with mock.patch.object(tu, '_db_rules', return_value=None):
            ins = at.instructions('pl')
        self.assertIn('Polski', ins['general'])
        self.assertIn(tu.CHAPTER_PROMPT_EXAMPLES, ins['verses'])
        self.assertIn(tu.FOOTNOTE_PROMPT_EXAMPLES, ins['footnotes'])
        self.assertIn('NOT a standard Bible book name', ins['titles'])


TOKEN = 'test-token-123'
DIGEST = hashlib.sha256(TOKEN.encode()).hexdigest()


@override_settings(TRANSLATION_BACKEND='agent', RBT_AGENT_TOKEN_SHA256=[DIGEST])
class AgentApiTests(TestCase):
    def call(self, ability, data=None, token=TOKEN):
        headers = {'HTTP_AUTHORIZATION': f'Bearer {token}'} if token else {}
        return self.client.post('/api/agent/', json.dumps({'ability': ability, 'input': data or {}}),
                                content_type='application/json', **headers)

    @override_settings(RBT_AGENT_TOKEN_SHA256=[])
    def test_switched_off_without_a_token_digest(self):
        self.assertEqual(self.call('list-languages').status_code, 404)

    def test_needs_the_token(self):
        self.assertEqual(self.call('list-languages', token=None).status_code, 401)
        self.assertEqual(self.call('list-languages', token='wrong').status_code, 401)

    def test_lists_languages(self):
        r = self.call('list-languages')
        self.assertEqual(r.status_code, 200)
        codes = [x['code'] for x in r.json()['result']['languages']]
        self.assertIn('es', codes)
        self.assertNotIn('en', codes)

    def test_unknown_ability(self):
        r = self.call('drop-tables')
        self.assertEqual(r.status_code, 404)
        self.assertIn('get-source-content', r.json()['abilities'])

    def test_bad_input_is_a_400(self):
        r = self.call('get-source-content', {'kind': 'chapter', 'book': 'John', 'chapter': 1, 'language': 'xx'})
        self.assertEqual(r.status_code, 400)
        self.assertIn('Unsupported language', r.json()['error'])


@override_settings(TRANSLATION_BACKEND='agent')
@mock.patch.object(at, '_extract', side_effect=fake_extract)
@mock.patch.object(at, '_needed_titles', return_value={})
class ChapterFlowTests(TestCase):
    def take(self):
        return at.get_source_content('chapter', 'John', 1, 'es', agent='tester')

    def test_claim_save_complete(self, *_):
        work = self.take()
        job_id = work['job']['job_id']
        self.assertEqual(TranslationJob.objects.get(pk=job_id).status, at.AGENT_STATUS)
        self.assertEqual(set(work['verses']), {'1', '2'})
        self.assertIn('John-1', work['footnotes'])

        bad = at.save_translation('chapter', job_id, verses={'1': 'sin etiquetas'})
        self.assertEqual(bad['saved'], 0)
        self.assertFalse(VerseTranslation.objects.exists())  # all-or-nothing

        part = at.save_translation('chapter', job_id, verses={
            '1': 'En la cabeza <span style="color: blue;">él</span> está cortando.'}, agent='tester')
        self.assertEqual(part['saved'], 1)
        row = VerseTranslation.objects.get(verse=1)
        self.assertEqual(row.status, 'completed')
        self.assertEqual(row.generated_by, 'agent:tester')
        self.assertEqual(row.source_hash, tu.source_fingerprint(SOURCE_VERSES[1]))
        self.assertEqual(TranslationJob.objects.get(pk=job_id).status, at.AGENT_STATUS)

        done = at.save_translation('chapter', job_id, verses={
            '2': '<b>Y</b> la Tierra era un desierto informe <a href="?footnote=1-2-1">1</a>'},
            footnotes={'John-1': '<p class="rbt_footnote">El griego <strong>λόγος</strong> es "razón".</p>'})
        self.assertEqual(done['remaining'], 0)
        self.assertEqual(TranslationJob.objects.get(pk=job_id).status, 'completed')

    def test_stale_translation_is_offered_again(self, *_):
        VerseTranslation.objects.create(book='John', chapter=1, verse=1, language_code='es', verse_text='viejo',
                                        status='completed', source_hash=tu.source_fingerprint('older English'))
        VerseTranslation.objects.create(book='John', chapter=1, verse=2, language_code='es', verse_text='bien',
                                        status='completed', source_hash=None)  # pre-fingerprint: trusted
        work = self.take()
        self.assertEqual(set(work['verses']), {'1'})

    def test_validate_saves_nothing(self, *_):
        job_id = self.take()['job']['job_id']
        ok = at.validate_translation('chapter', job_id, verses={
            '1': 'En la cabeza <span style="color: blue;">él</span> está cortando.'})
        self.assertTrue(ok['valid'])
        self.assertFalse(VerseTranslation.objects.exists())

    def test_draft_then_publish(self, *_):
        job_id = self.take()['job']['job_id']
        at.save_translation('chapter', job_id, publish=False, verses={
            '1': 'En la cabeza <span style="color: blue;">él</span> está cortando.'})
        self.assertEqual(VerseTranslation.objects.get(verse=1).status, at.DRAFT)
        self.assertEqual(at.publish_translation('chapter', 'John', 1, 'es')['published'], 1)
        self.assertEqual(VerseTranslation.objects.get(verse=1).status, 'completed')

    def test_saving_needs_a_claim(self, *_):
        job_id = self.take()['job']['job_id']
        at.release('chapter', job_id)
        with self.assertRaises(ValueError):
            at.save_translation('chapter', job_id, verses={'1': 'x'})
        self.assertEqual(TranslationJob.objects.get(pk=job_id).status, 'pending')


MEDIA = [pp.Media(n=1, verse='1', html='<div class="tooltip-container"><img src="a.jpg"/><div class="tooltip">'
                  '<b>Seed</b> notes</div></div>', kind='image', caption='Seed notes', title='Seed')]
ENGLISH, _ = pp.finalize_output(
    '<p data-v="1-2">In the beginning <span style="color: blue;">was</span> the Word.<rbt-media n="1"></rbt-media></p>'
    '<blockquote data-v="3" class="pp-poetry">All things<br>came to be.</blockquote>', MEDIA, ['1', '2', '3'])


class ParaphraseUnitTests(SimpleTestCase):
    def test_units_round_trip(self):
        notes, blocks = pt.translation_units(ENGLISH)
        self.assertEqual(set(notes), {'N1'})
        self.assertEqual(set(blocks), {1, 2})
        self.assertIn('<rbt-media n="1">', blocks[1])
        self.assertEqual(pt.assemble_html(ENGLISH, notes, blocks), pt.assemble_html(ENGLISH, *pt.translation_units(ENGLISH)))
        rebuilt = pt.assemble_html(ENGLISH, {'N1': notes['N1'].replace('Seed', 'Ziarno')},
                                   {1: blocks[1].replace('In the beginning', 'Na początku'), 2: blocks[2]})
        self.assertIn('Na początku', rebuilt)
        self.assertIn('Ziarno', rebuilt)

    def test_translate_html_still_uses_gemini_helpers(self):
        with mock.patch.object(pt, 'translate_chapter_batch', side_effect=lambda v, l, chapter=None: v), \
                mock.patch.object(pt, 'translate_footnotes_batch', side_effect=lambda n, l: n):
            self.assertEqual(pt.translate_html(ENGLISH, 'pl', chapter=1),
                             pt.assemble_html(ENGLISH, *pt.translation_units(ENGLISH)))


class GlossaryTests(TestCase):
    def test_candidate_renderings_are_not_sent(self):
        PromptRule.objects.create(scope='chapter', order=1, text='Keep HTML.', active=True)
        result = at.update_glossary(terms=[{
            'term': 'eternal circuit', 'sense': 'עוֹלָם: a cycle that returns on itself', 'use_guidance': 'a word for cycle',
            'overrides': {'de': 'Ewiger Kreislauf', 'pl': {'rendering': 'Wieczny obieg', 'status': 'candidate'}},
        }])
        self.assertTrue(result['saved'])
        self.assertTrue(PromptLanguageOverride.objects.get(term__term='eternal circuit', language_code='de').active)
        self.assertFalse(PromptLanguageOverride.objects.get(term__term='eternal circuit', language_code='pl').active)
        self.assertIn('Ewiger Kreislauf', tu.build_glossary_section('de'))
        self.assertNotIn('Wieczny obieg', tu.build_glossary_section('pl'))
        pl = at.get_glossary('pl')
        term = next(t for t in pl['glossary'] if t['term'] == 'eternal circuit')
        self.assertEqual(term['candidate_renderings'], ['Wieczny obieg'])
        self.assertIsNone(term['required_rendering'])

    def test_new_term_needs_sense_and_rules_cannot_be_emptied(self):
        r = at.update_glossary(terms=[{'term': 'ratio'}], rules={'chapter': []})
        self.assertFalse(r['saved'])
        self.assertFalse(PromptGlossaryTerm.objects.filter(term='ratio').exists())


class BookSyncTests(TestCase):
    def test_percentages(self):
        sources = {(1, 1): 'h1', (1, 2): 'h2', (1, 3): 'h3', (1, 4): 'h4'}
        VerseTranslation.objects.create(book='Jude', chapter=1, verse=1, language_code='de', status='completed',
                                        verse_text='a', source_hash='h1')
        VerseTranslation.objects.create(book='Jude', chapter=1, verse=2, language_code='de', status='completed',
                                        verse_text='b', source_hash='old')
        VerseTranslation.objects.create(book='Jude', chapter=1, verse=3, language_code='de', status='completed',
                                        verse_text='c', source_hash=None)
        with mock.patch.object(at, '_book_sources', return_value=sources):
            result = at.book_sync('Jude', 'de')
        de = result['languages'][0]
        self.assertEqual((de['synchronized_pct'], de['outdated_pct'], de['remaining_pct']), (50.0, 25.0, 25.0))


class UntranslatedTests(TestCase):
    def test_failed_and_orphaned_jobs_are_listed_once(self):
        from datetime import timedelta
        from django.utils import timezone
        old = timezone.now() - timedelta(hours=1)
        mk = lambda jid, ch, status, **kw: TranslationJob.objects.create(
            job_id=jid, book='John', chapter=ch, language_code='es', status=status, **kw)
        mk('p1', 1, 'pending')
        mk('f1', 2, 'failed')
        mk('f2', 2, 'failed')            # duplicate of chapter 2
        mk('f3', 3, 'failed')
        mk('c3', 3, 'completed')         # chapter 3 succeeded later
        mk('o4', 4, 'processing', started_at=old)
        chapters = [j['chapter'] for j in at.get_untranslated('chapter', 'es')['chapter']]
        self.assertEqual(chapters[0], 1)  # pending first
        self.assertEqual(sorted(chapters), [1, 2, 4])
