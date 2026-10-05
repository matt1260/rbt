"""
Tests for AI chapter paraphrases: search/paraphrase.py, the sync merge rules and the
studio API guards. DB access is mocked, so no test database is needed:

    python manage.py test search.test_paraphrase
"""
import json
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest import mock

from bs4 import BeautifulSoup
from django.test import RequestFactory, SimpleTestCase

from search import paraphrase as pp
from search.management.commands.sync_paraphrases import _utc, plan_paraphrases, plan_presets
from translate import paraphrase_api as api

MEDIA = [
    pp.Media(n=1, verse='1', html='<div class="tooltip-container"><img src="a.jpg"/><div class="tooltip"><b>Seed</b> notes</div></div>',
             kind='image', caption='Seed notes', title='Seed'),
    pp.Media(n=2, verse='4', html='<div class="tooltip-container"><video src="b.mp4"></video></div>', kind='video', caption='', title=''),
]


class FinalizeOutputTests(SimpleTestCase):
    def finalize(self, raw, verses=('1', '2', '3', '4')):
        return pp.finalize_output(raw, MEDIA, list(verses))

    def test_sanitises_to_the_allowlist(self):
        html, _ = self.finalize(
            '```html\n<p data-v="1-4" class="pp-lead evil" onclick="x()" style="color:red">'
            '<span style="color: blue;">kept</span> <span style="color: red;">dropped style</span>'
            '<script>alert(1)</script><iframe src="x"></iframe></p>\n```'
        )
        self.assertIn('class="pp-lead"', html)
        self.assertIn('<span style="color: blue;">kept</span>', html)
        for bad in ('evil', 'onclick', 'color:red', 'color: red', 'script', 'alert', 'iframe', '```'):
            self.assertNotIn(bad, html)

    def test_marker_inside_a_sentence_becomes_an_inline_cue(self):
        html, _ = self.finalize('<p data-v="1-4">First sentence. <rbt-media n="1" align="left"></rbt-media> Second.</p>')
        self.assertIn(
            'First sentence. <button aria-label="View image: Seed" class="pp-cue pp-cue--image" data-media="1" '
            'title="Seed" type="button"><img alt="" class="pp-cue__thumb" decoding="async" loading="lazy" src="a.jpg"/></button> Second.',
            html,
        )
        self.assertNotIn('<figure', html)
        self.assertNotIn('align', html)

    def test_marker_between_paragraphs_joins_the_paragraph_before(self):
        html, _ = self.finalize('<p data-v="1-2">a</p><rbt-media n="1"></rbt-media><p data-v="3-4">b</p>')
        self.assertRegex(html, r'a <button[^>]*data-media="1".*?</button></p><p data-v="3-4">')

    def test_unknown_and_repeated_markers_are_dropped(self):
        html, _ = self.finalize('<p data-v="1-4">x <rbt-media n="1"></rbt-media> y <rbt-media n="1"></rbt-media><rbt-media n="9"></rbt-media></p>')
        self.assertEqual(html.count('<button'), 2)  # media 1 once, plus media 2 added (it was skipped)
        self.assertNotIn('rbt-media', html)

    def test_skipped_media_get_a_cue_at_the_end_of_their_verse(self):
        html, _ = self.finalize('<p data-v="1-2">a</p><p data-v="3-4">b</p>')
        self.assertRegex(html, r'a <button[^>]*data-media="1"')
        # Media 2 is a video from verse 4: a play-icon cue at the end of the 3-4 paragraph.
        self.assertRegex(html, r'b <button aria-label="View video" class="pp-cue pp-cue--video" data-media="2"[^>]*><svg aria-hidden="true" class="pp-cue__icon"[^>]*><path[^>]*></path></svg></button></p>')

    def test_original_media_are_kept_inert_for_the_modal(self):
        html, _ = self.finalize('<p data-v="1-4">a</p>')
        store = html[html.index('<div class="pp-media-store"'):]
        self.assertIn('<template data-media="1"><div class="tooltip-container"><img src="a.jpg"/><div class="tooltip"><b>Seed</b> notes</div></div></template>', store)
        self.assertIn('<template data-media="2">', store)

    def test_reports_missing_verses_and_adds_anchors(self):
        html, missing = self.finalize('<p data-v="1">a</p><p data-v="3">c</p>')
        self.assertEqual(missing, [2, 4])
        self.assertIn('<p data-v="1"><span class="pp-anchor" id="v1"></span>a', html)

    def test_headings_are_dropped_with_their_text(self):
        html, _ = self.finalize('<h5>Section</h5><h3>Other</h3><p data-v="1-4">Body</p>')
        self.assertNotIn('Section', html)
        self.assertNotIn('Other', html)
        self.assertIn('</span>Body', html)

    def test_rejects_malformed_verse_ranges(self):
        html, missing = self.finalize('<p data-v="1-x">a</p><p data-v="4-2">b</p>')
        self.assertNotIn('data-v="1-x"', html)
        self.assertEqual(missing, [1, 2, 3, 4])


