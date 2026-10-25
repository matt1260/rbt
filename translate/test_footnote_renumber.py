from django.test import SimpleTestCase

from translate.footnote_renumber import numbering, renumber_links


def marker(ch, vs, ref, book='Mat', amp='&amp;', sup=None):
    return (f'<a class="sdfootnoteanc" href="?footnote={ch}-{vs}-{ref}{amp}book={book}" target="_blank">'
            f'<sup>{ref if sup is None else sup}</sup></a>')


class NumberingTests(SimpleTestCase):
    def test_linked_in_reading_order_then_unlinked_in_natural_order(self):
        mapping = numbering(['4b', '5', '7c', '6'], {'4b', '5', '6', '7c', '10', '2', '9a', 'xx'})
        self.assertEqual(mapping, {'4b': '1', '5': '2', '7c': '3', '6': '4', '2': '5', '9a': '6', '10': '7', 'xx': '8'})

    def test_links_to_missing_notes_keep_their_place(self):
        self.assertEqual(numbering(['3', '99', '4'], {'3', '4'}), {'3': '1', '99': '2', '4': '3'})


class RenumberLinksTests(SimpleTestCase):
    def test_marker_gets_new_number_in_link_and_sup(self):
        html, moved = renumber_links(f'Text{marker(2, 4, "8a")} more.', 'Mat', {'8a': '9'}, 2, 4)
        self.assertEqual(html, f'Text{marker(2, 4, "9")} more.')
        self.assertEqual(moved, [])

    def test_swapped_numbers_are_not_renumbered_twice(self):
        html, _ = renumber_links(marker(1, 1, '9') + marker(1, 1, '8'), 'Mat', {'9': '8', '8': '9'}, 1, 1)
        self.assertEqual(html, marker(1, 1, '8') + marker(1, 1, '9'))

    def test_plain_ampersand_is_kept(self):
        html, _ = renumber_links(marker(1, 1, '3', amp='&'), 'Mat', {'3': '1'}, 1, 1)
        self.assertEqual(html, marker(1, 1, '1', amp='&'))

    def test_marker_naming_another_verse_gets_its_own(self):
        html, moved = renumber_links(marker(1, 20, '4c'), 'Mat', {'4c': '6'}, 1, 19)
        self.assertEqual(html, marker(1, 19, '6'))
        self.assertEqual(moved, [('1:20', '4c')])

    def test_wrong_sup_text_is_corrected(self):
        html, _ = renumber_links(marker(23, 2, '82', book='Luk', sup='84'), 'Luk', {'82': '115'}, 23, 2)
        self.assertEqual(html, marker(23, 2, '115', book='Luk'))

    def test_cross_reference_link_keeps_text_and_verse(self):
        src = '<a href="https://read.realbible.tech/?footnote=4-18-20&amp;book=Luk" target="_blank">Footnote - A Crushed Wind</a>'
        html, moved = renumber_links(src, 'Luk', {'20': '21'}, 9, 9)
        self.assertEqual(html, src.replace('4-18-20', '4-18-21'))
        self.assertEqual(moved, [])

    def test_link_that_is_not_just_a_sup_keeps_its_text(self):
        src = '<a class="sdfootnoteanc" href="?footnote=10-11-49&amp;book=Act" target="_blank">cf. ἀρχαῖς</a>'
        html, _ = renumber_links(src, 'Act', {'49': '50'}, 10, 11)
        self.assertEqual(html, src.replace('10-11-49', '10-11-50'))

    def test_other_books_and_unknown_refs_are_left_alone(self):
        src = marker(1, 1, '3', book='Mar') + marker(1, 1, '7')
        html, _ = renumber_links(src, 'Mat', {'3': '1'}, 1, 1)
        self.assertEqual(html, src)

    def test_bare_link_outside_an_anchor(self):
        html, _ = renumber_links('see ?footnote=2-1-5&amp;book=Gal here', 'Gal', {'5': '2'}, 4, 24)
        self.assertEqual(html, 'see ?footnote=2-1-2&amp;book=Gal here')

    def test_other_html_is_untouched(self):
        src = '<h5>Head</h5><p>A <a href="/x">link</a> and <abbr>abbr</abbr>.</p>' + marker(3, 3, '12b')
        html, _ = renumber_links(src, 'Mat', {'12b': '37'}, 3, 3)
        self.assertEqual(html, src.replace(marker(3, 3, '12b'), marker(3, 3, '37')))
