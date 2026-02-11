import re
from django.test import TestCase

from translate.views import _build_nt_search_pattern


class FindReplaceNTTests(TestCase):
    def test_html_find_and_replace_literal(self):
        find_text = '<span style="color: blue;"><span style="color: blue;">the Old Men</span></span>'
        replace_text = '<span style="color: blue;">the Old Men</span>'
        old_text = f'Beginning {find_text} end.'

        # Build pattern in HTML mode (no word boundaries)
        pattern = _build_nt_search_pattern(find_text, exact=False, allow_html=True)
        compiled = re.compile(pattern)

        assert compiled.search(old_text)
        new_text = compiled.sub(lambda m: replace_text, old_text)
        assert replace_text in new_text
        assert find_text not in new_text

    def test_exact_match_without_html_mode_uses_word_boundary(self):
        find_text = 'Old'
        pattern = _build_nt_search_pattern(find_text, exact=True, allow_html=False)
        assert pattern.startswith('\\b') and pattern.endswith('\\b')