QUOTE = ('"And I heard <span style="color: #ff00aa;">a mega voice</span> from out of '
         '<span style="color: blue;">the Throne</span>!"')
NOTED = pp.Media(
    n=1, verse='2', kind='image', caption='', title='',
    html=(f'<div class="tooltip-container"><img src="a.jpg"/><div class="tooltip"><b>The Beat</b>'
          f'<p>Wreathed Ones: a man sent out.</p><p>{QUOTE}</p>(Revelation 21:3 RBT)'
          '<center><img src="inner.png"/></center></div></div>'),
)


class NoteVerseTests(SimpleTestCase):
    """Verses quoted in media notes are paraphrased via exact-match rbt-note edits."""

    def finalize(self, notes):
        html, _ = pp.finalize_output(f'<p data-v="1-2">Body <rbt-media n="1"></rbt-media></p>{notes}', [NOTED], ['1', '2'])
        return html

    def note(self, html):
        return BeautifulSoup(html, 'html.parser').select_one('template[data-media="1"]').decode_contents()

    def test_prompt_sends_notes_that_quote_verses(self):
        prompt = pp.build_user_prompt('John', 1, '[1] a', [NOTED, MEDIA[0]])
        self.assertIn('NOTE 1:\n<b>The Beat</b>', prompt)
        self.assertIn('the Throne</span>!"', prompt)
        self.assertNotIn('NOTE 2', prompt)  # MEDIA[0]'s note quotes nothing

    def test_quoted_verse_is_replaced_and_the_rest_kept(self):
        html = self.finalize(
            f'<rbt-note n="1"><rbt-find>{QUOTE}</rbt-find>'
            '<rbt-replace>"I heard <span style="color: #ff00aa;">a great voice</span> '
            '<b onclick="x()">from</b> the Throne!"<script>alert(1)</script></rbt-replace></rbt-note>'
        )
        note = self.note(html)
        self.assertIn('a great voice', note)
        self.assertNotIn('mega voice', note)
        self.assertIn('<b>from</b>', note)
        self.assertNotIn('onclick', html)
        self.assertNotIn('alert', html)
        for kept in ('<b>The Beat</b>', 'Wreathed Ones: a man sent out.', '(Revelation 21:3 RBT)', 'inner.png', 'a.jpg'):
            self.assertIn(kept, note)
        self.assertNotIn('rbt-', html.replace('rbt-paraphrase', ''))  # no blocks left in the chapter
        self.assertIn('Body', html)

    def test_passages_that_do_not_match_exactly_are_skipped(self):
        for edit in (
            '<rbt-note n="1"><rbt-find>And I heard a mega voice</rbt-find><rbt-replace>X</rbt-replace></rbt-note>',  # tags missing
            '<rbt-note n="1"><rbt-find>sent out</rbt-find><rbt-replace>X</rbt-replace></rbt-note>',  # too short
            '<rbt-note n="1"><rbt-find><center><img src="inner.png"/></center></rbt-find><rbt-replace>X</rbt-replace></rbt-note>',
            f'<rbt-note n="9"><rbt-find>{QUOTE}</rbt-find><rbt-replace>X</rbt-replace></rbt-note>',  # no such media
        ):
            note = self.note(self.finalize(edit))
            self.assertIn('mega voice', note)
            self.assertIn('inner.png', note)

    def test_whitespace_differences_still_match(self):
        spaced = QUOTE.replace(' from out of ', '\n   from out of\n ')
        note = self.note(self.finalize(f'<rbt-note n="1"><rbt-find>{spaced}</rbt-find><rbt-replace>"Paraphrased!"</rbt-replace></rbt-note>'))
        self.assertIn('"Paraphrased!"', note)

    def test_unclosed_note_block_does_not_leak_into_the_chapter(self):
        html = self.finalize('<rbt-note n="1"><rbt-find>stray text')
        self.assertNotIn('stray text', html)


