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
    normalize_book_name,
    old_testament_books,
    new_testament_books,
    load_json,
)
from search.seo_utils import book_to_slug, slug_to_book
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
    
    # Route 3: SINGLE VERSE (legacy query param -> 301 redirect)
    elif book and chapter_num and verse_num:
        slug = book_to_slug(book)
        if slug:
            redirect_url = reverse('verse_seo_view', kwargs={'book_slug': slug, 'chapter': chapter_num, 'verse': verse_num})
            if request.GET.get('lang'):
                redirect_url += f"?lang={request.GET.get('lang')}"
            return redirect(redirect_url, permanent=True)
        return handle_single_verse(request, book, chapter_num, verse_num, language)
    
    # Route 4: SINGLE CHAPTER (legacy query param -> 301 redirect)
    elif book and chapter_num:
        slug = book_to_slug(book)
        if slug:
            redirect_url = reverse('chapter_seo_view', kwargs={'book_slug': slug, 'chapter': chapter_num})
            if request.GET.get('lang'):
                redirect_url += f"?lang={request.GET.get('lang')}"
            return redirect(redirect_url, permanent=True)
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
    ip = request.META.get('HTTP_X_FORWARDED_FOR', request.META.get('REMOTE_ADDR', 'unknown'))
    ua = request.META.get('HTTP_USER_AGENT', '')[:200]
    print(
        f"[REQUEST] verse book={book} chapter={chapter_num} verse={verse_num} "
        f"lang={language} path={request.get_full_path()} ip={ip} ua={ua}"
    )
    try:
        # Normalize book display (e.g., '3John' -> '3 John') while keeping lookup compatible
        book = normalize_book_name(book) or book
        results = get_results(book, chapter_num, verse_num, language)
        # Log cache status for observability
        try:
            print(f"[CACHE] verse book={book} chapter={chapter_num} verse={verse_num} cached={results.get('cached_hit', False)}")
        except Exception:
            pass
        
        # Validate verse exists - need either Greek (NT) or verse text (OT)
        has_nt_data = results.get('rbt_greek')
        has_ot_text = results.get('rbt') or results.get('rbt_text') or results.get('rbt_paraphrase')
        
        if not has_nt_data and not has_ot_text:
            context = {'error': 'Verse is Invalid'}
            return render(request, 'search_input.html', context)
        
        replacements = load_json()  # NT - loads from InterlinearConfig DB
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

        from django.utils.html import strip_tags
        is_nt = bool(has_nt_data)
        lang_str = "Greek" if is_nt else "Hebrew"
        
        # Build clean snippet for description
        clean_text = strip_tags(rbt_text or rbt_paraphrase or '')
        snippet = f" '{clean_text[:120]}...'" if clean_text else ""
        
        if is_nt:
            meta_title = f"{book} {chapter_num}:{verse_num} Greek Interlinear Translation | Parsing, Morphology, Logeion"
            meta_description = f"Read the {book} {chapter_num}:{verse_num} Greek interlinear translation:{snippet} Featuring full morphological parsing, Strong's lexicon, and Logeion/Perseus study tools."
        else:
            meta_title = f"{book} {chapter_num}:{verse_num} Hebrew Interlinear Translation | Strongs, BDB, Parsing"
            meta_description = f"Read the {book} {chapter_num}:{verse_num} Hebrew interlinear translation:{snippet} Featuring full morphological parsing, BDB, Fuerst, and Strong's Hebrew lexicon popups."

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
            'hebrew_interlinear_cards': hebrew_cards,
            'meta_title': meta_title,
            'meta_description': meta_description,
        }
        page_title = meta_title
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
    print(
        f"[REQUEST] chapter book={book} chapter={chapter_num} "
        f"lang={language} path={request.get_full_path()}"
    )
    from search.views.chapter_handlers import (
        handle_genesis_chapter,
        handle_nt_chapter,
        handle_ot_chapter
    )
    
    try:
        source_book = book
        # Normalize book display (e.g., '3John' -> '3 John') for consistent rendering
        book = normalize_book_name(book) or book
        results = get_results(book, chapter_num, None, language)
        try:
            print(f"[CACHE] chapter book={book} chapter={chapter_num} cached={results.get('cached_hit', False)}")
        except Exception:
            pass
        
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


def chapter_seo_view(request, book_slug, chapter, lang_code=None):
    """
    SEO-friendly route for single chapters (e.g., /genesis/1/ or /es/genesis/1/).
    Extracts the canonical book name from the slug and forwards to handle_single_chapter.
    """
    book_name = slug_to_book(book_slug)
    if not book_name:
        # Invalid slug, fallback or 404
        return render(request, 'search_input.html', {'error': 'Book not found.'})
    
    language = lang_code or request.GET.get('lang', 'en')
    
    # Optional: validate lang_code against SUPPORTED_LANGUAGES here if you want to strictly enforce it
    # if lang_code and lang_code not in SUPPORTED_LANGUAGES:
    #     return render(request, 'search_input.html', {'error': 'Unsupported language.'})

    return handle_single_chapter(request, book_name, chapter, language)


def verse_seo_view(request, book_slug, chapter, verse, lang_code=None):
    """
    SEO-friendly route for single verses (e.g., /genesis/1/1/ or /es/genesis/1/1/).
    Extracts the canonical book name from the slug and forwards to handle_single_verse.
    """
    book_name = slug_to_book(book_slug)
    if not book_name:
        return render(request, 'search_input.html', {'error': 'Book not found.'})
        
    language = lang_code or request.GET.get('lang', 'en')
    return handle_single_verse(request, book_name, chapter, verse, language)
