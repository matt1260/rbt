"""
Joseph and Aseneth text viewer.

Public reader for the Joseph and Aseneth apocryphal text with Greek/English parallel display.
Supports multi-language translation via Gemini API.
"""

import re
from django.shortcuts import render
from django.core.cache import cache

from search.db_utils import get_db_connection
from search.views.translation_views import INTERLINEAR_CACHE_VERSION
from search.translation_utils import SUPPORTED_LANGUAGES
from search.models import VerseTranslation


def storehouse_view(request):
    """
    Public reader for Joseph and Aseneth text.
    
    Displays chapter-by-chapter view with English translation and Greek text.
    Includes chapter navigation, caching, and multi-language translation support.
    
    Query params:
    - chapter: Chapter number to display (default: 1)
    - lang: Language code for translation (default: 'en')
    
    Returns:
    - Rendered storehouse.html template with chapter content
    """
    book_name = "He Adds and Storehouse"
    # Internal book name used for translation database lookups
    internal_book_name = "Joseph and Aseneth"
    
    chapter_param = request.GET.get('chapter')
    try:
        chapter_num = int(chapter_param)
        if chapter_num < 1:
            chapter_num = 1
    except (TypeError, ValueError):
        chapter_num = 1

    # Language support
    language = request.GET.get('lang', 'en')
    if language not in SUPPORTED_LANGUAGES and language != 'en':
        language = 'en'

    debug_mode = request.GET.get('_debug') is not None

    cache_key = f'storehouse_{chapter_num}_{language}_{INTERLINEAR_CACHE_VERSION}'

    # Disable cache for non-English or debug to avoid stale translations
    cached_data = None
    if language == 'en' and not debug_mode:
        cached_data = cache.get(cache_key)

    if cached_data:
        context = {
            **cached_data,
            'cache_hit': True,
            'supported_languages': SUPPORTED_LANGUAGES,
            'current_language': language,
        }
        return render(request, 'storehouse.html', context)

    chapter_list = []
    chapters_markup = ''
    paraphrase = ''
    greek_literal = ''
    footnotes_collection = {}
    verses = []
    error_message = None

    try:
        with get_db_connection() as conn:
            with conn.cursor() as cursor:
                cursor.execute("SET search_path TO joseph_aseneth")
                cursor.execute(
                    """
                    SELECT DISTINCT chapter
                    FROM aseneth
                    ORDER BY chapter
                    """
                )
                chapter_rows = cursor.fetchall()

                raw_chapters = []
                for (chapter_value,) in chapter_rows:
                    if chapter_value is None:
                        continue
                    try:
                        raw_chapters.append(int(chapter_value))
                    except (TypeError, ValueError):
                        continue

                if not raw_chapters:
                    raise ValueError("Joseph and Aseneth data is unavailable.")

                chapter_list = sorted(set(raw_chapters))

                if chapter_num not in chapter_list:
                    chapter_num = chapter_list[0]

                # Build chapter links with language parameter preserved
                for number in chapter_list:
                    lang_param = f'&lang={language}' if language != 'en' else ''
                    chapters_markup += (
                        f'<a href="?chapter={number}{lang_param}" style="text-decoration: none;">{number}</a> |'
                    )

                cursor.execute(
                    """
                    SELECT verse, english, greek
                    FROM aseneth
                    WHERE chapter = %s
                    ORDER BY verse
                    """,
                    (chapter_num,)
                )
                rows = cursor.fetchall()
    except Exception as exc:
        error_message = str(exc)
        rows = []

    print(f"[STOREHOUSE DEBUG] Loading chapter {chapter_num}, language={language}")
    print(f"[STOREHOUSE DEBUG] Total verses to process: {len(rows)}")
    
    for verse_value, english_text, greek_text in rows:
        verse_label = '' if verse_value is None else str(verse_value)
        verse_ref = (
            f'<span class="verse_ref" style="display: none;">'
            f'<b>{verse_label or ""} </b></span>'
        )

        english_fragment = english_text or ''
        
        # Check for translation if non-English language requested
        if language != 'en' and verse_label:
            try:
                verse_int = int(verse_label) if verse_label.isdigit() else 0
                print(f"[STOREHOUSE DEBUG] Looking up verse {verse_label} (int={verse_int}), book='{internal_book_name}', chapter={chapter_num}, lang='{language}'")
                
                translation = VerseTranslation.objects.filter(
                    book=internal_book_name,
                    chapter=chapter_num,
                    verse=verse_int,
                    language_code=language,
                    footnote_id__isnull=True  # Only verse translations, not footnotes
                ).first()
                
                print(f"[STOREHOUSE DEBUG]   Translation found: {translation is not None}")
                if translation:
                    print(f"[STOREHOUSE DEBUG]   verse_text: {translation.verse_text[:100]}...")
                    print(f"[STOREHOUSE DEBUG]   Replacing english_fragment")
                    english_fragment = translation.verse_text
                else:
                    print(f"[STOREHOUSE DEBUG]   No translation found, using English")
            except Exception as e:
                print(f"[STOREHOUSE DEBUG] Translation lookup exception: {e}")
                import traceback
                traceback.print_exc()
                pass  # Fall back to English if translation lookup fails
        
        close_text = '' if english_fragment.endswith('</span>') else '<br>'

        if english_fragment:
            if '<h5>' in english_fragment:
                parts = english_fragment.split('</h5>')
                if len(parts) >= 2:
                    heading = parts[0] + '</h5>'
                    paraphrase += f'{heading}{verse_ref}{parts[1]}{close_text}'
                else:
                    paraphrase += f'{verse_ref}{english_fragment}{close_text}'
            else:
                formatted_paraphrase = f'{verse_ref} {english_fragment}'
                paraphrase += formatted_paraphrase + close_text

        greek_fragment = greek_text or ''
        greek_literal += f'<p>{verse_ref} {greek_fragment}</p>'
  
        anchor = re.sub(r'[^0-9a-zA-Z]+', '-', verse_label).strip('-').lower()
        if not anchor:
            anchor = f'verse-{len(verses) + 1}'
        verses.append({
            'chapter': chapter_num,
            'verse': verse_label,
            'anchor': anchor,
            'content': english_fragment  # Use potentially translated content
        })

    # Check if translation is needed (non-English and not all verses translated)
    needs_translation = False
    translated_book_name = book_name
    
    if language != 'en' and paraphrase:
        # Get translated book name (verse=0, chapter=0)
        book_translation = VerseTranslation.objects.filter(
            book=internal_book_name,
            chapter=0,
            verse=0,
            language_code=language,
            footnote_id__isnull=True
        ).first()
        
        print(f"[STOREHOUSE DEBUG] Book translation lookup: book={internal_book_name}, lang={language}")
        print(f"[STOREHOUSE DEBUG] Book translation found: {book_translation is not None}")
        if book_translation:
            print(f"[STOREHOUSE DEBUG] Translated book name: {book_translation.verse_text}")
        
        if book_translation and book_translation.verse_text:
            translated_book_name = book_translation.verse_text
        
        existing_translations = VerseTranslation.objects.filter(
            book=internal_book_name,
            chapter=chapter_num,
            language_code=language,
            footnote_id__isnull=True
        ).count()
        # Need translation if we have fewer translations than verses
        needs_translation = existing_translations < len(rows)
    
    print(f"[STOREHOUSE DEBUG] Final book name in context: {translated_book_name}")
    print(f"[STOREHOUSE DEBUG] Paraphrase first 200 chars: {paraphrase[:200]}")

    context = {
        'book': translated_book_name,
        'original_book': internal_book_name,  # For translation API
        'chapter_num': chapter_num,
        'chapters': chapters_markup,
        'paraphrase': paraphrase,
        'greek': greek_literal,
        'footnotes': footnotes_collection,
        'verses': verses,
        'error_message': error_message,
        'cache_hit': False,
        'page_title': f"{book_name} {chapter_num}" if not error_message else book_name,
        'supported_languages': SUPPORTED_LANGUAGES,
        'current_language': language,
        'needs_translation': needs_translation,
    }

    # Only cache English, non-debug responses to avoid stale translations
    if not error_message and language == 'en' and not debug_mode:
        cache.set(cache_key, {**context})

    response = render(request, 'storehouse.html', context)
    
    # Prevent browser caching for translated pages
    if language != 'en':
        response['Cache-Control'] = 'no-cache, no-store, must-revalidate, max-age=0'
        response['Pragma'] = 'no-cache'
        response['Expires'] = '0'
    
    return response