class SourceTests(SimpleTestCase):
    def test_prepare_source_extracts_media_and_keeps_rbt_spans(self):
        verses = [
            ('1', '<h5>Head</h5><span style="color: blue;">Word</span> and <span style="color: green;">x</span>'
                  '<a class="sdfootnoteanc" href="?footnote=1-1-1"><sup>1</sup></a>'
                  '<div class="tooltip-container"><img src="i.jpg"/><div class="tooltip"><b>Cap</b> tion</div></div>'),
            ('2', 'plain <span class="hayah">He Who Is</span> <img src="icon.png" alt="icon"/>'),
        ]
        text, media = pp.prepare_source(verses)
        self.assertEqual(text.splitlines(), [
            '[1] <span style="color: blue;">Word</span> and <span>x</span>',
            '[2] plain <span class="hayah">He Who Is</span>',
        ])
        self.assertEqual([(m.n, m.verse, m.kind, m.caption, m.title) for m in media],
                         [(1, '1', 'image', 'Cap tion', 'Cap'), (2, '2', 'image', 'icon', 'icon')])
        self.assertTrue(media[0].html.startswith('<div class="tooltip-container">'))

    @mock.patch.object(pp, 'glossary_block', return_value='- "Logos Ratio": a proportion.')
    def test_system_prompt_order(self, _glossary):
        prompt = pp.build_system_prompt('Be smooth.', 'Logos: keep it', include_glossary=True)
        self.assertLess(prompt.index('Be smooth.'), prompt.index('Logos: keep it'))
        self.assertLess(prompt.index('Logos: keep it'), prompt.index('Logos Ratio'))
        self.assertTrue(prompt.endswith(pp.OUTPUT_RULES))
        self.assertNotIn('Logos Ratio', pp.build_system_prompt('Be smooth.', include_glossary=False))


def row(uid, updated, published=False, published_at=None, chapter=1):
    return {'uid': uid, 'updated_at': updated, 'is_published': published, 'published_at': published_at,
            'book': 'John', 'chapter': chapter, 'language_code': 'en'}


T0 = datetime(2026, 9, 1, tzinfo=timezone.utc)


class SyncPlanTests(SimpleTestCase):
    def test_newer_copy_wins_and_new_rows_are_added(self):
        source = [row('a', T0 + timedelta(hours=2)), row('b', T0), row('c', T0)]
        target = [row('a', T0), row('b', T0 + timedelta(hours=1))]
        to_write, _ = plan_paraphrases(source, target)
        self.assertEqual({r['uid'] for r in to_write}, {'a', 'c'})

    def test_most_recently_published_wins_per_chapter(self):
        source = [row('new', T0, True, T0 + timedelta(days=2))]
        target = [row('old', T0, True, T0 + timedelta(days=1)), row('other', T0, True, T0, chapter=2)]
        _, published = plan_paraphrases(source, target)
        self.assertEqual(published, {'new', 'other'})

    def test_newer_unpublish_on_target_is_kept(self):
        source = [row('a', T0, True, T0)]
        target = [row('a', T0 + timedelta(hours=1), False)]
        to_write, published = plan_paraphrases(source, target)
        self.assertEqual((to_write, published), ([], set()))

    def test_timestamps_from_both_connections_compare(self):
        # Django's connection returns naive UTC (USE_TZ off); a raw psycopg2 connection returns aware.
        naive = _utc(datetime(2026, 9, 30, 2, 34))
        aware = _utc(datetime(2026, 9, 30, 4, 34, tzinfo=timezone(timedelta(hours=2))))
        self.assertEqual(naive, aware)
        self.assertEqual(_utc('not a date'), 'not a date')

    def test_single_default_preset(self):
        source = [{'name': 'Mine', 'updated_at': T0 + timedelta(hours=1), 'is_default': True}]
        target = [{'name': 'Default', 'updated_at': T0, 'is_default': True}]
        to_write, default = plan_presets(source, target)
        self.assertEqual(([r['name'] for r in to_write], default), (['Mine'], 'Mine'))


