"""
Main search/chapter display dispatch view.

Handles routing for different types of Bible content requests:
- Reference search (e.g., "John 3:16")
- Keyword search (legacy, now redirects to search API)
- Single verse display
- Chapter display (Genesis, OT, NT)
"""

import re
from urllib.parse import urlencode

from django.core.cache import cache
from django.shortcuts import redirect, render
from django.urls import reverse

from bs4 import BeautifulSoup
import pythonbible as bible
from pythonbible import InvalidBookError, InvalidChapterError, InvalidVerseError

from search.models import Genesis, VerseTranslation
from search.views.chapter_views_part1 import get_results
from search.views.footnote_views import get_footnote
from translate.translator import (
    book_abbreviations,
    convert_book_name,
    old_testament_books,
    new_testament_books,
    load_json,
)
from search.rbt_titles import rbt_books
from search.translation_utils import SUPPORTED_LANGUAGES
from search.db_utils import execute_query


def search(request):
    """
    Main dispatch view for Bible content requests.
    
    Routes to appropriate handler based on query parameters:
    - ref: Bible reference search
    - q: Keyword search (redirects to search API)
    - book + chapter + verse: Single verse display
    - book + chapter: Chapter display
    
    Query params:
    - q: Keyword search query
    - ref: Bible reference (e.g., "John 3:16")
    - book: Book name
    - chapter: Chapter number
    - verse: Verse number (optional)
    - lang: Language code (default: 'en')
    """
    query = request.GET.get('q')
    ref_query = request.GET.get('ref')
    chapter_num = request.GET.get('chapter')
    book = request.GET.get('book')
    verse_num = request.GET.get('verse')
    language = request.GET.get('lang', 'en')
    
    error = None
    reference = None
    
    # Route 1: REFERENCE SEARCH
    if ref_query:
        return handle_reference_search(request, ref_query, language)
    
    # Route 2: KEYWORD SEARCH (redirects to search API)
    elif query:
        return handle_keyword_search(request, query)
    
    # Route 3: SINGLE VERSE
    elif book and chapter_num and verse_num:
        return handle_single_verse(request, book, chapter_num, verse_num, language)
    
    # Route 4: SINGLE CHAPTER
    elif book and chapter_num:
        return handle_single_chapter(request, book, chapter_num, language)
    
    # Default: Show search input
    else:
        context = {'error': error}
        return render(request, 'search_input.html', context)


def handle_reference_search(request, ref_query, language):
    """
    Handle Bible reference search (e.g., "John 3:16").
    
    Parses reference using pythonbible and redirects to appropriate view.
    """
    error = None
    reference = None
    
    try:
        reference = bible.get_references(ref_query)
    except (InvalidBookError, InvalidChapterError, InvalidVerseError) as e:
        error = e
    except Exception as e:
        error = e

    # Check if the reference list is not empty
    if reference:
        # Use only the first entry
        first_entry = reference[0]
        book = first_entry.book.name

        if book == 'SONG_OF_SONGS':
            book = 'Song of Solomon'
        elif book.endswith('_1'):
            book = book[:-2].capitalize()
            book = '1 ' + book
        elif book.endswith('_2'):
            book = '2 ' + book[:-2].capitalize()
        else:
            book = book.capitalize()

        start_chapter = first_entry.start_chapter
        start_verse = first_entry.start_verse
        end_chapter = first_entry.end_chapter
        end_verse = first_entry.end_verse
        chapter_num = start_chapter
        verse_num = start_verse

        if ":" not in ref_query:
            verse_num = None
        
        # Redirect to appropriate view
        if verse_num:
            return handle_single_verse(request, book, chapter_num, verse_num, language)
        else:
            return handle_single_chapter(request, book, chapter_num, language)
    
    # Error case
    context = {'error': error}
    return render(request, 'search_input.html', context)


def handle_keyword_search(request, query):
    """Redirect keyword queries to the dedicated results page."""

    params = {
        'q': query,
        'scope': request.GET.get('scope', 'all'),
        'type': request.GET.get('type', 'keyword'),
        'page': request.GET.get('page', '1'),
    }
    url = f"{reverse('search_results')}?{urlencode(params)}"
    return redirect(url)


