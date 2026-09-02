from django.contrib.sitemaps import Sitemap
from django.urls import reverse

from lexicon.views import _all_dictionary_words


class LexiconWordSitemap(Sitemap):
    changefreq = "monthly"
    priority = 0.6
    protocol = "https"

    def items(self):
        return _all_dictionary_words()

    def location(self, item):
        return reverse('lexicon_word_detail', kwargs={'strongs': item['slug']})