def staff(is_staff=True):
    return SimpleNamespace(is_authenticated=True, is_staff=is_staff, username='editor')


class StudioApiTests(SimpleTestCase):
    def setUp(self):
        self.factory = RequestFactory()
        self.models = {'gemini': {'models': ['gemini-3.8-flash'], 'configured': True},
                       'openai': {'models': ['gpt-5.6-terra'], 'configured': False}}

    def post(self, view, payload, user=None):
        request = self.factory.post('/x/', data=json.dumps(payload), content_type='application/json')
        request.user = user or staff()
        return view(request)

    def test_everything_is_staff_only(self):
        for view in (api.generate, api.publish, api.unpublish, api.delete, api.save_preset):
            self.assertEqual(self.post(view, {}, user=staff(False)).status_code, 403)
        request = self.factory.get('/x/', {'book': 'John', 'chapter': '1'})
        request.user = staff(False)
        self.assertEqual(api.state(request).status_code, 403)

    @mock.patch.object(pp, 'start_batch')
    def test_generate_validates_models_and_prompt(self, start_batch):
        base = {'book': 'John', 'chapter': 1, 'instructions': 'Be smooth.'}
        with mock.patch.object(pp, 'available_models', return_value=self.models):
            cases = [
                ({**base, 'models': []}, 'Choose at least one model'),
                ({**base, 'models': [['gemini', 'made-up-model']]}, 'not allowed'),
                ({**base, 'models': [['openai', 'gpt-5.6-terra']]}, 'No API key'),
                ({**base, 'instructions': ' ', 'models': [['gemini', 'gemini-3.8-flash']]}, 'Instructions'),
                ({**base, 'book': 'Genesis', 'models': [['gemini', 'gemini-3.8-flash']]}, 'Unknown NT book'),
            ]
            for payload, error in cases:
                response = self.post(api.generate, payload)
                self.assertEqual(response.status_code, 400, payload)
                self.assertIn(error, json.loads(response.content)['error'])
        start_batch.assert_not_called()

    @mock.patch.object(pp, 'start_batch')
    def test_generate_starts_a_batch(self, start_batch):
        start_batch.return_value = ('batch-1', [SimpleNamespace(uid='u1')])
        with mock.patch.object(pp, 'available_models', return_value=self.models):
            response = self.post(api.generate, {
                'book': 'John', 'chapter': 1, 'instructions': 'Be smooth.', 'word_guidance': 'x',
                'include_glossary': False, 'prompt_name': 'Default', 'models': [['gemini', 'gemini-3.8-flash']] * 2,
            })
        self.assertEqual(json.loads(response.content), {'batch_id': 'batch-1', 'uids': ['u1']})
        start_batch.assert_called_once_with(
            'John', 1, [('gemini', 'gemini-3.8-flash')], instructions='Be smooth.', word_guidance='x',
            include_glossary=False, prompt_name='Default', username='editor',
        )


STORED = pp.finalize_output(
    '<p data-v="1-2">First <rbt-media n="1"></rbt-media> one.</p><blockquote data-v="3">Second</blockquote><p data-v="4">Third.</p>',
    MEDIA, ['1', '2', '3', '4'],
)[0]