def handle_single_verse(request, book, chapter_num, verse_num, language):
    """
    Handle single verse display with interlinear data.
    
    Fetches verse data using get_results() and renders verse.html template.
    Includes Hebrew/Greek interlinear, translations, and footnotes.
    """
    try:
        results = get_results(book, chapter_num, verse_num, language)
        
        # Validate verse exists - need either Greek (NT) or verse text (OT)
        has_nt_data = results.get('rbt_greek')
        has_ot_text = results.get('rbt') or results.get('rbt_text') or results.get('rbt_paraphrase')
        
        if not has_nt_data and not has_ot_text:
            context = {'error': 'Verse is Invalid'}
            return render(request, 'search_input.html', context)
        
        replacements = load_json('interlinear_english.json')  # NT
        greek = results['rbt_greek']
        interlinear = results['interlinear']  # NT
        hebrew = results['hebrew']
        rbt = results['rbt']
        rbt_text = results['rbt_text']
        rbt_paraphrase = results['rbt_paraphrase']
        slt = results['slt']
        litv = results['litv']
        eng_lxx = results['eng_lxx']
        previous_verse = results['prev_ref']
        next_verse = results['next_ref']
        footnote_contents = results['footnote_content']
        cached_hit = results['cached_hit']
        strong_row = results['strong_row']
        english_row = results['english_row']
        hebrew_row = results['hebrew_row']
        hebrew_clean = results['hebrew_clean']
        hebrew_cards = results.get('hebrew_interlinear_cards')
        hebrew_cards = hebrew_cards or []

        if footnote_contents:
            footnotes_content = "<p> ".join(footnote_contents)
            footnotes_content = f'<div style="font-size: 12px;">{footnotes_content}</div>'
        else:
            footnotes_content = ''
        
        rbt_paraphrase = rbt_paraphrase or ''
        rbt = f'<strong>RBT Translation:</strong><div>{rbt}</div>'

        context = {
            'previous_verse': previous_verse,
            'next_verse': next_verse,
            'footnotes': footnotes_content,
            'book': book,
            'chapter_num': chapter_num,
            'verse_num': verse_num,
            'slt': slt,
            'rbt': rbt,
            'rbt_text': rbt_text,
            'rbt_paraphrase': rbt_paraphrase,
            'englxx': eng_lxx,
            'litv': litv,
            'hebrew': hebrew,
            'greek': greek,
            'greek_interlinear': interlinear,
            'error': None,
            'cache_hit': cached_hit,
            'strong_row': strong_row,
            'english_row': english_row,
            'hebrew_row': hebrew_row,
            'hebrew_clean': hebrew_clean,
            'hebrew_interlinear_cards': hebrew_cards
        }
        page_title = f'{book} {chapter_num}:{verse_num}'
        return render(request, 'verse.html', {'page_title': page_title, **context})
        
    except Exception as e:
        context = {'error': "Invalid verse"}
        return render(request, 'search_input.html', context)


def handle_single_chapter(request, book, chapter_num, language):
    """
    Handle single chapter display (Genesis, OT, or NT).
    
    Routes to appropriate chapter handler based on book type.
    Includes translation support and footnote collection.
    """
    from search.views.chapter_handlers import (
        handle_genesis_chapter,
        handle_nt_chapter,
        handle_ot_chapter
    )
    
    try:
        source_book = book
        results = get_results(book, chapter_num, None, language)
        
        # Route to appropriate handler based on book type
        if book == 'Genesis':
            return handle_genesis_chapter(request, book, chapter_num, results, language, source_book)
        elif book in new_testament_books:
            return handle_nt_chapter(request, book, chapter_num, results, language, source_book)
        else:
            # Old Testament (except Genesis)
            return handle_ot_chapter(request, book, chapter_num, results, language, source_book)
            
    except Exception as e:
        context = {'error': e}
        return render(request, 'search_input.html', context)
