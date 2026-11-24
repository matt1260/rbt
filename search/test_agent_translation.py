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


V1 = 'En la cabeza <span style="color: blue;">él</span> está cortando.'
V2 = '<b>Y</b> la Tierra era un desierto informe <a href="?footnote=1-2-1">1</a>'
N1 = '<p class="rbt_footnote">El griego <strong>λόγος</strong> es "razón".</p>'


@override_settings(TRANSLATION_BACKEND='agent')
@mock.patch.object(at, '_extract', side_effect=fake_extract)
@mock.patch.object(at, '_needed_titles', return_value={})
class ChapterFlowTests(TestCase):
    def take(self, agent='tester', **kw):
        kw = kw or {'book': 'John', 'chapter': 1, 'language': 'es'}
        return at.get_source_content('chapter', agent=agent, **kw)

    def test_claim_save_complete(self, *_):
        work = self.take()
        job_id, token = work['job']['job_id'], work['claim_token']
        self.assertEqual(TranslationJob.objects.get(pk=job_id).status, at.AGENT_STATUS)
        self.assertEqual(work['job']['claimed_by'], 'tester')
        self.assertIsNone(work['job']['error'])  # the token is never shown as an error
        self.assertEqual(set(work['verses']), {'1', '2'})

        bad = at.save_translation('chapter', job_id, verses={'1': 'sin etiquetas'}, claim_token=token)
        self.assertEqual(bad['saved'], 0)
        self.assertFalse(VerseTranslation.objects.exists())  # all-or-nothing

        part = at.save_translation('chapter', job_id, verses={'1': V1}, agent='tester', claim_token=token)
        self.assertEqual(part['saved'], 1)
        row = VerseTranslation.objects.get(verse=1)
        self.assertEqual((row.status, row.generated_by), ('completed', 'agent:tester'))
        self.assertEqual(row.source_hash, tu.source_fingerprint(SOURCE_VERSES[1]))

        again = at.save_translation('chapter', job_id, verses={'1': V1}, claim_token=token)
        self.assertEqual((again['saved'], again['already_saved']), (0, 1))  # a retried save is harmless

        done = at.save_translation('chapter', job_id, verses={'2': V2}, footnotes={'John-1': N1}, claim_token=token)
        self.assertEqual(done['remaining'], 0)
        self.assertEqual(TranslationJob.objects.get(pk=job_id).status, 'completed')
        replay = at.save_translation('chapter', job_id, verses={'2': V2}, footnotes={'John-1': N1}, claim_token=token)
        self.assertEqual(replay, done)  # the reply was lost: asking again gives the same answer

    def test_stale_translation_is_offered_again(self, *_):
        VerseTranslation.objects.create(book='John', chapter=1, verse=1, language_code='es', verse_text='viejo',
                                        status='completed', source_hash=tu.source_fingerprint('older English'))
        VerseTranslation.objects.create(book='John', chapter=1, verse=2, language_code='es', verse_text='bien',
                                        status='completed', source_hash=None)  # pre-fingerprint: trusted
        self.assertEqual(set(self.take()['verses']), {'1'})

    def test_validate_saves_nothing(self, *_):
        job_id = self.take()['job']['job_id']
        self.assertTrue(at.validate_translation('chapter', job_id, verses={'1': V1})['valid'])
        self.assertFalse(VerseTranslation.objects.exists())

    def test_draft_then_publish(self, *_):
        work = self.take()
        at.save_translation('chapter', work['job']['job_id'], publish=False, verses={'1': V1},
                            claim_token=work['claim_token'])
        self.assertEqual(VerseTranslation.objects.get(verse=1).status, at.DRAFT)
        self.assertEqual(at.publish_translation('chapter', 'John', 1, 'es')['published'], 1)
        self.assertEqual(VerseTranslation.objects.get(verse=1).status, 'completed')

    def test_release_needs_the_token(self, *_):
        work = self.take()
        with self.assertRaises(at.ClaimConflict):
            at.release('chapter', work['job']['job_id'], claim_token='guess')
        at.release('chapter', work['job']['job_id'], claim_token=work['claim_token'])
        self.assertEqual(TranslationJob.objects.get(pk=work['job']['job_id']).status, 'pending')
        with self.assertRaises(at.ClaimConflict):
            at.save_translation('chapter', work['job']['job_id'], verses={'1': V1}, claim_token=work['claim_token'])


