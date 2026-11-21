"""Interlinear words the RBT's Greek text lacks are found word by word (search/greek_variants.py)."""
from django.test import SimpleTestCase

from search.greek_variants import (
    compare_texts_url, compare_with_rbt_text, double_bracket_verses, verse_variants,
)


class CompareWithRbtTextTests(SimpleTestCase):
    def compare(self, words, text, prev='', next_=''):
        return compare_with_rbt_text(words.split(), text, prev, next_)

    def test_acts_2_44(self):
        absent, notes = self.compare(
            'Πάντες δὲ οἱ ‹πιστεύοντες ἦσαν› ἐπὶ τὸ αὐτὸ ‹καὶ› εἶχον ἅπαντα κοινά',
            'πάντες δὲ οἱ πιστεύσαντες ἐπὶ τὸ αὐτὸ εἶχον ἅπαντα κοινά,')
        self.assertEqual([i for i, a in enumerate(absent) if a], [3, 4, 8])
        self.assertEqual(notes, [
            'πιστεύοντες ἦσαν: the SBL Greek NT reading; the RBT text has πιστεύσαντες',
            'καὶ: the SBL Greek NT reading; not in the RBT text',
        ])

    def test_spelling_is_not_a_variant(self):
        for ours, theirs in [('Δαυὶδ', 'Δαυείδ'), ('οὕτως', 'οὕτω'), ('ἀπ’', 'ἀπὸ'),
                             ('συμβαλεῖν', 'συνβαλεῖν'), ('τέσσαρα', 'τέσσερα'), ('κεραία', 'κερέα')]:
            absent, notes = self.compare(f'καὶ {ours} λέγει', f'καὶ {theirs} λέγει')
            self.assertEqual(notes, [], ours)

    def test_another_form_is_a_variant(self):
        _absent, notes = self.compare('καὶ ἤκουον αὐτοῦ', 'καὶ ἤκουσεν αὐτοῦ')
        self.assertEqual(len(notes), 1)

    def test_word_order_is_not_a_variant(self):   # Rom 8:14
        _absent, notes = self.compare('οὗτοι υἱοί εἰσιν ⇔ Θεοῦ', 'οὗτοι υἱοὶ θεοῦ εἰσίν.')
        self.assertEqual(notes, [])

    def test_words_of_the_next_verse_are_not_a_variant(self):   # Rom 7:9-10
        _absent, notes = self.compare(
            'ἡ ἁμαρτία ἀνέζησεν ἐγὼ δὲ ἀπέθανον', 'ἡ ἁμαρτία ἀνέζησεν,',
            next_='ἐγὼ δὲ ἀπέθανον, καὶ εὑρέθη μοι')
        self.assertEqual(notes, [])

    def test_verse_missing_from_the_rbt_text(self):   # Acts 8:37
        absent, notes = self.compare('{εἰπε δὲ ὁ Φίλιππος}', '')
        self.assertTrue(all(absent))
        self.assertEqual(notes, ['This verse is not in the RBT Greek text; it comes from the Textus Receptus'])

    def test_differently_numbered_verse_is_left_alone(self):   # Mat 23:13 / 23:14
        absent, notes = self.compare('κλείετε τὴν βασιλείαν τῶν οὐρανῶν ἔμπροσθεν τῶν ἀνθρώπων',
                                     'κατεσθίετε τὰς οἰκίας τῶν χηρῶν καὶ προφάσει μακρὰ προσευχόμενοι')
        self.assertEqual((absent, notes), ([None] * 8, []))


class DoubleBracketTests(SimpleTestCase):
    def test_passage_and_part_of_a_verse(self):
        marked = double_bracket_verses([
            ('Mar.16.8', 'ἐφοβοῦντο γάρ.'),
            ('Mar.16.9', '[[Ἀναστὰς δὲ πρωὶ'),
            ('Mar.16.10', 'ἐκείνη πορευθεῖσα'),
            ('Mar.16.20', 'ἐξελθόντες ἐκήρυξαν.]]'),
            ('Luk.24.6', '[[οὐκ ἔστιν ὧδε, ἀλλὰ ἠγέρθη.]] μνήσθητε ὡς'),
        ])
        self.assertEqual(sorted(marked), ['Luk.24.6', 'Mar.16.10', 'Mar.16.20', 'Mar.16.9'])
        self.assertIn('print this', marked['Mar.16.10'])
        self.assertIn('“οὐκ ἔστιν ὧδε ἀλλὰ ἠγέρθη”', marked['Luk.24.6'])


class TableTests(SimpleTestCase):
    def test_built_table(self):
        entry = verse_variants('Act.2.44')
        self.assertEqual(entry['words'], {'04': 0, '05': 0, '09': 1})
        self.assertIn('Textus Receptus', verse_variants('1Jo.5.7')['notes'][0])
        self.assertIsNone(verse_variants('Rom.7.9'))

    def test_compare_url(self):
        self.assertEqual(compare_texts_url('1 Corinthians', 13, 4),
                         'https://biblehub.com/texts/1_corinthians/13-4.htm')
