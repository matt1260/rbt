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
from search.seo_utils import book_to_slug, slug_to_book, RTL_LANGUAGES
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
            language = request.GET.get('lang', 'en')
            route_name = 'verse_seo_view_lang' if language != 'en' else 'verse_seo_view'
            kwargs = {'book_slug': slug, 'chapter': chapter_num, 'verse': verse_num}
            if route_name.endswith('_lang'):
                kwargs['lang_code'] = language
            redirect_url = reverse(route_name, kwargs=kwargs)
            return redirect(redirect_url, permanent=True)
        return handle_single_verse(request, book, chapter_num, verse_num, language)
    
    # Route 4: SINGLE CHAPTER (legacy query param -> 301 redirect)
    elif book and chapter_num:
        slug = book_to_slug(book)
        if slug:
            language = request.GET.get('lang', 'en')
            route_name = 'chapter_seo_view_lang' if language != 'en' else 'chapter_seo_view'
            kwargs = {'book_slug': slug, 'chapter': chapter_num}
            if route_name.endswith('_lang'):
                kwargs['lang_code'] = language
            redirect_url = reverse(route_name, kwargs=kwargs)
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

        # Footnotes carry their own translations, keyed differently from the verse.
        # get_footnote() renders '1-1-1' by taking the trailing number and looking up
        # '<abbrev>-<n>' (Joh-1); verse_translations keys the same note by FULL book
        # name ('John-1'). Map across that gap so translated notes appear too.
        if footnote_contents and language and language != 'en':
            footnote_ids = results.get('current_verse_footnotes') or []
            wanted = {}
            for idx, raw_id in enumerate(footnote_ids):
                number = str(raw_id).split('-')[-1]
                wanted[f'{book}-{number}'] = idx

            if wanted:
                translated_notes = {}
                for trans in (
                    VerseTranslation.objects
                    .filter(
                        footnote_id__in=list(wanted.keys()),
                        language_code=language,
                        status='completed',
                    )
                    .exclude(footnote_text__isnull=True)
                    .exclude(footnote_text='')
                    .exclude(footnote_text__startswith='[Translation error')
                ):
                    translated_notes[trans.footnote_id] = trans.footnote_text

                if translated_notes:
                    footnote_contents = list(footnote_contents)
                    for key, idx in wanted.items():
                        if key not in translated_notes or idx >= len(footnote_contents):
                            continue
                        row = footnote_contents[idx]
                        body = translated_notes[key]
                        # Swap only the note body, keeping get_footnote()'s row
                        # scaffolding (number cell + note-location) intact.
                        swapped, n = re.subn(
                            r'(<div class="note-location">.*?</div>)(.*?)(</td>\s*</tr>)',
                            lambda m: m.group(1) + body + m.group(3),
                            row,
                            count=1,
                            flags=re.DOTALL,
                        )
                        if not n:
                            swapped, n = re.subn(
                                r'(<td[^>]*>)(?:(?!</td>).)*(</td>\s*</tr>)',
                                lambda m: m.group(1) + body + m.group(2),
                                row,
                                count=1,
                                flags=re.DOTALL,
                            )
                        if n:
                            footnote_contents[idx] = swapped

        if footnote_contents:
            footnotes_content = "<p> ".join(footnote_contents)
            footnotes_content = f'<div style="font-size: 12px;">{footnotes_content}</div>'
        else:
            footnotes_content = ''
        
        rbt_paraphrase = rbt_paraphrase or ''

        # Verse pages never consulted verse_translations, so /<lang>/<book>/<ch>/<v>/
        # served English in all 38 languages while the chapter page beside it was
        # correctly translated. Show the translation above the English rather than
        # replacing it -- on a study page both are useful.
        translated_verse = ''
        translated_language_label = ''
        if language and language != 'en':
            try:
                verse_int = int(str(verse_num).strip())
            except (TypeError, ValueError):
                verse_int = None
            if verse_int is not None:
                # verse_translations stores book names inconsistently ('3 John'
                # and '3John' both occur), so try the spaced and unspaced forms.
                book_variants = {book, book.replace(' ', '')}
                trans = (
                    VerseTranslation.objects
                    .filter(
                        book__in=list(book_variants),
                        chapter=chapter_num,
                        verse=verse_int,
                        language_code=language,
                        status='completed',
                        footnote_id__isnull=True,
                    )
                    .exclude(verse_text__isnull=True)
                    .exclude(verse_text='')
                    # ~18% of rows are stored Gemini failures ("[Translation
                    # error: 503 UNAVAILABLE...") saved with status='completed'.
                    # Never render those as if they were a translation.
                    .exclude(verse_text__startswith='[Translation error')
                    .first()
                )
                if trans:
                    translated_verse = trans.verse_text
                    translated_language_label = dict(SUPPORTED_LANGUAGES).get(language, language)

        rbt = f'<strong>RBT Translation:</strong><div>{rbt}</div>'

        from django.utils.html import strip_tags
        is_nt = bool(has_nt_data)
        lang_str = "Greek" if is_nt else "Hebrew"
        
        # Build clean snippet for description
        clean_text = strip_tags(rbt_text or rbt_paraphrase or '')
        snippet = f" '{clean_text[:120]}...'" if clean_text else ""
        
        standard_book = re.sub(r'(\d+)([a-zA-Z]+)', r'\1 \2', book)

        chapter_slug = book_to_slug(book)
        chapter_route = 'chapter_seo_view_lang' if language != 'en' else 'chapter_seo_view'
        chapter_kwargs = {'book_slug': chapter_slug, 'chapter': chapter_num}
        if chapter_route.endswith('_lang'):
            chapter_kwargs['lang_code'] = language
        chapter_url = reverse(chapter_route, kwargs=chapter_kwargs) if chapter_slug else f'/?book={book}&chapter={chapter_num}'

        if is_nt:
            meta_title = f"{standard_book} {chapter_num}:{verse_num} Greek Interlinear Translation | Gospel of the Queen"
            meta_description = f"Read the {standard_book} {chapter_num}:{verse_num} Greek interlinear translation:{snippet} Featuring full morphological parsing, Strong's lexicon, and Logeion/Perseus study tools."
        else:
            meta_title = f"{standard_book} {chapter_num}:{verse_num} Hebrew Interlinear Translation | Gospel of the Queen"
            meta_description = f"Read the {standard_book} {chapter_num}:{verse_num} Hebrew interlinear translation:{snippet} Featuring full morphological parsing, BDB, Fuerst, and Strong's Hebrew lexicon popups."

        context = {
            'previous_verse': previous_verse,
            'next_verse': next_verse,
            'footnotes': footnotes_content,
            'book': book,
            'chapter_num': chapter_num,
            'chapter_url': chapter_url,
            'verse_num': verse_num,
            'slt': slt,
            'rbt': rbt,
            'translated_verse': translated_verse,
            'translated_language_label': translated_language_label,
            'current_language': language,
            'is_rtl': language in RTL_LANGUAGES,
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
