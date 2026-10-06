"""
Tests for the inline editor's footnote endpoint (translate/chapter_editor_api.py footnote).
The database is mocked:

    python manage.py test translate.test_chapter_editor_footnote
"""
import json
from types import SimpleNamespace
from unittest import mock

from django.test import RequestFactory, SimpleTestCase

from translate import chapter_editor_api as api

STORED = '<p class="rbt_footnote">Old note.</p>'


def staff(is_staff=True):
    return SimpleNamespace(is_authenticated=True, is_staff=is_staff, username='editor')


class FootnoteEndpointTests(SimpleTestCase):
    def setUp(self):
        self.factory = RequestFactory()
        self.queries = []
        stored = {'html': STORED}

        def execute_query(sql, params, fetch=None):
            self.queries.append((sql, params))
            if sql.startswith('SELECT'):
                return (stored['html'],) if params == ('Joh-70a',) else None
            stored['html'] = params[0]
            return None

        for target, value in (('execute_query', execute_query), ('_safe_save_update', mock.Mock()),
                              ('_invalidate_reader_cache', mock.Mock())):
            patcher = mock.patch.object(api, target, value)
            self.addCleanup(patcher.stop)
            setattr(self, target, patcher.start())

    def get(self, **params):
        request = self.factory.get('/x/', params)
        request.user = staff()
        return api.footnote(request)

    def post(self, payload, user=None):
        request = self.factory.post('/x/', data=json.dumps(payload), content_type='application/json')
        request.user = user or staff()
        return api.footnote(request)

    def test_reads_the_stored_footnote(self):
        data = json.loads(self.get(book='John', ref='70a').content)
        self.assertEqual(data['html'], STORED)
        self.assertEqual(self.queries[0], ('SELECT footnote_html FROM new_testament.joh_footnotes WHERE footnote_id = %s', ('Joh-70a',)))
        self.assertEqual(self.get(book='John', ref='99').status_code, 404)
        self.assertEqual(self.get(book='Genesis', ref='70a').status_code, 400)        # NT only
        self.assertEqual(self.get(book='John', ref='1; DROP').status_code, 400)

    def test_saves_normalised_html_and_logs_it(self):
        base = api._verse_hash(STORED)
        response = self.post({'book': 'John', 'chapter': 2, 'verse': 5, 'ref': '70a', 'base_hash': base,
                              'html': '<p data-start="3">New <span style="color: blue;">note</span>.</p>'})
        self.assertEqual(response.status_code, 200)
        data = json.loads(response.content)
        self.assertEqual(data['html'], '<p class="rbt_footnote">New <span style="color: blue;">note</span>.</p>')
        self.assertEqual(data['hash'], api._verse_hash(data['html']))
        self.assertIn(('UPDATE new_testament.joh_footnotes SET footnote_html = %s WHERE footnote_id = %s', (data['html'], 'Joh-70a')), self.queries)
        self.assertEqual(self._safe_save_update.call_args[0][0].reference, 'John 2:5 - Joh-70a')
        self._invalidate_reader_cache.assert_called_once_with('John', 2, 5)

    def test_conflict_and_permissions(self):
        stale = self.post({'book': 'John', 'chapter': 2, 'verse': 5, 'ref': '70a', 'base_hash': 'old', 'html': '<p>x</p>'})
        self.assertEqual(stale.status_code, 409)
        self.assertEqual(json.loads(stale.content)['html'], STORED)
        self.assertFalse(any(sql.startswith('UPDATE') for sql, _ in self.queries))
        self.assertEqual(self.post({'book': 'John', 'ref': '70a'}, user=staff(False)).status_code, 403)
        self.assertEqual(self.post({'book': 'John', 'chapter': 2, 'verse': 5, 'ref': '70a', 'html': 'x'}).status_code, 400)

    def test_unchanged_save_writes_nothing(self):
        response = self.post({'book': 'John', 'chapter': 2, 'verse': 5, 'ref': '70a', 'base_hash': api._verse_hash(STORED), 'html': STORED})
        self.assertEqual(response.status_code, 200)
        self.assertFalse(any(sql.startswith('UPDATE') for sql, _ in self.queries))
        self._invalidate_reader_cache.assert_not_called()