class EditBlockTests(SimpleTestCase):
    def test_replaces_one_paragraph_and_rebuilds_its_cue(self):
        # The client sends the paragraph back with its cue (tampered here) and anchors.
        edited = ('<span class="pp-anchor" id="v1"></span>Edited <em>text</em>. '
                  '<button class="pp-cue" data-media="1" onclick="x()"><img src="evil.jpg"></button>'
                  '<script>alert(1)</script>')
        html, block = pp.replace_block(STORED, 0, edited)
        self.assertIn('Edited <em>text</em>.', block)
        self.assertIn('src="a.jpg"', block)          # rebuilt from the stored media
        self.assertNotIn('evil.jpg', html)
        self.assertNotIn('onclick', html)
        self.assertNotIn('script', html)
        self.assertIn('id="v1"', block)
        self.assertIn('id="v2"', block)              # anchors re-added for the 1-2 range
        self.assertIn('<blockquote data-v="3">', html)  # other blocks untouched
        self.assertIn('Third.', html)
        self.assertIn('<template data-media="1">', html)

    def test_index_counts_paragraphs_and_quotes_only(self):
        html, block = pp.replace_block(STORED, 2, 'Changed')
        self.assertIn('id="v4"', block)
        self.assertIn('Changed', html)
        with self.assertRaises(IndexError):
            pp.replace_block(STORED, 3, 'x')

    def test_color_spellings_from_the_page_toggles_are_kept(self):
        # chapter-viewer.js's Blue/Magenta toggles leave rgb(), or "inherit" while hidden.
        edit = ('<span style="color: rgb(255, 0, 170);">a</span> <span style="color:#FF00AA">b</span> '
                '<span style="color: inherit;" data-orig-color-magenta="rgb(255, 0, 170)">c</span> '
                '<span style="color: inherit;" data-orig-color-blue="blue">d</span> '
                '<span style="color: rgb(0, 0, 255)">e</span> <span style="color: red;">f</span> '
                '<span style="display: block; color: blue;">g</span>')
        _, block = pp.replace_block(STORED, 2, edit)
        self.assertEqual(block.count('<span style="color: #ff00aa;">'), 3)
        self.assertEqual(block.count('<span style="color: blue;">'), 2)
        self.assertNotIn('red', block)
        self.assertNotIn('display', block)
        self.assertNotIn('data-orig', block)

    def test_leading_h5_becomes_the_heading_above_the_paragraph(self):
        html, block = pp.replace_block(STORED, 2, '<h5><span style="color: blue;">The Lamb</span> <b onclick="x()">x</b></h5>Third.')
        self.assertIn('<h5><span style="color: blue;">The Lamb</span> x</h5><p data-v="4">', html)
        self.assertTrue(block.startswith('<h5>'))
        self.assertIn('id="v4"', block)
        # Headings don't count as paragraphs, so indexes stay put.
        html, block = pp.replace_block(html, 2, '<h5>The Lamb of God</h5>Third, edited.')
        self.assertEqual(html.count('<h5>'), 1)
        self.assertIn('<h5>The Lamb of God</h5><p data-v="4">', html)
        self.assertIn('Third, edited.', block)
        # Untouched paragraphs keep no heading.
        self.assertNotIn('<h5>', pp.editor_html(pp.editable_blocks(BeautifulSoup(html, 'html.parser'))[1]))

    def test_no_or_empty_heading_removes_it(self):
        with_heading, _ = pp.replace_block(STORED, 1, '<h5>Quote</h5>Second')
        self.assertIn('<h5>Quote</h5><blockquote', with_heading)
        for edit in ('Second', '<h5> </h5>Second', '<h5><span style="color: blue;"></span></h5>Second'):
            html, block = pp.replace_block(with_heading, 1, edit)
            self.assertNotIn('<h5>', html)
            self.assertFalse(block.startswith('<h5>'))

    def test_heading_text_in_mid_paragraph_stays_text(self):
        html, _ = pp.replace_block(STORED, 2, 'Before <h5>Middle</h5> after')
        self.assertNotIn('<h5>', html)
        self.assertIn('Before Middle after', html)

    @mock.patch.object(api.transaction, 'atomic', mock.MagicMock())
    def test_endpoint(self):
        factory = RequestFactory()
        row = SimpleNamespace(html=STORED, book='John', chapter=1, save=mock.Mock())
        uid = '00000000-0000-0000-0000-000000000001'

        def post(payload, user=None):
            request = factory.post('/x/', data=json.dumps(payload), content_type='application/json')
            request.user = user or staff()
            return api.edit_block(request)

        self.assertEqual(post({'uid': uid, 'index': 0, 'html': 'x', 'base_hash': 'h'}, user=staff(False)).status_code, 403)
        with mock.patch.object(api.ChapterParaphrase.objects, 'select_for_update') as select:
            select.return_value.filter.return_value.first.return_value = row
            stale = post({'uid': uid, 'index': 0, 'html': 'x', 'base_hash': 'stale'})
            self.assertEqual(stale.status_code, 409)
            row.save.assert_not_called()

            good = post({'uid': uid, 'index': 1, 'html': 'New quote', 'base_hash': pp.html_hash(STORED)})
            self.assertEqual(good.status_code, 200)
            data = json.loads(good.content)
            self.assertIn('New quote', data['html'])
            self.assertEqual(data['hash'], pp.html_hash(row.html))
            row.save.assert_called_once()

            out_of_range = post({'uid': uid, 'index': 9, 'html': 'x', 'base_hash': pp.html_hash(row.html)})
            self.assertEqual(out_of_range.status_code, 400)


