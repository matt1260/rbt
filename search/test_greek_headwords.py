"""NT interlinear words link to their Logeion headword, and words in ‹ › are flagged
(search/greek_headwords.py, search/data/greek_logeion_headwords.json)."""
from unittest import mock

from django.test import SimpleTestCase

from search.greek_headwords import logeion_headword, logeion_url, perseus_morph_url, plain_word


class LogeionHeadwordTests(SimpleTestCase):
    def test_inflected_words_link_to_their_headword(self):
        self.assertEqual(logeion_headword('Rom.14.21-05', '2907', 'κρέα'), 'κρέας')    # meat, pl.
        self.assertEqual(logeion_headword('Mat.1.2-03', '3588', 'τὸν'), 'ὁ')
        self.assertEqual(logeion_headword('Mat.1.23-20', '1473', 'ἡμῶν'), 'ἐγώ')
        self.assertEqual(logeion_headword('Mat.2.2-18', '2064', 'ἤλθομεν'), 'ἔρχομαι')

    def test_strongs_spellings_that_logeion_files_elsewhere(self):
        self.assertEqual(logeion_headword('X', '2036', 'εἶπεν'), 'λέγω')      # Strong's: ἔπω
        self.assertEqual(logeion_headword('X', '730', 'ἄρσεν'), 'ἄρσην')      # Strong's: ἄῤῥην
        self.assertEqual(logeion_headword('X', '1163', 'δεῖ'), 'δεῖ')         # not δέω "bind"

    def test_word_level_corrections(self):
        # Readings with no Strong's number of their own keep the TR word's number.
        self.assertEqual(logeion_headword('2Pe.2.17-06', '887', 'ὁμίχλαι'), 'ὀμίχλη')       # ἀχλύς
        self.assertEqual(logeion_headword('Mar.14.31-03', '4057', 'ἐκπερισσῶς'), 'ἐκπερισσῶς')
        # Mis-tagged numbers corrected in the data (δύο was 5140 τρεῖς, ἐγώ was 1510 εἰμί).
        self.assertEqual(logeion_headword('Act.10.19-14', '1417', 'δύο'), 'δύο')
        self.assertEqual(logeion_headword('Joh.3.28-07', '1473', 'ἐγώ'), 'ἐγώ')

    def test_unknown_number_falls_back_to_the_plain_word(self):
        self.assertEqual(logeion_headword('X', '999999', '‹λόγος›'), 'λόγος')

    def test_urls_are_encoded(self):
        self.assertEqual(logeion_url('κρέας'), 'https://logeion.uchicago.edu/%CE%BA%CF%81%CE%AD%CE%B1%CF%82')
        self.assertTrue(logeion_url('Ἄρειος Πάγος').endswith('%20%CE%A0%CE%AC%CE%B3%CE%BF%CF%82'))
        self.assertNotIn('‹', perseus_morph_url(plain_word('‹καὶ›')))

    def test_marks_are_stripped(self):
        self.assertEqual(plain_word('‹πρὸς'), 'πρὸς')
        self.assertEqual(plain_word('μή¦γε'), 'μήγε')
        self.assertEqual(plain_word('ὑμᾶς⧽'), 'ὑμᾶς')


class InterlinearRenderTests(SimpleTestCase):
    """The verse page and the NT editor share the interlinear HTML built in get_results."""

    def test_rows_carry_headword_and_variant(self):
        from search.views import chapter_views_part1 as views
        rows = [
            ('Act.2.44-03', '3588', 'hoi', 'οἱ', 'the', 'Art-NMP', 'Article'),
            ('Act.2.44-04', '4100', 'pisteuontes', '‹πιστεύοντες', 'trusting', 'V-PPA-NMP', 'Verb'),
        ]
        with mock.patch.object(views, 'execute_query', return_value=rows), \
                mock.patch.object(views, 'replace_words', side_effect=lambda s, l, e: (s, l, e)):
            words = views.fetch_greek_interlinear_rows('Acts', 2, 44)
        self.assertEqual([w['logeion'] for w in words], ['ὁ', 'πιστεύω'])
        self.assertIsNone(words[0]['variant'])
        self.assertIn('the RBT text has πιστεύσαντες', words[1]['variant'])
