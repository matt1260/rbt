"""
Chapter display handlers for different book types (Genesis, OT, NT).

Each handler processes chapter data with translation support and renders
the appropriate template.
"""

from django.shortcuts import render
import re

from search.models import Genesis, VerseTranslation
from search.views.footnote_views import get_footnote, build_notes_html
from translate.translator import (
    book_abbreviations,
    convert_book_name,
    old_testament_books,
    new_testament_books,
)
from search.rbt_titles import rbt_books
from search.translation_utils import SUPPORTED_LANGUAGES
from search.db_utils import execute_query


def handle_genesis_chapter(request, book, chapter_num, results, language, source_book):
    """
    Handle Genesis chapter display with Hebrew literal and paraphrase.
    
    Genesis uses Django ORM and has its own footnote system.
    Supports multi-language translation.
    """
    rbt = results['rbt']
    cached_hit = results['cached_hit']
    chapter_list = results['chapter_list']
    notes_sources = []
    
    # Translation tracking
    translation_quota_exceeded = False
    verses_to_translate = {}
    footnotes_to_translate = {}
    book_name_translation = None
    footnotes_collection = {}
    
    if language != 'en':
        # Check which verses need translation
        existing_translations = VerseTranslation.objects.filter(
            book=book,
            chapter=chapter_num,
            language_code=language,
            status__in=['completed', 'processing'],
            footnote_id__isnull=True
        ).values_list('verse', flat=True)
        
        for result in rbt:
            if int(result.verse) not in existing_translations:
                verses_to_translate[int(result.verse)] = True
        
        # Check if book name needs translation
        book_name_translation = VerseTranslation.objects.filter(
            book=book,
            chapter=0,
            verse=0,
            language_code=language,
            status__in=['completed', 'processing'],
            footnote_id__isnull=True
        ).first()
        
        if not book_name_translation:
            verses_to_translate[0] = True
        
        # Get existing translations
        translated_verses = {}
        translations_qs = VerseTranslation.objects.filter(
            book=book,
            chapter=chapter_num,
            language_code=language,
            status='completed',
            footnote_id__isnull=True
        )
        for trans in translations_qs:
            if trans.verse_text:
                translated_verses[trans.verse] = trans.verse_text

    hebrew_literal = ""
    paraphrase = ""
    
    for result in rbt:
        # verse_html = Hebrew Literal (DO NOT translate - always English)
        # verse_reader = Paraphrase (translate this)
        verse_html = result.html  # Always use original English Hebrew Literal
        verse_reader = result.rbt_reader
        
        if language != 'en' and int(result.verse) in translated_verses:
            # Apply translation ONLY to paraphrase (verse_reader), NOT to Hebrew Literal (verse_html)
            verse_reader = translated_verses[int(result.verse)]
        
        # Extract footnotes for translation from both HTML and reader
        if verse_html:
            sup_texts = re.findall(r'\?footnote=([^"&\s]+)', verse_html)
            for sup_text in sup_texts:
                if sup_text not in footnotes_collection:
                    footnote_html = get_footnote(sup_text, book)
                    if footnote_html:
                        footnotes_collection[sup_text] = {
                            'verse': result.verse,
                            'content': footnote_html,
                            'id': sup_text
                        }

        if '</p><p>' in verse_html:
            parts = verse_html.split('</p><p>')
            hebrew_literal += f'{parts[0]}</p><p><span class="verse_ref" style="display: none;"><b><a href="?book={book}&chapter={result.chapter}&verse={result.verse}">{result.verse}</a> </b></span>{parts[1]}'
        elif verse_html.startswith('<p>'):
            hebrew_literal += f'<p><span class="verse_ref" style="display: none;"><b><a href="?book={book}&chapter={result.chapter}&verse={result.verse}">{result.verse}</a> </b></span>{verse_html[3:]}'
        else:
            hebrew_literal += f'<span class="verse_ref" style="display: none;"><b><a href="?book={book}&chapter={result.chapter}&verse={result.verse}">{result.verse}</a> </b></span>{verse_html}'

        if verse_reader.endswith('</span>'):
            close_text = ''
        else:
            close_text = '<br>'

        if '<h5>' in verse_reader:
            parts = verse_reader.split('</h5>')
            if len(parts) >= 2:
                heading = parts[0] + '</h5>'
                paraphrase += f'{heading}<span class="verse_ref" style="display: none;"><b><a href="?book={book}&chapter={result.chapter}&verse={result.verse}">{result.verse}</a> </b></span>{parts[1]}{close_text}'
            else:
                paraphrase += f'{heading}<span class="verse_ref" style="display: none;"><b><a href="?book={book}&chapter={result.chapter}&verse={result.verse}">{result.verse}</a> </b></span>{verse_reader}{close_text}'
        elif verse_reader == '':
            paraphrase += ''
        else:
            paraphrase += f'<span class="verse_ref" style="display: none;"><b><a href="?book={book}&chapter={result.chapter}&verse={result.verse}">{result.verse}</a> </b></span>{verse_reader}{close_text}'

        if result.html:
            notes_sources.append(result.html)
        if result.rbt_reader:
            notes_sources.append(result.rbt_reader)

    # Handle footnote translations
    translated_footnotes = {}
    if language != 'en':
        # Get translated footnotes from database
        for trans in VerseTranslation.objects.filter(
            book=book,
            chapter=chapter_num,
            language_code=language,
            status='completed'
        ).exclude(footnote_text__isnull=True).exclude(footnote_text=''):
            if trans.footnote_id:
                translated_footnotes[trans.footnote_id] = trans.footnote_text
        
        if footnotes_collection:
            existing_footnote_ids = set(translated_footnotes.keys())
            
            for footnote_key, footnote_data in footnotes_collection.items():
                full_footnote_id = f"{book}-{footnote_key}"
                if full_footnote_id not in existing_footnote_ids:
                    footnotes_to_translate[footnote_key] = True
            
            for footnote_id, footnote_data in footnotes_collection.items():
                full_id = f"{book}-{footnote_id}"
                if full_id in translated_footnotes:
                    footnote_data['content'] = translated_footnotes[full_id]

    commentary = None

    # Store original book name
    original_book = book

    chapters = ""
    for number in chapter_list:
        chapters += f'<a href="?book={original_book}&chapter={number}&lang={language}" style="text-decoration: none;">{number}</a> |'

    # Build notes_html with translated footnotes when available
    notes_html = build_notes_html(notes_sources, source_book, chapter_num, translated_footnotes=translated_footnotes)

    # Transform book name for display
    display_book = rbt_books.get(book, book)
    
    # Apply translated book name if available
    if language != 'en' and book_name_translation and book_name_translation.verse_text:
        display_book = book_name_translation.verse_text

    page_title = f'{display_book} {chapter_num}'
    
    # Determine if translation is needed
    needs_translation = False
    if language != 'en':
        print(f"[SEARCH VIEW DEBUG Genesis] Checking translation needs for {book} ch{chapter_num} lang={language}")
        print(f"[SEARCH VIEW DEBUG Genesis] verses_to_translate count: {len(verses_to_translate)}")
        print(f"[SEARCH VIEW DEBUG Genesis] footnotes_to_translate count: {len(footnotes_to_translate)}")
        if verses_to_translate or footnotes_to_translate:
            needs_translation = True
            print(f"[SEARCH VIEW DEBUG Genesis] Setting needs_translation=True")
        else:
            print(f"[SEARCH VIEW DEBUG Genesis] All translations exist, needs_translation=False")
    
    context = {
        'chapters': chapters,
        'html': hebrew_literal,
        'paraphrase': paraphrase,
        'commentary': commentary,
        'book': display_book,
        'original_book': original_book,
        'chapter_num': chapter_num,
        'chapter_list': chapter_list,
        'footnotes': footnotes_collection,
        'cache_hit': cached_hit,
        'notes_html': notes_html,
        'supported_languages': SUPPORTED_LANGUAGES,
        'current_language': language,
        'translation_quota_exceeded': translation_quota_exceeded,
        'needs_translation': needs_translation,
    }
    return render(request, 'chapter.html', {'page_title': page_title, **context})


