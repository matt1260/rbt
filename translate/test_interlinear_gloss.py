"""
Interlinear Greek gloss lookup and inline gloss edits. A Strong's-number key in the
InterlinearConfig mapping must not override one specific form's own key, and an
inline edit of one form must not change the others. DB access is mocked:

    python manage.py test translate.test_interlinear_gloss
"""
import json
from types import SimpleNamespace
from unittest import mock

from django.test import RequestFactory, SimpleTestCase

from translate import views
from translate.translator import resolve_interlinear_gloss


# Key order as Postgres JSONB returns it: shortest keys first, so '444' leads.
MAPPING = {
    '444': 'humans',
    'ἀνθρώπῳ': 'human',
    'ἀνθρώποις': 'humans',
}


class ResolveInterlinearGlossTests(SimpleTestCase):
    def test_form_key_beats_strongs_key(self):
        self.assertEqual(resolve_interlinear_gloss(MAPPING, '444', 'ἀνθρώπῳ', 'db'), 'human')
        self.assertEqual(resolve_interlinear_gloss(MAPPING, '444', 'ἀνθρώποις', 'db'), 'humans')

    def test_strongs_key_covers_forms_without_their_own_key(self):
        self.assertEqual(resolve_interlinear_gloss(MAPPING, '444', 'ἄνθρωποι', 'db'), 'humans')

    def test_no_match_keeps_stored_english(self):
        self.assertEqual(resolve_interlinear_gloss(MAPPING, '2316', 'θεοῦ', 'God'), 'God')
        self.assertEqual(resolve_interlinear_gloss(MAPPING, None, None, 'x'), 'x')


class UpdateInterlinearWordTests(SimpleTestCase):
    def post(self, payload, config):
        request = RequestFactory().post(
            '/translate/api/update-interlinear-word/',
            data=json.dumps(payload),
            content_type='application/json',
        )
        request.user = SimpleNamespace(is_authenticated=True, username='editor')

        cursor = mock.MagicMock()
        cursor.fetchone.return_value = ('humans',)
        conn = mock.MagicMock()
        conn.cursor.return_value = cursor
        db = mock.MagicMock()
        db.return_value.__enter__.return_value = conn

        model = mock.MagicMock()
        model.objects.order_by.return_value.first.return_value = config
        with mock.patch.object(views, 'get_db_connection', db), \
                mock.patch('search.models.InterlinearConfig', model), \
                mock.patch.object(views, 'connection'), \
                mock.patch('builtins.open', mock.mock_open()):
            response = views.update_interlinear_word(request)
        return response, cursor

    def test_editing_one_form_leaves_strongs_key_alone(self):
        config = SimpleNamespace(mapping=dict(MAPPING), save=mock.Mock())
        response, cursor = self.post(
            {'strongs': '444', 'lemma': 'ἀνθρώπῳ', 'new_english': 'a human'}, config
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(config.mapping['ἀνθρώπῳ'], 'a human')
        self.assertEqual(config.mapping['444'], 'humans')
        self.assertEqual(config.mapping['ἀνθρώποις'], 'humans')
        config.save.assert_called_once()
        cursor.execute.assert_any_call(
            "UPDATE rbt_greek.strongs_greek SET english = %s WHERE strongs = %s AND lemma = %s",
            ('a human', '444', 'ἀνθρώπῳ'),
        )
