from django.test import SimpleTestCase

from translate.footnote_cleanup import normalize, normalize_html, visible_text


class NormalizeFootnoteTests(SimpleTestCase):
    def assertClean(self, before, after):
        result = normalize(before)
        self.assertEqual(result.html, after)
        self.assertFalse(result.text_changed)
        # A second pass never changes anything more.
        self.assertEqual(normalize(result.html).html, after)

    def test_old_span_class_and_new_p_class_end_up_the_same(self):
        self.assertClean('<p><span class="rbt_footnote">Old style.</span></p>', '<p>Old style.</p>')
        self.assertClean('<p class="rbt_footnote">New style.</p>', '<p>New style.</p>')
        self.assertClean('<ul class="rbt_footnote"><li class="rbt_footnote">Item</li></ul>', '<ul><li>Item</li></ul>')

    def test_empty_header_from_the_add_form_is_removed_but_a_real_one_kept(self):
        self.assertClean('<p><span class="footnote_header"></span></p> <p class="rbt_footnote">Body.</p>', '<p>Body.</p>')
        self.assertClean('<p><span class="footnote_header">Title<br/></span></p> <p>Body.</p>',
                         '<p><span class="footnote_header">Title</span></p>\n<p>Body.</p>')

    def test_browser_translation_popup_is_removed(self):
        html = ('<p>Note.</p><div class="simple-translate-system-theme" id="simple-translate"><div>'
                '<div class="simple-translate-panel" style="top: 0px"><p class="simple-translate-result">Nota.</p></div></div></div>')
        self.assertClean(html, '<p>Note.</p>')

    def test_paste_attributes_and_classes_are_dropped(self):
        self.assertClean('<p data-start="1" data-end="9" dir="ltr"><strong data-path-to-node="3">Bold</strong> text</p>',
                         '<p><strong>Bold</strong> text</p>')
        self.assertClean('<div class="flex flex-col w-full"><div class="break-words">Chat answer.</div></div>', '<p>Chat answer.</p>')

    def test_fonts_and_sizes_go_but_meaningful_styles_stay(self):
        self.assertClean('<p style="padding-left: 40px; font-size: 13px;">Indented <span style="color: #ff00aa;">pink</span></p>',
                         '<p style="padding-left: 40px;">Indented <span style="color: #ff00aa;">pink</span></p>')
        self.assertClean('<p>See <span style="font-variant: small-caps;">Pl.</span></p>',
                         '<p>See <span style="font-variant: small-caps;">Pl.</span></p>')

    def test_sized_hebrew_and_fonted_greek_words_get_their_class(self):
        self.assertClean('<p>The word <span style="font-size: 18pt;">התברכו</span> here.</p>',
                         '<p>The word <span class="hebrew">התברכו</span> here.</p>')
        self.assertClean('<p><span style="font-family: \'Times New Roman\',serif;">λόγος</span></p>',
                         '<p><span class="greek">λόγος</span></p>')
        self.assertClean('<p><span class="hebrew_footnote">אמן</span> and <span class="greek2">ἀμήν</span></p>',
                         '<p><span class="hebrew">אמן</span> and <span class="greek">ἀμήν</span></p>')

    def test_b_and_i_become_strong_and_em_but_icons_stay(self):
        self.assertClean('<p><b>B</b> <i>I</i></p>', '<p><strong>B</strong> <em>I</em></p>')
        html = '<div class="tooltip-container"><img src="x.png"/><i class="touch-indicator fas fa-hand-pointer"></i><div class="tooltip">Notes.</div></div>'
        self.assertEqual(normalize_html(html), html)

    def test_loose_text_double_breaks_and_trailing_breaks(self):
        self.assertClean('Loose text <strong>here</strong>.', '<p>Loose text <strong>here</strong>.</p>')
        self.assertClean('<p>One<br/><br/>Two<br/></p>', '<p>One</p>\n<p>Two</p>')
        self.assertClean('<p>Line one<br/>line two</p>', '<p>Line one<br/>line two</p>')

    def test_list_item_paragraphs_and_empty_paragraphs(self):
        self.assertClean('<ul><li><p>Item</p></li></ul><p>&nbsp;</p><p></p>', '<ul><li>Item</li></ul>')

    def test_spacing(self):
        self.assertClean('<p>&nbsp;Too  many\xa0 spaces&nbsp;</p>', '<p>Too many spaces</p>')
        self.assertClean('<p>Keep\xa0this</p>', '<p>Keep\xa0this</p>')

    def test_rendered_maths_is_left_alone_and_flagged(self):
        html = '<p>Formula <span class="katex"><span class="mord mathnormal" style="margin-right: 0.05em;">β</span></span></p>'
        result = normalize(html)
        self.assertIn('<span class="katex"><span class="mord mathnormal" style="margin-right: 0.05em;">β</span></span>', result.html)
        self.assertTrue(any('maths' in r for r in result.review))

    def test_clean_note_is_untouched(self):
        html = '<p><span class="footnote_header">Title</span></p>\n<p>Body with <a href="https://x.org" target="_blank">link</a>.</p>'
        result = normalize(html)
        self.assertFalse(result.changed)
        self.assertEqual(result.html, html)

    def test_visible_text_ignores_extension_junk(self):
        self.assertEqual(visible_text('<p>A</p><div id="simple-translate">B</div>'), 'A')
