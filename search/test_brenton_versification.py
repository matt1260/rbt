"""The Brenton column follows the Septuagint's numbering (search/brenton_versification.py)."""
from django.test import SimpleTestCase

from search.brenton_versification import brenton_label, brenton_reference


class BrentonReferenceTests(SimpleTestCase):
    def ref(self, book, chapter, verse, default):
        return brenton_reference(book, chapter, verse, default)

    def test_psalms_follow_the_septuagint_numbering(self):
        self.assertEqual(self.ref('Psalms', 82, 6, 'PSA'), ('PSA', '81', '6'))   # "Ye are gods"
        self.assertEqual(self.ref('Psalms', 82, 1, 'PSA'), ('PSA', '81', '1'))
        self.assertEqual(self.ref('Psalms', 10, 1, 'PSA'), ('PSA', '9', '22'))   # 9-10 are one psalm
        self.assertEqual(self.ref('Psalms', 115, 9, 'PSA'), ('PSA', '113', '17'))  # an unmarked run
        self.assertEqual(self.ref('Psalms', 116, 10, 'PSA'), ('PSA', '115', '1'))
        self.assertEqual(self.ref('Psalms', 147, 12, 'PSA'), ('PSA', '147', '1'))
        self.assertEqual(self.ref('Psalms', 8, 6, 'PSA'), ('PSA', '8', '6'))     # same numbers

    def test_exodus_22_reader_uses_english_numbers(self):
        self.assertEqual(self.ref('Exodus', 22, 1, 'EXO'), ('EXO', '21', '37'))
        self.assertEqual(self.ref('Exodus', 22, 9, 'EXO'), ('EXO', '22', '8'))
        self.assertEqual(self.ref('Exodus', 22, 28, 'EXO'), ('EXO', '22', '27'))  # "revile the gods"
        self.assertEqual(self.ref('Exodus', 20, 16, 'EXO'), ('EXO', '20', '16'))  # after the reordered commandments

    def test_brenton_edition_shifts(self):
        self.assertEqual(self.ref('Malachi', 4, 4, 'MAL'), ('MAL', '4', '6'))     # "Remember the law of Moses"
        self.assertEqual(self.ref('Proverbs', 30, 1, 'PRO'), ('PRO', '24', '22f'))
        self.assertEqual(self.ref('Proverbs', 31, 1, 'PRO'), ('PRO', '24', '54'))
        self.assertEqual(self.ref('Nehemiah', 1, 1, None), ('EZR', '11', '1'))   # 2 Esdras 11
        self.assertEqual(self.ref('Daniel', 4, 1, 'DAG'), ('DAG', '4', '4'))

    def test_rearranged_and_missing_verses(self):
        self.assertEqual(self.ref('Jeremiah', 25, 15, 'JER'), ('JER', '32', '15'))
        self.assertEqual(self.ref('Jeremiah', 39, 3, 'JER'), ('JER', '46', '3'))
        self.assertIsNone(self.ref('Jeremiah', 33, 15, 'JER'))  # not in the Septuagint

    def test_catss_division_quirks_keep_the_reader_numbers(self):
        self.assertEqual(self.ref('Joshua', 22, 22, 'JOS'), ('JOS', '22', '22'))
        self.assertEqual(self.ref('Lamentations', 1, 20, 'LAM'), ('LAM', '1', '20'))
        self.assertEqual(self.ref('Genesis', 1, 1, 'GEN'), ('GEN', '1', '1'))

    def test_unknown_books_and_bad_numbers(self):
        self.assertIsNone(self.ref('John', 1, 1, None))
        self.assertEqual(self.ref('Genesis', '1', '1', 'GEN'), ('GEN', '1', '1'))
        self.assertEqual(self.ref('Genesis', 'x', '1', 'GEN'), ('GEN', 'x', '1'))

    def test_label_names_a_different_reference(self):
        self.assertEqual(brenton_label('Psalms', ('PSA', '81', '6'), 'PSA', 82, 6), '81:6')
        self.assertEqual(brenton_label('Nehemiah', ('EZR', '11', '1'), None, 1, 1), '2 Esdras 11:1')
        self.assertEqual(brenton_label('Genesis', ('GEN', '1', '1'), 'GEN', '1', '1'), '')
