import re
import json
from typing import Optional
from bs4 import BeautifulSoup
from django.urls import reverse
from translate.translator import book_abbreviations

# Languages published in the sitemap and cross-linked with rel="alternate" hreflang.
# sitemaps.py, the context processor and base.html must all agree on this list, or
# Google sees the translations as duplicates instead of as an hreflang cluster.
SEO_LANGUAGES = ['es', 'pt', 'fr', 'de', 'ru', 'zh', 'ar', 'hi', 'ja', 'it']

# BCP-47 tags for the hreflang attribute (Google matches on these, not on our
# internal two-letter codes).
HREFLANG_TAGS = {
    'es': 'es',
    'pt': 'pt',
    'fr': 'fr',
    'de': 'de',
    'ru': 'ru',
    'zh': 'zh-Hans',
    'zh-TW': 'zh-Hant',
    'ar': 'ar',
    'hi': 'hi',
    'ja': 'ja',
    'it': 'it',
}

# Languages written right-to-left, for the <html dir> attribute.
RTL_LANGUAGES = {'ar', 'he', 'fa', 'ur'}


def hreflang_for(lang_code: str) -> str:
    return HREFLANG_TAGS.get(lang_code, lang_code)

class BookSlugConverter:
    """Convert between book names (full/alternate formats/abbreviations) and URL slugs."""
    
    def __init__(self):
        self._abbrev_to_name = {}  # e.g., 'Gen' -> 'Genesis'
        self._slug_to_name = {}    # e.g., 'genesis' -> 'Genesis'
        
        # Build reverse mappings
        for name, abbrev in book_abbreviations.items():
            if abbrev not in self._abbrev_to_name:
                canonical = self._to_canonical(name)
                self._abbrev_to_name[abbrev] = canonical
                self._slug_to_name[canonical.lower().replace(' ', '-')] = canonical
    
    @staticmethod
    def _to_canonical(book_name: str) -> str:
        """Normalize book name to canonical form."""
        if '_' in book_name:
            return book_name.replace('_', ' ')
        return re.sub(r'^(\d+)([A-Za-z])', r'\1 \2', book_name)
    
    def to_slug(self, book_name: str) -> Optional[str]:
        if not book_name:
            return None
        if book_name in self._abbrev_to_name:
            return self._abbrev_to_name[book_name].lower().replace(' ', '-')
        canonical = self._to_canonical(book_name)
        if canonical in self._abbrev_to_name.values():
            return canonical.lower().replace(' ', '-')
        if book_name in book_abbreviations:
            abbrev = book_abbreviations[book_name]
            return self._abbrev_to_name[abbrev].lower().replace(' ', '-')
        return None
    
    def from_slug(self, slug: str) -> Optional[str]:
        if not slug:
            return None
        return self._slug_to_name.get(slug.lower())

_converter = BookSlugConverter()

def book_to_slug(book_name: str) -> Optional[str]:
    return _converter.to_slug(book_name)

def slug_to_book(slug: str) -> Optional[str]:
    return _converter.from_slug(slug)

def chapter_url(request, book_name: str, chapter_num, language: str = None) -> str:
    """Absolute URL of a chapter page, matching the page's own canonical tag.

    `book_name` must be an English book name -- a translated display name such as
    "In the Head" has no slug and would fall back to a query-string URL that no
    longer resolves.
    """
    slug = book_to_slug(book_name)
    if not slug:
        return request.build_absolute_uri('/')
    if language and language != 'en':
        return request.build_absolute_uri(reverse(
            'chapter_seo_view_lang',
            kwargs={'lang_code': language, 'book_slug': slug, 'chapter': chapter_num},
        ))
    return request.build_absolute_uri(reverse(
        'chapter_seo_view', kwargs={'book_slug': slug, 'chapter': chapter_num}
    ))


def generate_chapter_schema(request, book_name: str, chapter_num: int, footnotes: dict,
                            url_book: str = None, language: str = None) -> str:
    """Build the JSON-LD for a chapter page.

    `book_name` is the display name (may be translated); `url_book` is the English
    name used to build URLs, so that every `item`/`url` in the schema points at the
    same address as the page's canonical tag.
    """
    url = chapter_url(request, url_book or book_name, chapter_num, language)

    schemas = []

    schemas.append({
        "@context": "https://schema.org",
        "@type": "BreadcrumbList",
        "itemListElement": [
            {
                "@type": "ListItem",
                "position": 1,
                "name": "Bible",
                "item": request.build_absolute_uri('/')
            },
            {
                "@type": "ListItem",
                "position": 2,
                "name": f"{book_name} {chapter_num}",
                "item": url
            }
        ]
    })

    schemas.append({
        "@context": "https://schema.org",
        "@type": "Article",
        "headline": f"{book_name} {chapter_num} | Original Translation",
        "url": url,
        "publisher": {
            "@type": "Organization",
            "name": "Real Bible Translation Project",
            "url": request.build_absolute_uri('/')
        }
    })

    if footnotes:
        faq_items = []
        for f_id, f_data in list(footnotes.items())[:5]:
            try:
                clean_text = BeautifulSoup(f_data.get('content', ''), "html.parser").get_text(separator=" ").strip()
            except Exception:
                clean_text = str(f_data.get('content', ''))
                
            if clean_text:
                faq_items.append({
                    "@type": "Question",
                    "name": f"What is the meaning of the footnote in {book_name} {chapter_num}:{f_data.get('verse', '')}?",
                    "acceptedAnswer": {
                        "@type": "Answer",
                        "text": clean_text
                    }
                })
        
        if faq_items:
            schemas.append({
                "@context": "https://schema.org",
                "@type": "FAQPage",
                "mainEntity": faq_items
            })

    return json.dumps(schemas).replace('</', '<\\/')


def _get_verse_url(language, book, chapter_num, verse):
    from django.urls import reverse
    slug = book_to_slug(book)
    if not slug:
        return f"?book={book}&chapter={chapter_num}&verse={verse}"
    try:
        if language and language != 'en':
            return reverse('verse_seo_view_lang', kwargs={'lang_code': language, 'book_slug': slug, 'chapter': chapter_num, 'verse': str(verse)})
        return reverse('verse_seo_view', kwargs={'book_slug': slug, 'chapter': chapter_num, 'verse': str(verse)})
    except Exception:
        return f"?book={book}&chapter={chapter_num}&verse={verse}"