class EditNoteTests(SimpleTestCase):
    def test_replaces_one_note_and_keeps_its_markup(self):
        edited = ('<b>Seed</b> rewritten <span style="color: blue;">notes</span><br><center><img src="x.png" onerror="y()"></center>'
                  '<script>alert(1)</script><a href="javascript:z()">link</a>')
        html, note = pp.replace_note(STORED, 1, edited)
        self.assertIn('rewritten <span style="color: blue;">notes</span>', note)
        self.assertIn('<center><img src="x.png"/></center>', note)
        for gone in ('onerror', 'alert', 'javascript'):
            self.assertNotIn(gone, html)
        self.assertIn('<template data-media="2">', html)  # the other media item untouched
        self.assertIn('src="a.jpg"', html)                # the image beside the notes untouched
        self.assertEqual(html.split('<div class="pp-media-store"')[0], STORED.split('<div class="pp-media-store"')[0])

    def test_media_without_notes(self):
        with self.assertRaises(LookupError):
            pp.replace_note(STORED, 2, 'x')  # a bare video: no .tooltip
        with self.assertRaises(LookupError):
            pp.replace_note(STORED, 7, 'x')

    @mock.patch.object(api.transaction, 'atomic', mock.MagicMock())
    def test_endpoint(self):
        factory = RequestFactory()
        row = SimpleNamespace(html=STORED, book='John', chapter=1, save=mock.Mock())
        uid = '00000000-0000-0000-0000-000000000001'

        def post(payload, user=None):
            request = factory.post('/x/', data=json.dumps(payload), content_type='application/json')
            request.user = user or staff()
            return api.edit_note(request)

        self.assertEqual(post({'uid': uid, 'n': 1, 'html': 'x', 'base_hash': 'h'}, user=staff(False)).status_code, 403)
        self.assertEqual(post({'uid': uid, 'n': '1', 'html': 'x', 'base_hash': 'h'}).status_code, 400)
        with mock.patch.object(api.ChapterParaphrase.objects, 'select_for_update') as select:
            select.return_value.filter.return_value.first.return_value = row
            self.assertEqual(post({'uid': uid, 'n': 1, 'html': 'x', 'base_hash': 'stale'}).status_code, 409)
            row.save.assert_not_called()
            good = post({'uid': uid, 'n': 1, 'html': 'New notes', 'base_hash': pp.html_hash(STORED)})
            self.assertEqual(good.status_code, 200)
            data = json.loads(good.content)
            self.assertEqual(data['html'], 'New notes')
            self.assertEqual(data['hash'], pp.html_hash(row.html))
            self.assertEqual(post({'uid': uid, 'n': 2, 'html': 'x', 'base_hash': pp.html_hash(row.html)}).status_code, 400)
