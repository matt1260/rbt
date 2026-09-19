"""
Tests for the inline chapter editor endpoints (translate/chapter_editor_api.py) and the
shared NT save helper. DB access is mocked, so these run without a test database:

    python manage.py test translate
"""
import json
from datetime import datetime, timedelta
from types import SimpleNamespace
from unittest import mock

from django.http import HttpResponse
from django.middleware.csrf import CsrfViewMiddleware
from django.test import RequestFactory, SimpleTestCase

from translate import chapter_editor_api as api
from translate import views


def make_user(staff=True, authenticated=True):
    return SimpleNamespace(is_authenticated=authenticated, is_staff=staff, username='editor')


def verse_hash(html):
    return api._verse_hash(html)


class ChapterEditorApiTests(SimpleTestCase):
    def setUp(self):
        self.factory = RequestFactory()

    def post_verse(self, payload, user=None):
        request = self.factory.post('/translate/api/chapter-editor/verse/', data=json.dumps(payload), content_type='application/json')
        request.user = user or make_user()
        return api.save_verse(request)

    # --- permissions -------------------------------------------------------

    def test_endpoints_reject_anonymous_and_non_staff(self):
        for user in (make_user(staff=False, authenticated=False), make_user(staff=False)):
            request = self.factory.get('/x/', {'book': 'John', 'chapter': '1'})
            request.user = user
            self.assertEqual(api.chapter(request).status_code, 403)

            request = self.factory.get('/x/', {'book': 'John', 'chapter': '1', 'verse': '1'})
            request.user = user
            self.assertEqual(api.interlinear(request).status_code, 403)

            self.assertEqual(self.post_verse({}, user=user).status_code, 403)

    def test_save_requires_csrf_token(self):
        request = self.factory.post('/translate/api/chapter-editor/verse/', data='{}', content_type='application/json')
        request.user = make_user()
        middleware = CsrfViewMiddleware(lambda r: HttpResponse())
        response = middleware.process_view(request, api.save_verse, (), {})
        self.assertIsNotNone(response)
        self.assertEqual(response.status_code, 403)

    # --- chapter -----------------------------------------------------------

    @mock.patch.object(api, 'execute_query')
    def test_chapter_returns_verses_with_hashes(self, execute_query):
        execute_query.return_value = [(1, '<b>In</b> the beginning'), (2, None)]
        request = self.factory.get('/x/', {'book': 'John', 'chapter': '1'})
        request.user = make_user()

        data = json.loads(api.chapter(request).content)

        self.assertEqual(execute_query.call_args[0][1], ('Joh', 1))
        self.assertEqual(data['verses'], [
            {'verse': '1', 'html': '<b>In</b> the beginning', 'hash': verse_hash('<b>In</b> the beginning')},
            {'verse': '2', 'html': '', 'hash': verse_hash('')},
        ])

    def test_chapter_rejects_non_nt_books(self):
        request = self.factory.get('/x/', {'book': 'Exodus', 'chapter': '1'})
        request.user = make_user()
        self.assertEqual(api.chapter(request).status_code, 400)

    # --- save --------------------------------------------------------------

    @mock.patch.object(api, 'save_nt_verse_html')
    @mock.patch.object(api, 'execute_query')
    def test_save_writes_and_returns_new_hash(self, execute_query, save_nt_verse_html):
        execute_query.return_value = ('JOH-1-1', 'old text')
        new_html = 'new <span style="color: blue;">text</span>'

        response = self.post_verse({'book': 'John', 'chapter': 1, 'verse': 1, 'html': new_html, 'base_hash': verse_hash('old text')})

        self.assertEqual(response.status_code, 200)
        self.assertEqual(json.loads(response.content), {'hash': verse_hash(new_html), 'saved': True})
        save_nt_verse_html.assert_called_once_with('JOH-1-1', new_html, 'John', 1, 1, coalesce_seconds=api.LOG_COALESCE_SECONDS)

    @mock.patch.object(api, 'save_nt_verse_html')
    @mock.patch.object(api, 'execute_query')
    def test_save_with_stale_hash_is_a_conflict(self, execute_query, save_nt_verse_html):
        execute_query.return_value = ('JOH-1-1', 'edited on the verse page')

        response = self.post_verse({'book': 'John', 'chapter': 1, 'verse': 1, 'html': 'mine', 'base_hash': verse_hash('old text')})

        self.assertEqual(response.status_code, 409)
        self.assertEqual(json.loads(response.content)['html'], 'edited on the verse page')
        save_nt_verse_html.assert_not_called()

    @mock.patch.object(api, 'save_nt_verse_html')
    @mock.patch.object(api, 'execute_query')
    def test_unchanged_save_is_a_no_op(self, execute_query, save_nt_verse_html):
        execute_query.return_value = ('JOH-1-1', 'same')

        response = self.post_verse({'book': 'John', 'chapter': 1, 'verse': 1, 'html': 'same', 'base_hash': verse_hash('same')})

        self.assertEqual(json.loads(response.content)['saved'], False)
        save_nt_verse_html.assert_not_called()

    @mock.patch.object(api, 'save_nt_verse_html')
    @mock.patch.object(api, 'execute_query')
    def test_save_strips_editor_artifacts(self, execute_query, save_nt_verse_html):
        execute_query.return_value = ('JOH-1-1', 'old')
        html = '<span contenteditable="false">x</span><br class="ProseMirror-trailingBreak">'

        self.post_verse({'book': 'John', 'chapter': 1, 'verse': 1, 'html': html, 'base_hash': verse_hash('old')})

        self.assertEqual(save_nt_verse_html.call_args[0][1], '<span>x</span>')

    def test_save_validates_input(self):
        base = {'book': 'John', 'chapter': 1, 'verse': 1, 'html': 'x', 'base_hash': 'h'}
        for bad in ({**base, 'book': 'Genesis'}, {**base, 'verse': 'one'}, {**base, 'html': None}, {**base, 'html': 'x' * (api.MAX_VERSE_HTML_LENGTH + 1)}):
            self.assertEqual(self.post_verse(bad).status_code, 400, bad)

    # --- interlinear ---------------------------------------------------------

    @mock.patch.object(api, 'fetch_greek_interlinear_rows')
    def test_interlinear_returns_display_fields(self, fetch_rows):
        fetch_rows.return_value = [{
            'strongs': 'G3056', 'translit': 'logos', 'lemma': 'λόγος', 'english': 'Word',
            'morph': 'N-NSM', 'morph_desc': 'Noun Nominative Singular Masculine',
            'raw_lemma': 'λόγος', 'raw_english': 'word',
        }]
        request = self.factory.get('/x/', {'book': 'John', 'chapter': '1', 'verse': '1'})
        request.user = make_user()

        words = json.loads(api.interlinear(request).content)['words']

        fetch_rows.assert_called_once_with('John', 1, 1)
        self.assertEqual(words, [{
            'strongs': 'G3056', 'translit': 'logos', 'lemma': 'λόγος', 'english': 'Word',
            'morph': 'N-NSM', 'morph_desc': 'Noun Nominative Singular Masculine',
        }])