def handle_nt_chapter(request, book, chapter_num, results, language, source_book):
    """
    Handle New Testament chapter display with Greek text and interlinear.
    
    NT books use PostgreSQL new_testament schema.
    Supports multi-language translation.
    """
    chapter_rows = results['chapter_reader']
    html_rows = results['html']
    chapter_list = results['chapter_list']
    cached_hit = results['cached_hit']
    commentary = results['commentary']
    
    print(f"[RENDER DEBUG] Book: '{book}', Has chapter_rows: {len(chapter_rows) if chapter_rows else 0}")
    print(f"[RENDER DEBUG] Is NT book: {book in new_testament_books}")
    
    if commentary is not None:
        commentary = commentary[0]

    # Translation tracking
    translation_quota_exceeded = False
    verses_to_translate = {}
    footnotes_to_translate = {}
    book_name_translation = None
    
    if language != 'en':
        # Check which verses need translation (completed OR processing)
        existing_translations = VerseTranslation.objects.filter(
            book=book,
            chapter=chapter_num,
            language_code=language,
            status__in=['completed', 'processing'],
            footnote_id__isnull=True
        ).values_list('verse', flat=True)
        
        verses_to_translate = {}
        for row in chapter_rows:
            bk, ch_num, vrs, html_verse = row
            if int(vrs) not in existing_translations:
                verses_to_translate[int(vrs)] = True
        
        # Check if book name needs translation (stored with verse=0)
        book_name_translation = VerseTranslation.objects.filter(
            book=book,
            chapter=0,
            verse=0,
            language_code=language,
            status__in=['completed', 'processing'],
            footnote_id__isnull=True
        ).first()
        
        if not book_name_translation:
            verses_to_translate[0] = True  # Indicate book name needs translation

        # Collect all translated verses (existing only, new ones fetched via API)
        translated_verses = {}
        translations_qs = VerseTranslation.objects.filter(
            book=book,
            chapter=chapter_num,
            language_code=language,
            status='completed',
            footnote_id__isnull=True
        )
        for trans in translations_qs:
            if trans.verse_text:
                translated_verses[trans.verse] = trans.verse_text
        
        # Apply translations to chapter_rows
        updated_rows = []
        for row in chapter_rows:
            bk, ch_num, vrs, html_verse = row
            if int(vrs) in translated_verses:
                html_verse = translated_verses[int(vrs)]
            updated_rows.append((bk, ch_num, vrs, html_verse))
        chapter_rows = updated_rows

    # Collect footnotes
    footnotes_collection = {}
    
    def query_footnote(book, sup_text):
        """Query footnote from appropriate schema."""
        # Resolve to canonical full name for schema detection; use abbreviation for table/id
        full_book = book if book in new_testament_books or book in old_testament_books else (convert_book_name(book) or book)
        book_abbrev = book_abbreviations.get(full_book, full_book)
        schema = 'new_testament' if full_book in new_testament_books else 'old_testament'

        print(f"[QUERY_FOOTNOTE DEBUG] book='{book}', full='{full_book}', abbrev='{book_abbrev}', sup_text='{sup_text}', schema={schema}")

        abbrev_lower = book_abbrev.lower() # type: ignore
        if schema == 'new_testament' and abbrev_lower[0].isdigit():
            table_name = f"table_{abbrev_lower}_footnotes"
        else:
            table_name = f"{abbrev_lower}_footnotes"

        execute_query(f"SET search_path TO {schema};")
        db_footnote_id = f"{book_abbrev}-{sup_text}"
        
        try:
            result = execute_query(
                f"SELECT footnote_html FROM {schema}.{table_name} WHERE footnote_id = %s",
                (db_footnote_id,),
                fetch='one'
            )
            return result[0] if result else None
        except Exception as e:
            print(f"[FOOTNOTE QUERY ERROR] Schema: {schema}, Table: {table_name}, ID: {db_footnote_id}, Error: {e}")
            return None

    paraphrase = ""
    for row in chapter_rows:
        bk, ch_num, vrs, html_verse = row
        if html_verse:
            close_text = '' if html_verse.endswith('</span>') else '<br>'

            sup_texts = re.findall(r'<sup>(.*?)</sup>', html_verse)
            for sup_text in sup_texts:
                data = query_footnote(bk, sup_text)
                if data:
                    footnotes_collection[sup_text] = {
                        'verse': vrs,
                        'content': data,
                        'id': sup_text
                    }

            if '<h5>' in html_verse:
                parts = html_verse.split('</h5>')
                if len(parts) >= 2:
                    heading = parts[0] + '</h5>'
                    paraphrase += f'{heading}<span class="verse_ref" style="display: none;"><b><a href="?book={book}&chapter={chapter_num}&verse={vrs}">{vrs}</a> </b></span>{parts[1]}{close_text}'
                else:
                    paraphrase += f'{heading}<span class="verse_ref" style="display: none;"><b><a href="?book={book}&chapter={chapter_num}&verse={vrs}">{vrs}</a> </b></span>{html_verse}{close_text}'
            else:
                html_verse = f'<span class="verse_ref" style="display: none;"><b><a href="?book={book}&chapter={chapter_num}&verse={vrs}">{vrs}</a></b></span> {html_verse}'
                paraphrase += html_verse + close_text
    
    # Handle footnote translations
    if language != 'en' and footnotes_collection:
        existing_footnote_ids = set()
        for trans in VerseTranslation.objects.filter(
            book=book,
            chapter=chapter_num,
            language_code=language,
            status='completed'
        ).exclude(footnote_text__isnull=True).exclude(footnote_text=''):
            if trans.footnote_id:
                existing_footnote_ids.add(trans.footnote_id)
        
        footnotes_to_translate = {}
        for footnote_key, footnote_data in footnotes_collection.items():
            full_footnote_id = f"{book}-{footnote_key}"
            if full_footnote_id not in existing_footnote_ids:
                footnotes_to_translate[footnote_key] = True

        # Apply translated footnotes (existing ones only)
        translated_footnotes = {}
        for trans in VerseTranslation.objects.filter(
            book=book,
            chapter=chapter_num,
            language_code=language,
            status='completed'
        ).exclude(footnote_text__isnull=True).exclude(footnote_text=''):
            if trans.footnote_id:
                translated_footnotes[trans.footnote_id] = trans.footnote_text
        
        for footnote_id, footnote_data in footnotes_collection.items():
            full_id = f"{book}-{footnote_id}"
            if full_id in translated_footnotes:
                footnote_data['content'] = translated_footnotes[full_id]

    # Store original book name BEFORE transformation for API calls
    original_book = book
    
    chapters = ''
    for number in chapter_list:
        chapters += f'<a href="?book={original_book}&chapter={number}&lang={language}" style="text-decoration: none;">{number}</a> |'

    # Transform book name for display only
    display_book = re.sub(r'(\d+)([a-zA-Z]+)', r'\1 \2', book)
    display_book = rbt_books.get(display_book, display_book)
    
    # Apply translated book name if available
    if language != 'en' and book_name_translation and book_name_translation.verse_text:
        display_book = book_name_translation.verse_text
    page_title = f'{display_book} {chapter_num}'
    
    needs_translation = False
    if language != 'en':
        print(f"[SEARCH VIEW DEBUG] Checking translation needs for {book} ch{chapter_num} lang={language}")
        print(f"[SEARCH VIEW DEBUG] verses_to_translate count: {len(verses_to_translate)}")
        print(f"[SEARCH VIEW DEBUG] footnotes_to_translate count: {len(footnotes_to_translate)}")
        if verses_to_translate:
            print(f"[SEARCH VIEW DEBUG] Missing verse numbers: {list(verses_to_translate.keys())[:10]}")
        if footnotes_to_translate:
            print(f"[SEARCH VIEW DEBUG] Missing footnote keys: {list(footnotes_to_translate.keys())[:10]}")
        if verses_to_translate or footnotes_to_translate:
            needs_translation = True
            print(f"[SEARCH VIEW DEBUG] Setting needs_translation=True")
        else:
            print(f"[SEARCH VIEW DEBUG] All translations exist, needs_translation=False")
            
    context = {
        'cache_hit': cached_hit,
        'chapters': chapters,
        'html': "",  # NT literal
        'paraphrase': paraphrase,
        'book': display_book,
        'original_book': original_book,
        'chapter_num': chapter_num,
        'chapter_list': chapter_list,
        'footnotes': footnotes_collection,
        'current_language': language,
        'supported_languages': SUPPORTED_LANGUAGES,
        'translation_quota_exceeded': translation_quota_exceeded,
        'needs_translation': needs_translation
    }
    
    return render(request, 'nt_chapter.html', {'page_title': page_title, **context})


