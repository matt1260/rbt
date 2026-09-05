import os
import re
import json
from functools import lru_cache
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


_BOOK_NAMES_I18N_PATH = os.path.join(os.path.dirname(__file__), 'data', 'book_names_i18n.json')


@lru_cache(maxsize=1)
def _book_names_i18n():
    """{language: {book_slug: traditional_name}}, extracted from the front-end
    translations bundle. Static data, so it is read once per process."""
    try:
        with open(_BOOK_NAMES_I18N_PATH, encoding='utf-8') as handle:
            return json.load(handle)
    except (OSError, ValueError):
        return {}


def localized_book_name(book_name: str, language: Optional[str]) -> str:
    """The book's traditional name in `language` (pl/3 John -> '3 Jana').

    Titles and descriptions need the name people actually search for, which is
    neither the English name nor the project's poetic RBT title -- a Polish
    reader searches "3 Jana", not "3 John" and not "Trzeci Faworyzowany".
    Falls back to the English name when a translation isn't available.
    """
    fallback = re.sub(r'^(\d+)([A-Za-z])', r'\1 \2', book_name or '')
    if not language or language == 'en' or not book_name:
        return fallback
    slug = book_to_slug(book_name)
    if not slug:
        return fallback
    return _book_names_i18n().get(language, {}).get(slug) or fallback


# A chapter counts as translated into a language only once this much of it is
# actually translated. Below that the page is mostly English fallback text under
# a foreign URL, which is duplicate content rather than a translation worth
# advertising in hreflang or submitting in the sitemap.
MIN_TRANSLATION_COVERAGE = 0.5

_TRANSLATED_CHAPTERS_CACHE_KEY = 'seo_translated_chapters_v1'
_TRANSLATED_CHAPTERS_TTL = 60 * 60 * 6


def translated_chapters():
    """Map {(book_slug, chapter): frozenset(language_codes)} of chapters that
    genuinely have a translation (see MIN_TRANSLATION_COVERAGE).

    Both the hreflang cluster and the sitemap read this, so a language is only
    advertised where translated text actually exists. The previous behaviour
    advertised a fixed 10-language list for every chapter regardless of whether
    a translation existed, while every other language was silently treated as
    English -- which pointed their canonical at the English page.
    """
    from search.db_utils import execute_query, safe_cache_get, safe_cache_set

    cached = safe_cache_get(_TRANSLATED_CHAPTERS_CACHE_KEY)
    if cached is not None:
        return cached

    # `verse > 0` skips footnote rows; the NOT LIKE drops rows the translation
    # worker stored as failures. '%%' is a literal % because params are bound.
    rows = execute_query(
        """
        WITH v AS (
            SELECT book, chapter, language_code, verse
            FROM verse_translations
            WHERE footnote_id IS NULL
              AND verse > 0
              AND COALESCE(TRIM(verse_text), '') <> ''
              AND verse_text NOT LIKE '[Translation%%'
        ),
        len AS (
            SELECT book, chapter, MAX(verse) AS n FROM v GROUP BY book, chapter
        )
        SELECT v.book, v.chapter, v.language_code
        FROM v JOIN len ON len.book = v.book AND len.chapter = v.chapter
        GROUP BY v.book, v.chapter, v.language_code, len.n
        HAVING COUNT(*)::float / NULLIF(len.n, 0) >= %s
        """,
        (MIN_TRANSLATION_COVERAGE,),
        fetch='all',
    ) or []

    index = {}
    for book, chapter, language_code in rows:
        # Normalises the book-name inconsistency in this table ("1 John" vs
        # "1John"); returns None for non-canonical texts (Judas, Aseneth), which
        # have their own routes and no hreflang cluster.
        slug = book_to_slug(book)
        if not slug:
            continue
        try:
            chapter_int = int(chapter)
        except (TypeError, ValueError):
            continue
        index.setdefault((slug, chapter_int), set()).add(language_code)

    index = {key: frozenset(langs) for key, langs in index.items()}
    safe_cache_set(_TRANSLATED_CHAPTERS_CACHE_KEY, index, _TRANSLATED_CHAPTERS_TTL)
    return index


def translated_languages_for(book_slug, chapter):
    """Language codes with a real translation of this chapter."""
    if not book_slug or chapter is None:
        return frozenset()
    try:
        chapter_int = int(chapter)
    except (TypeError, ValueError):
        return frozenset()
    return translated_chapters().get((book_slug, chapter_int), frozenset())

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


def generate_lexicon_schema(request, word: dict) -> str:
    """Build the JSON-LD for a Hebrew lexicon word page: a BreadcrumbList plus a
    DefinedTerm entry (schema.org's type for dictionary/glossary content)."""
    word_url = request.build_absolute_uri(f"/lexicon/hebrew/{word['slug']}/")
    short_def = (word.get('strongs_def') or word.get('kjv_def') or '')[:300]

    schemas = [
        {
            "@context": "https://schema.org",
            "@type": "BreadcrumbList",
            "itemListElement": [
                {
                    "@type": "ListItem",
                    "position": 1,
                    "name": "Lexicon",
                    "item": request.build_absolute_uri('/lexicon/hebrew/')
                },
                {
                    "@type": "ListItem",
                    "position": 2,
                    "name": "Hebrew",
                    "item": request.build_absolute_uri('/lexicon/hebrew/')
                },
                {
                    "@type": "ListItem",
                    "position": 3,
                    "name": f"{word['lemma']} ({word['strong_number']})",
                    "item": word_url
                }
            ]
        },
        {
            "@context": "https://schema.org",
            "@type": "DefinedTerm",
            "name": word['lemma'],
            "termCode": word['strong_number'],
            "description": short_def,
            "url": word_url,
            "inDefinedTermSet": {
                "@type": "DefinedTermSet",
                "name": "Hebrew Lexicon — Real Bible Translation Project",
                "url": request.build_absolute_uri('/lexicon/hebrew/')
            }
        }
    ]

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