@mock.patch.object(views, '_invalidate_reader_cache', return_value=['k1'])
@mock.patch.object(views, 'execute_query')
@mock.patch.object(views, 'TranslationUpdates')
class SaveNtVerseHtmlTests(SimpleTestCase):
    def test_writes_logs_and_clears_cache(self, updates, execute_query, invalidate):
        updates.objects.filter.return_value.order_by.return_value.first.return_value = None

        cleared = views.save_nt_verse_html('JOH-1-1', '<a href="?footnote=1">x</a> y', 'John', 1, 1)

        execute_query.assert_called_once_with("UPDATE new_testament.nt SET rbt = %s WHERE verseID = %s", ('<a href="?footnote=1">x</a> y', 'JOH-1-1'))
        kwargs = updates.call_args.kwargs
        self.assertEqual((kwargs['version'], kwargs['reference'], kwargs['update_text']), ('New Testament', 'John 1:1', 'x y'))
        invalidate.assert_called_once_with('John', 1, 1)
        self.assertEqual(cleared, ['k1'])

    def test_coalesces_recent_log_row(self, updates, execute_query, invalidate):
        recent = SimpleNamespace(date=datetime.now() - timedelta(minutes=2))
        updates.objects.filter.return_value.order_by.return_value.first.return_value = recent

        views.save_nt_verse_html('JOH-1-1', 'second edit', 'John', 1, 1, coalesce_seconds=600)

        updates.assert_not_called()  # no new row
        updates.objects.filter.assert_called_with(date=recent.date)
        updates.objects.filter.return_value.update.assert_called_once_with(update_text='second edit')