def handle_ot_chapter(request, book, chapter_num, results, language, source_book):
    """
    Handle Old Testament chapter display (excluding Genesis).
    
    OT books use PostgreSQL old_testament schema.
    Supports Hebrew literal and paraphrase with multi-language translation.
    """
    chapter_rows = results['chapter_reader']
    html_rows = results['html']
    chapter_list = results['chapter_list']
    cached_hit = results['cached_hit']
    commentary = results['commentary']
    
    print(f"[RENDER DEBUG] Book: '{book}', Has chapter_rows: {len(chapter_rows) if chapter_rows else 0}")
    print(f"[RENDER DEBUG] Is OT book: {book in old_testament_books}")
    
    if commentary is not None:
        commentary = commentary[0]

    # Translation tracking
    translation_quota_exceeded = False
    verses_to_translate = {}
    footnotes_to_translate = {}
    book_name_translation = None
    translated_footnotes = {}
    
    # Build verse_data from html_rows (already grouped by verse) - NOT chapter_rows (word-level)
    sorted_verse_keys = sorted(html_rows.keys(), key=lambda x: int(x) if x.isdigit() else float('inf'))
    
    if language != 'en':
        # Check which verses need translation
        existing_translations = VerseTranslation.objects.filter(
            book=book,
            chapter=chapter_num,
            language_code=language,
            status__in=['completed', 'processing'],
            footnote_id__isnull=True
        ).values_list('verse', flat=True)
        
        # Build verse_data from html_rows (one entry per verse)
        verse_data = []
        for vrs_key in sorted_verse_keys:
            eng_literal, html_paraphrase = html_rows[vrs_key]
            verse_num_int = int(vrs_key) if vrs_key.isdigit() else float('inf')
            verse_data.append((verse_num_int, vrs_key, html_paraphrase))
        
        # Check which verses need translation
        for verse_num_int, vrs, html_verse in verse_data:
            if verse_num_int not in existing_translations:
                verses_to_translate[verse_num_int] = True
        
        # Check if book name needs translation
        book_name_translation = VerseTranslation.objects.filter(
            book=book,
            chapter=0,
            verse=0,
            language_code=language,
            status__in=['completed', 'processing'],
            footnote_id__isnull=True
        ).first()
        
        if not book_name_translation:
            verses_to_translate[0] = True
        
        # Get existing translations
        translated_verses = {}
        translations_qs = VerseTranslation.objects.filter(
            book=book,
            chapter=chapter_num,
            language_code=language,
            status='completed',
            footnote_id__isnull=True
        )
        for trans in translations_qs:
            if trans.verse_text:
                translated_verses[trans.verse] = trans.verse_text
        
        # Apply translations to verses
        updated_verse_data = []
        for verse_num_int, vrs, html_verse in verse_data:
            if verse_num_int in translated_verses:
                html_verse = translated_verses[verse_num_int]
            updated_verse_data.append((verse_num_int, vrs, html_verse))
        verse_data = updated_verse_data
    else:
        # For English, build verse_data from html_rows
        verse_data = []
        for vrs_key in sorted_verse_keys:
            eng_literal, html_paraphrase = html_rows[vrs_key]
            verse_num_int = int(vrs_key) if vrs_key.isdigit() else float('inf')
            verse_data.append((verse_num_int, vrs_key, html_paraphrase))
    
    # Collect footnotes from verse HTML
    footnotes_collection = {}
    paraphrase = ""
    
    # Process sorted verses
    for verse_num, vrs, html_verse in verse_data:
        # Strip leading zeros for display and links
        display_vrs = vrs.lstrip('0') or '0'
        if html_verse:
            # Extract footnote references from verse HTML
            sup_texts = re.findall(r'\?footnote=([^"&\s]+)', html_verse)
            for sup_text in sup_texts:
                if sup_text not in footnotes_collection:
                    footnote_html = get_footnote(sup_text, source_book)
                    if footnote_html:
                        footnotes_collection[sup_text] = {
                            'verse': display_vrs,
                            'content': footnote_html,
                            'id': sup_text
                        }
            
            close_text = '' if html_verse.endswith('</span>') else '<br>'
            if '<h5>' in html_verse:
                parts = html_verse.split('</h5>')
                if len(parts) >= 2:
                    heading = parts[0] + '</h5>'
                    paraphrase += f'{heading}<span class="verse_ref" style="display: none;"><b><a href="?book={book}&chapter={chapter_num}&verse={display_vrs}">{display_vrs}</a> </b></span>{parts[1]}{close_text}'
                else:
                    paraphrase += f'{heading}<span class="verse_ref" style="display: none;"><b><a href="?book={book}&chapter={chapter_num}&verse={display_vrs}">{display_vrs}</a> </b></span>{html_verse}{close_text}'
            else:
                html_verse = f'<span class="verse_ref" style="display: none;"><b><a href="?book={book}&chapter={chapter_num}&verse={display_vrs}">{display_vrs}</a></b></span> {html_verse}'
                paraphrase += html_verse + close_text

    # Handle footnote translations
    if language != 'en' and footnotes_collection:
        existing_footnote_ids = set()
        for trans in VerseTranslation.objects.filter(
            book=book,
            chapter=chapter_num,
            language_code=language,
            status='completed'
        ).exclude(footnote_text__isnull=True).exclude(footnote_text=''):
            if trans.footnote_id:
                existing_footnote_ids.add(trans.footnote_id)
        
        for footnote_key, footnote_data in footnotes_collection.items():
            full_footnote_id = f"{book}-{footnote_key}"
            if full_footnote_id not in existing_footnote_ids:
                footnotes_to_translate[footnote_key] = True
        
        # Apply translated footnotes
        translated_footnotes = {}
        for trans in VerseTranslation.objects.filter(
            book=book,
            chapter=chapter_num,
            language_code=language,
            status='completed'
        ).exclude(footnote_text__isnull=True).exclude(footnote_text=''):
            if trans.footnote_id:
                translated_footnotes[trans.footnote_id] = trans.footnote_text
        
        for footnote_id, footnote_data in footnotes_collection.items():
            full_id = f"{book}-{footnote_id}"
            if full_id in translated_footnotes:
                footnote_data['content'] = translated_footnotes[full_id]

    # Compile the Hebrew Literal
    hebrew_literal = ""
    sorted_keys = sorted(html_rows.keys(), key=lambda x: int(x) if x.isdigit() else float('inf'))

    for key in sorted_keys:
        english_literal = html_rows[key][0]
        words_str = english_literal if english_literal is not None else ''

        display_key = key.lstrip('0') or '0'
        hebrew_literal += (
            f'<span class="verse_ref" style="display: none;">'
            f'<b><a href="?book={book}&chapter={chapter_num}&verse={display_key}">{display_key}</a> </b></span>'
            f'{words_str}<br>'
        )
    
    # Store original book name BEFORE transformation
    original_book = book
    
    chapters = ''
    for number in chapter_list:
        chapters += f'<a href="?book={original_book}&chapter={number}&lang={language}" style="text-decoration: none;">{number}</a> |'

    # Transform book name for display
    display_book = re.sub(r'(\d+)([a-zA-Z]+)', r'\1 \2', book)
    display_book = rbt_books.get(display_book, display_book)
    
    # Apply translated book name if available
    if language != 'en' and book_name_translation and book_name_translation.verse_text:
        display_book = book_name_translation.verse_text
    
    page_title = f'{display_book} {chapter_num}'
    notes_html = build_notes_html([paraphrase, hebrew_literal], source_book, chapter_num, translated_footnotes=translated_footnotes)
    
    # Determine if translation is needed
    needs_translation = False
    if language != 'en':
        print(f"[SEARCH VIEW DEBUG OT] Checking translation needs for {book} ch{chapter_num} lang={language}")
        print(f"[SEARCH VIEW DEBUG OT] verses_to_translate count: {len(verses_to_translate)}")
        print(f"[SEARCH VIEW DEBUG OT] footnotes_to_translate count: {len(footnotes_to_translate)}")
        if verses_to_translate or footnotes_to_translate:
            needs_translation = True
            print(f"[SEARCH VIEW DEBUG OT] Setting needs_translation=True")
        else:
            print(f"[SEARCH VIEW DEBUG OT] All translations exist, needs_translation=False")
    
    context = {
        'chapters': chapters,
        'html': hebrew_literal,
        'paraphrase': paraphrase,
        'commentary': commentary,
        'book': display_book,
        'original_book': original_book,
        'chapter_num': chapter_num,
        'chapter_list': chapter_list,
        'footnotes': footnotes_collection,
        'notes_html': notes_html,
        'supported_languages': SUPPORTED_LANGUAGES,
        'current_language': language,
        'translation_quota_exceeded': translation_quota_exceeded,
        'needs_translation': needs_translation,
        'cache_hit': cached_hit,
    }
    
    return render(request, 'chapter.html', {'page_title': page_title, **context})