@override_settings(TRANSLATION_BACKEND='agent')
@mock.patch.object(at, '_extract', side_effect=fake_extract)
@mock.patch.object(at, '_needed_titles', return_value={})
class ConcurrencyTests(TestCase):
    def test_second_agent_cannot_take_a_claimed_chapter(self, *_):
        first = at.get_source_content('chapter', 'John', 1, 'es', agent='a')
        with self.assertRaises(at.ClaimConflict):
            at.get_source_content('chapter', 'John', 1, 'es', agent='b')
        with self.assertRaises(at.ClaimConflict):
            at.get_source_content('chapter', job_id=first['job']['job_id'], agent='b')
        self.assertEqual(TranslationJob.objects.filter(book='John', chapter=1, language_code='es').count(), 1)

    def test_next_gives_parallel_agents_different_chapters(self, *_):
        for jid, ch in (('j1', 1), ('j2', 2), ('j2b', 2)):  # two requests for chapter 2
            TranslationJob.objects.create(job_id=jid, book='John', chapter=ch, language_code='es', status='pending')
        a = at.get_source_content('chapter', agent='a')
        b = at.get_source_content('chapter', agent='b')
        c = at.get_source_content('chapter', agent='c')
        self.assertEqual({a['job']['chapter'], b['job']['chapter']}, {1, 2})
        self.assertIsNone(c['job'])  # the duplicate request for chapter 2 is not handed out twice

    def test_expired_claim_is_taken_over_and_the_old_token_stops_working(self, *_):
        from datetime import timedelta
        from django.utils import timezone
        old = at.get_source_content('chapter', 'John', 1, 'es', agent='slow')
        TranslationJob.objects.filter(pk=old['job']['job_id']).update(
            started_at=timezone.now() - at.CLAIM_TTL - timedelta(minutes=1))
        new = at.get_source_content('chapter', agent='fast')
        self.assertEqual(new['job']['job_id'], old['job']['job_id'])
        self.assertNotEqual(new['claim_token'], old['claim_token'])
        with self.assertRaises(at.ClaimConflict):
            at.save_translation('chapter', old['job']['job_id'], verses={'1': V1}, claim_token=old['claim_token'])

    def test_request_key_returns_the_same_claim(self, *_):
        TranslationJob.objects.create(job_id='k1', book='John', chapter=1, language_code='es', status='pending')
        TranslationJob.objects.create(job_id='k2', book='John', chapter=2, language_code='es', status='pending')
        first = at.get_source_content('chapter', agent='a', request_key='req-1')
        again = at.get_source_content('chapter', agent='a', request_key='req-1')
        self.assertEqual((again['job']['job_id'], again['claim_token']), (first['job']['job_id'], first['claim_token']))
        self.assertEqual(TranslationJob.objects.filter(status=at.AGENT_STATUS).count(), 1)

    def test_titles_are_claimed_per_language(self, *_):
        from django.core.cache import cache
        stale = [{'key': 'Jude|0|es', 'book': 'Jude', 'verse': 0, 'language': 'es', 'english': 'Praised',
                  'current_translation': 'x'},
                 {'key': 'Jude|0|pl', 'book': 'Jude', 'verse': 0, 'language': 'pl', 'english': 'Praised',
                  'current_translation': 'y'}]
        cache.delete(at._title_lock_key('es')); cache.delete(at._title_lock_key('pl'))
        with mock.patch.object(at, 'stale_titles', side_effect=lambda language=None, limit=200:
                               [s for s in stale if not language or s['language'] == language]):
            a = at.get_source_content('title', agent='a')
            b = at.get_source_content('title', agent='b')
            self.assertEqual({a['language'], b['language']}, {'es', 'pl'})
            with self.assertRaises(at.ClaimConflict):
                at.get_source_content('title', language=a['language'], agent='c')
            with self.assertRaises(at.ClaimConflict):
                at.save_translation('title', titles={}, language=a['language'], claim_token=b['claim_token'])
        cache.delete(at._title_lock_key('es')); cache.delete(at._title_lock_key('pl'))


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


