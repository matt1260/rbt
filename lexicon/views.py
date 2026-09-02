import re

from django.http import Http404, HttpResponsePermanentRedirect, JsonResponse
from django.core.paginator import Paginator
from django.shortcuts import render

from translate.db_utils import execute_query
from translate.translator import (
    get_lexicon_word_data,
    get_strongs_numeric_value,
    convert_book_name,
)
from search.db_utils import safe_cache_get, safe_cache_set
from search.seo_utils import generate_lexicon_schema, _get_verse_url
from search.views.utils import strip_hebrew_vowels

LEXICON_DATA_CACHE_TTL = 60 * 60 * 24  # 24h — lexicon data is static/curated
LEXICON_LIST_CACHE_TTL = 60 * 60 * 24
PAGE_SIZE = 100


def _all_dictionary_words():
    """All Hebrew Strong's dictionary rows, numerically ordered. Cached — this
    backs both index pagination and the sitemap, and rarely changes."""
    cache_key = 'lexicon_hebrew_word_list_v1'
    cached = safe_cache_get(cache_key)
    if cached is not None:
        return cached

    rows = execute_query(
        """
        SELECT strong_number, lemma, xlit, strongs_def
        FROM old_testament.strongs_hebrew_dictionary
        ORDER BY CAST(regexp_replace(strong_number, '\\D', '', 'g') AS INTEGER);
        """,
        fetch='all'
    ) or []

    words = [
        {
            'strong_number': strong_number,
            'slug': strong_number.lower(),
            'lemma': lemma or '',
            'xlit': xlit or '',
            'strongs_def': strongs_def or '',
        }
        for strong_number, lemma, xlit, strongs_def in rows
    ]
    safe_cache_set(cache_key, words, LEXICON_LIST_CACHE_TTL)
    return words


def lexicon_root_redirect(request):
    return HttpResponsePermanentRedirect('/lexicon/hebrew/')


def lexicon_index(request):
    words = _all_dictionary_words()

    letter = (request.GET.get('letter') or '').strip()
    if letter:
        words = [w for w in words if strip_hebrew_vowels(w['lemma'])[:1] == letter]

    letters = []
    seen_letters = set()
    for w in _all_dictionary_words():
        first = strip_hebrew_vowels(w['lemma'])[:1]
        if first and first not in seen_letters:
            seen_letters.add(first)
            letters.append(first)
    letters.sort()

    paginator = Paginator(words, PAGE_SIZE)
    page_number = request.GET.get('page') or 1
    page = paginator.get_page(page_number)

    meta_title = "Hebrew Lexicon — Strong's, BDB, Fürst & Gesenius Word Studies | RBT"
    meta_description = (
        "Browse every Hebrew word in the Old Testament with Strong's, BDB, Fürst, and "
        "Gesenius lexicon entries, scanned dictionary pages, and verse occurrences."
    )

    context = {
        'meta_title': meta_title,
        'meta_description': meta_description,
        'page': page,
        'letters': letters,
        'active_letter': letter,
        'total_words': len(_all_dictionary_words()),
    }
    return render(request, 'lexicon_index.html', context)


def lexicon_search(request):
    query = (request.GET.get('term') or '').strip()
    if len(query) < 2:
        return JsonResponse({'results': []})

    like = f'%{query}%'
    rows = execute_query(
        """
        SELECT strong_number, lemma, xlit, strongs_def
        FROM old_testament.strongs_hebrew_dictionary
        WHERE lemma ILIKE %s OR xlit ILIKE %s OR strongs_def ILIKE %s
        ORDER BY CAST(regexp_replace(strong_number, '\\D', '', 'g') AS INTEGER)
        LIMIT 25;
        """,
        (like, like, like),
        fetch='all'
    ) or []

    results = [
        {
            'strong_number': strong_number,
            'slug': strong_number.lower(),
            'lemma': lemma or '',
            'xlit': xlit or '',
            'strongs_def': (strongs_def or '')[:120],
            'url': f'/lexicon/hebrew/{strong_number.lower()}/',
        }
        for strong_number, lemma, xlit, strongs_def in rows
    ]
    return JsonResponse({'results': results})


def _canonical_slug(strongs_param: str):
    numeric_value = get_strongs_numeric_value(strongs_param or '')
    if numeric_value is None:
        return None
    return f'h{numeric_value}'


def _verse_link(occurrence):
    ref = occurrence.get('ref') or ''
    parts = ref.split('.')
    if len(parts) < 3:
        return None
    book_code = parts[0]
    chapter = parts[1]
    verse = parts[2].split('-')[0]
    book_name = convert_book_name(book_code) or book_code
    url = _get_verse_url('en', book_name, chapter, verse)
    if not url or url.startswith('?'):
        return None
    return {
        'book': book_name,
        'chapter': chapter,
        'verse': verse,
        'url': url,
    }


def lexicon_word_detail(request, strongs):
    canonical_slug = _canonical_slug(strongs)
    if canonical_slug is None:
        raise Http404("Not a valid Strong's number")

    if strongs != canonical_slug:
        return HttpResponsePermanentRedirect(f'/lexicon/hebrew/{canonical_slug}/')

    strong_number = 'H' + canonical_slug[1:]

    cache_key = f'lexicon_word_v1_{canonical_slug}'
    word = safe_cache_get(cache_key)
    if word is None:
        word = get_lexicon_word_data(strong_number)
        if word is not None:
            safe_cache_set(cache_key, word, LEXICON_DATA_CACHE_TTL)

    if word is None:
        raise Http404("No lexicon entry for this Strong's number")

    verse_links = []
    for occurrence in word['verse_occurrences']:
        link = _verse_link(occurrence)
        if link:
            verse_links.append({**occurrence, **link})

    short_def = (word['strongs_def'] or word['kjv_def'] or '')[:160]
    meta_title = f"{word['lemma']} ({word['strong_number']}) — Hebrew Lexicon | RBT"
    meta_description = (
        f"{word['lemma']} ({word['strong_number']}): {short_def} "
        f"Full Strong's, BDB, Fürst, and Gesenius Hebrew lexicon entries with "
        f"{word['occurrence_count']} Bible occurrences."
    ).strip()

    context = {
        'meta_title': meta_title,
        'meta_description': meta_description,
        'word': word,
        'verse_links': verse_links,
        'jsonld_schemas': generate_lexicon_schema(request, word),
    }
    return render(request, 'lexicon_word.html', context)