from django.test import TransactionTestCase, skipUnlessDBFeature  # noqa: E402


@override_settings(TRANSLATION_BACKEND='agent')
@skipUnlessDBFeature('has_select_for_update_skip_locked')
class ParallelClaimTests(TransactionTestCase):
    """Real concurrency: agents claiming at the same instant on separate DB connections."""

    def test_simultaneous_claims_never_share_a_chapter(self):
        import threading
        from django.db import connection
        chapters = [1, 2, 3, 4, 5]
        for ch in chapters:
            TranslationJob.objects.create(job_id=f'p{ch}', book='John', chapter=ch, language_code='es', status='pending')
        TranslationJob.objects.create(job_id='p2-dup', book='John', chapter=2, language_code='es', status='pending')
        TranslationJob.objects.create(job_id='p4-dup', book='John', chapter=4, language_code='es', status='failed')
        results, errors, start = [], [], threading.Barrier(8)

        def agent(n):
            try:
                start.wait()
                r = at.get_source_content('chapter', agent=f'agent{n}')
                results.append(r['job'] and (r['job']['book'], r['job']['chapter']))
            except Exception as exc:  # noqa: BLE001
                errors.append(exc)
            finally:
                connection.close()

        threads = [threading.Thread(target=agent, args=(n,)) for n in range(8)]
        # Patched once for all threads: mock.patch is not thread-safe.
        with mock.patch.object(at, '_extract', side_effect=fake_extract), \
                mock.patch.object(at, '_needed_titles', return_value={}):
            for t in threads:
                t.start()
            for t in threads:
                t.join()
        self.assertEqual(errors, [])
        taken = [r for r in results if r]
        self.assertEqual(len(taken), len(set(taken)))            # nobody got the same chapter
        self.assertEqual(sorted(c for _, c in taken), chapters)  # and every chapter went to someone


class ScholarshipTests(TestCase):
    """Pure helpers and the edit log; the Bible tables are exercised against real data by hand."""

    def test_book_names(self):
        from search import scholarship as sch
        self.assertEqual(sch.resolve_book('Genesis')[2], 'genesis')
        self.assertEqual(sch.resolve_book('1John')[0], '1 John')
        self.assertEqual(sch.resolve_book('Jhn')[0] if False else sch.resolve_book('John')[2], 'nt')
        self.assertEqual(sch.resolve_book('Joe')[0], 'Joel')
        self.assertEqual(sch.resolve_book('Joseph and Aseneth')[2], 'special')
        with self.assertRaises(ValueError):
            sch.resolve_book('Hezekiah')

    def test_refs_and_strongs(self):
        from search import scholarship as sch
        self.assertEqual(sch._ref_parts('Gen.1.3-04'), ('Genesis', 1, 3, 4))
        self.assertEqual(sch._ref_parts('Joe.2.28')[:3], ('Joel', 2, 28))
        self.assertEqual(sch._parse_strongs('h0216'), ('H', 216))
        self.assertEqual(sch._parse_strongs('G3056'), ('G', 3056))
        with self.assertRaises(ValueError):
            sch._parse_strongs('logos')

    def test_verse_text_drops_media_and_markers(self):
        from search import scholarship as sch
        html = ('within an origin<a class="sdfootnoteanc" href="?footnote=1-1-1"><sup>1</sup></a>, and '
                '<div class="tooltip-container"><video src="x.mp4">Your browser</video><div class="tooltip">note</div></div>'
                'the <span style="color: blue;">Ratio</span>')
        self.assertEqual(sch._verse_text(html), 'within an origin, and the Ratio')
        self.assertEqual(sch._footnote_ids(html), ['1-1-1'])

    def test_revisions(self):
        from datetime import datetime, timedelta
        from search import scholarship as sch
        from search.models import TranslationUpdates
        now = datetime(2026, 11, 1, 12, 0)
        TranslationUpdates.objects.create(date=now, version='New Testament', reference='John 3:16', update_text='<p>new</p>')
        TranslationUpdates.objects.create(date=now - timedelta(days=1), version='New Testament', reference='John 3:16', update_text='old')
        TranslationUpdates.objects.create(date=now - timedelta(days=2), version='New Testament', reference='John 3:17', update_text='x')
        TranslationUpdates.objects.create(date=now - timedelta(days=3), version='New Testament Footnote',
                                          reference='John 3:16 - Joh-12', update_text='note')
        r = sch.get_revisions('John', 3, 16)
        self.assertEqual(r['total'], 3)
        self.assertEqual(r['revisions'][0]['text'], 'new')
        self.assertEqual(sch.get_revisions('John', 3)['total'], 4)
        self.assertEqual(sch.get_revisions('John', 3, 16, version='New Testament Footnote')['total'], 1)


@override_settings(RBT_AGENT_TOKEN_SHA256=[DIGEST])
class ScholarshipApiTests(TestCase):
    def test_abilities_are_routed(self):
        from search.views.agent_api import ABILITIES
        for name in ('get-verse', 'get-chapter', 'search-hebrew', 'search-greek', 'get-lexeme',
                     'get-occurrences', 'get-footnotes', 'get-revisions'):
            self.assertIn(name, ABILITIES)
        r = self.client.post('/api/agent/', json.dumps({'ability': 'get-lexeme', 'input': {'strongs': 'nonsense'}}),
                             content_type='application/json', HTTP_AUTHORIZATION=f'Bearer {TOKEN}')
        self.assertEqual(r.status_code, 400)


class HeldBooksTests(TestCase):
    """AGENT_CHAPTER_SCOPE='nt' (the default) keeps Old Testament chapters away from agents."""

    def setUp(self):
        from search.models import TranslationJob
        self.ot = TranslationJob.objects.create(job_id='ot-1', book='Isaiah', chapter=2, language_code='ta', status='pending')
        self.gen = TranslationJob.objects.create(job_id='gen-1', book='Genesis', chapter=1, language_code='ta', status='pending')
        self.nt = TranslationJob.objects.create(job_id='nt-1', book='Jude', chapter=1, language_code='sw', status='pending')

    def test_candidates_skip_ot(self):
        books = {j.book for j in at._chapter_candidates()}
        self.assertIn('Jude', books)
        self.assertNotIn('Isaiah', books)
        self.assertNotIn('Genesis', books)

    def test_named_ot_claims_are_refused(self):
        with self.assertRaises(ValueError):
            at._claim_chapter_job('ot-1', 'a')
        with mock.patch.object(at, '_require_language'):
            with self.assertRaises(ValueError):
                at._claim_chapter_for('Genesis', 1, 'ta', 'a')

    def test_untranslated_reports_held(self):
        out = at.get_untranslated(kind='chapter')
        self.assertEqual(out['chapter_held']['old_testament_chapters_waiting'], 2)
        self.assertEqual([j['book'] for j in out['chapter']], ['Jude'])

    @override_settings(AGENT_CHAPTER_SCOPE='all')
    def test_scope_all_offers_everything(self):
        books = {j.book for j in at._chapter_candidates()}
        self.assertEqual(books, {'Isaiah', 'Genesis', 'Jude'})
        self.assertNotIn('chapter_held', at.get_untranslated(kind='chapter'))
