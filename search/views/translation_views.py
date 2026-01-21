"""
Translation API endpoints and cache management.
"""
import re
from django.http import JsonResponse
from django.views.decorators.csrf import csrf_exempt
from django.core.cache import cache
from search.models import VerseTranslation
from translate.translator import (
    book_abbreviations, new_testament_books, old_testament_books,
    nt_abbrev
)
from search.rbt_titles import rbt_books
from search.translation_utils import translate_chapter_batch, translate_footnotes_batch
from .footnote_views import get_footnote

# Import get_results from chapter_views when needed (to avoid circular import)
# We'll use a late import pattern in the functions that need it

INTERLINEAR_CACHE_VERSION = 'v2'


def get_cache_key(book, chapter_num, verse_num, language):
    """Generate cache key for verse/chapter translations."""
    sanitized_book = book.replace(':', '_').replace(' ', '')
    return f'{sanitized_book}_{chapter_num}_{verse_num}_{language}_{INTERLINEAR_CACHE_VERSION}'


def translate_chapter_api(request):
    """
    API endpoint to trigger translation for a chapter.
    This allows non-blocking translation handling on the frontend.
    
    WARNING: This endpoint performs synchronous translation which can timeout.
    Consider using start_translation_job() for better reliability.
    """
    from .chapter_views_part1 import get_results  # Late import to avoid circular dependency
    from search.db_utils import execute_query
    
    book = request.GET.get('book')
    chapter_num = request.GET.get('chapter')
    language = request.GET.get('lang')
    
    if not book or not chapter_num or not language or language == 'en':
        print(f"[API DEBUG] Invalid params: book={book}, chapter={chapter_num}, lang={language}")
        return JsonResponse({'status': 'skipped', 'message': 'Invalid parameters or English language'})
    
    # Ensure chapter_num is integer for DB comparisons
    try:
        chapter_num = int(chapter_num)
    except ValueError:
        return JsonResponse({'status': 'error', 'message': 'Invalid chapter number'})
    
    print(f"[API DEBUG] Starting translation for {book} ch{chapter_num} in {language}")

    try:
        # Force English source to get canonical text for translation
        results = get_results(book, chapter_num, None, 'en')
        
        # Initialize translation_stats for all code paths
        translation_stats = {'verses': 0, 'footnotes': 0}
        
        if book in new_testament_books:
            translation_stats = _translate_nt_chapter(book, chapter_num, language, results)
        elif book == 'Genesis' or book in old_testament_books:
            translation_stats = _translate_ot_chapter(book, chapter_num, language, results)
        else:
            print(f"[API DEBUG] Book '{book}' not recognized for translation")
            return JsonResponse({'status': 'skipped', 'message': f'Book {book} not supported for translation'})
        
        print(f"[API DEBUG] All translations saved to database.")
        print(f"[API DEBUG] Translation complete. Verses: {translation_stats['verses']}, Footnotes: {translation_stats['footnotes']}")
        
        # Clear cache for the target language
        try:
             cache_key = get_cache_key(book, chapter_num, None, language)
             cache.delete(cache_key)
             print(f"Cleared cache for: {cache_key}")
        except Exception as e:
             print(f"Error clearing cache: {e}")

        print(f"[API DEBUG] Returning success response to client")
        return JsonResponse({'status': 'ok', 'translated': translation_stats})
        
    except Exception as e:
        import traceback
        traceback.print_exc()
        return JsonResponse({'status': 'error', 'message': str(e)})


def _translate_nt_chapter(book, chapter_num, language, results):
    """Handle NT chapter translation (verses and footnotes)."""
    from search.db_utils import execute_query
    
    translation_stats = {'verses': 0, 'footnotes': 0}
    chapter_rows = results['chapter_reader']
    print(f"[API DEBUG] Found {len(chapter_rows)} rows in chapter")
    
    # --- VERSE TEXT TRANSLATION ---
    existing_translations = VerseTranslation.objects.filter(
        book=book,
        chapter=chapter_num,
        language_code=language,
        status__in=['completed', 'processing'],
        footnote_id__isnull=True
    ).values_list('verse', flat=True)
    
    print(f"[API DEBUG] Existing translations: {list(existing_translations)}")

    verses_to_translate = {}
    
    for row in chapter_rows:
        bk, ch_num, vrs, html_verse = row
        if int(vrs) not in existing_translations:
            verses_to_translate[int(vrs)] = html_verse
    
    # Check if book name needs translation (stored with verse=0)
    book_name_exists = VerseTranslation.objects.filter(
        book=book,
        chapter=0,
        verse=0,
        language_code=language,
        status='completed',
        footnote_id__isnull=True
    ).exists()
    
    if not book_name_exists:
        display_book_en = re.sub(r'(\d+)([a-zA-Z]+)', r'\1 \2', book)
        display_book_en = rbt_books.get(display_book_en, display_book_en)
        verses_to_translate[0] = display_book_en
        print(f"[API DEBUG] Book name needs translation: {display_book_en}")
    
    print(f"[API DEBUG] Verses to translate: {list(verses_to_translate.keys())}")
    
    if verses_to_translate:
        # Mark verses as 'processing' to prevent duplicate translations
        for verse_num in verses_to_translate.keys():
            if verse_num == 0:
                VerseTranslation.objects.update_or_create(
                    book=book, chapter=0, verse=0,
                    language_code=language, footnote_id=None,
                    defaults={'status': 'processing', 'verse_text': ''}
                )
            else:
                VerseTranslation.objects.update_or_create(
                    book=book, chapter=chapter_num, verse=verse_num,
                    language_code=language, footnote_id=None,
                    defaults={'status': 'processing', 'verse_text': ''}
                )
        print(f"[API DEBUG] Marked {len(verses_to_translate)} verses as 'processing'")
        
        translated_results = translate_chapter_batch(verses_to_translate, language)
        
        if '__quota_exceeded__' in translated_results:
            raise Exception('Translation quota exceeded')
        
        all_failed = all('[Translation unavailable' in str(v) for v in translated_results.values())
        if all_failed and translated_results:
            raise Exception('Translation service unavailable - API key not configured')
        
        for verse_num, translated_text in translated_results.items():
            if '[Translation unavailable' in translated_text:
                continue
            
            if verse_num == 0:
                VerseTranslation.objects.update_or_create(
                    book=book, chapter=0, verse=0,
                    language_code=language, footnote_id=None,
                    defaults={'verse_text': translated_text, 'status': 'completed', 'generated_by': 'gemini-3-flash-preview'}
                )
            else:
                VerseTranslation.objects.update_or_create(
                    book=book, chapter=chapter_num, verse=verse_num,
                    language_code=language, footnote_id=None,
                    defaults={'verse_text': translated_text, 'status': 'completed', 'generated_by': 'gemini-3-flash-preview'}
                )
            translation_stats['verses'] += 1

    print(f"[API DEBUG] Verse translation complete. Starting footnote extraction...")
    
    # --- FOOTNOTE TRANSLATION ---
    footnotes_collection = {}
    
    def query_footnote_text(book, sup_text):
        footnote_id = f"{book}-{sup_text}"
        if book[0].isdigit():
            table_name = f"table_{book.lower()}_footnotes"
        else:
            table_name = f"{book.lower()}_footnotes"
        
        with get_db_connection() as conn:
            with conn.cursor() as cursor:
                cursor.execute("BEGIN")
                cursor.execute("SET LOCAL search_path TO new_testament")
                cursor.execute(
                    f"SELECT footnote_html FROM new_testament.{table_name} WHERE footnote_id = %s",
                    (footnote_id,)
                )
                row = cursor.fetchone()
                return row[0] if row else None

    for row in chapter_rows:
        bk, ch_num, vrs, html_verse = row
        if html_verse:
            sup_texts = re.findall(r'<sup>(.*?)</sup>', html_verse)
            for sup_text in sup_texts:
                data = query_footnote_text(bk, sup_text)
                if data:
                    footnotes_collection[sup_text] = {
                        'verse': vrs,
                        'content': data,
                        'id': sup_text
                    }
    
    if footnotes_collection:
        target_ids = [f"{book}-{k}" for k in footnotes_collection.keys()]
        found_objs = VerseTranslation.objects.filter(
            language_code=language,
            status__in=['completed', 'processing'],
            footnote_id__in=target_ids
        ).values_list('footnote_id', flat=True)
        
        existing_footnote_ids = set(found_objs)
        
        footnotes_to_translate = {}
        for sup_text, data in footnotes_collection.items():
            f_id = f"{book}-{sup_text}"
            if f_id not in existing_footnote_ids:
                footnotes_to_translate[f_id] = data['content']

        if footnotes_to_translate:
            # Mark as processing
            for f_id in footnotes_to_translate.keys():
                found_sup = None
                for s_txt in footnotes_collection:
                    if f"{book}-{s_txt}" == f_id:
                        found_sup = s_txt
                        break
                v_obj = 0
                c_obj = chapter_num
                if found_sup:
                    c_obj = int(footnotes_collection[found_sup].get('chapter', 0) or chapter_num)
                    v_obj = int(footnotes_collection[found_sup].get('verse', 0))
                
                VerseTranslation.objects.update_or_create(
                    book=book, chapter=c_obj, verse=v_obj,
                    language_code=language, footnote_id=f_id,
                    defaults={'status': 'processing', 'footnote_text': ''}
                )
            
            translated_footnotes = translate_footnotes_batch(footnotes_to_translate, language)
            
            if '__quota_exceeded__' in translated_footnotes:
                 raise Exception('Translation quota exceeded')

            for f_id, f_text in translated_footnotes.items():
                if '[Translation unavailable' in f_text:
                    continue
                
                found_sup = None
                for s_txt in footnotes_collection:
                    if f"{book}-{s_txt}" == f_id:
                        found_sup = s_txt
                        break
                
                v_obj = 0
                c_obj = chapter_num
                
                if found_sup:
                    c_obj = int(footnotes_collection[found_sup].get('chapter', 0) or chapter_num)
                    v_obj = int(footnotes_collection[found_sup].get('verse', 0))
                
                VerseTranslation.objects.update_or_create(
                    book=book, chapter=c_obj, verse=v_obj,
                    language_code=language, footnote_id=f_id,
                    defaults={'footnote_text': f_text, 'status': 'completed', 'generated_by': 'gemini-3-flash-preview'}
                )
                translation_stats['footnotes'] += 1
    
    return translation_stats


def _translate_ot_chapter(book, chapter_num, language, results):
    """Handle OT chapter translation (verses and footnotes)."""
    translation_stats = {'verses': 0, 'footnotes': 0}
    
    print(f"[API DEBUG] Processing OT book: {book}")
    
    book_abbrev = book_abbreviations.get(book, book)
    
    # --- PARAPHRASE TEXT TRANSLATION (not Hebrew Literal) ---
    existing_translations = VerseTranslation.objects.filter(
        book=book,
        chapter=chapter_num,
        language_code=language,
        status__in=['completed', 'processing'],
        footnote_id__isnull=True
    ).values_list('verse', flat=True)
    
    verses_to_translate = {}
    
    if book == 'Genesis':
        rbt_queryset = results.get('rbt', [])
        for verse_obj in rbt_queryset:
            verse_num = verse_obj.verse
            paraphrase_content = verse_obj.rbt_reader or ''
            if verse_num not in existing_translations and paraphrase_content:
                verses_to_translate[verse_num] = paraphrase_content
    else:
        html_dict = results.get('html', {})
        for verse_key, value in html_dict.items():
            if isinstance(value, tuple) and len(value) >= 2:
                paraphrase_content = value[1] or ''
            else:
                paraphrase_content = value if isinstance(value, str) else ''
            verse_num = int(verse_key)
            if verse_num not in existing_translations and paraphrase_content:
                verses_to_translate[verse_num] = paraphrase_content
    
    # Check if book name needs translation
    book_name_exists = VerseTranslation.objects.filter(
        book=book, chapter=0, verse=0,
        language_code=language, status='completed',
        footnote_id__isnull=True
    ).exists()
    
    if not book_name_exists:
        display_book_en = re.sub(r'(\d+)([a-zA-Z]+)', r'\1 \2', book)
        display_book_en = rbt_books.get(display_book_en, display_book_en)
        verses_to_translate[0] = display_book_en
    
    if verses_to_translate:
        # Mark as processing
        for verse_num in verses_to_translate.keys():
            if verse_num == 0:
                VerseTranslation.objects.update_or_create(
                    book=book, chapter=0, verse=0,
                    language_code=language, footnote_id=None,
                    defaults={'status': 'processing', 'verse_text': ''}
                )
            else:
                VerseTranslation.objects.update_or_create(
                    book=book, chapter=chapter_num, verse=verse_num,
                    language_code=language, footnote_id=None,
                    defaults={'status': 'processing', 'verse_text': ''}
                )
        
        translated_results = translate_chapter_batch(verses_to_translate, language)
        
        if '__quota_exceeded__' in translated_results:
            raise Exception('Translation quota exceeded')
        
        all_failed = all('[Translation unavailable' in str(v) for v in translated_results.values())
        if all_failed and translated_results:
            raise Exception('Translation service unavailable - API key not configured')
        
        for verse_num, translated_text in translated_results.items():
            if '[Translation unavailable' in translated_text:
                continue
            
            if verse_num == 0:
                VerseTranslation.objects.update_or_create(
                    book=book, chapter=0, verse=0,
                    language_code=language, footnote_id=None,
                    defaults={'verse_text': translated_text, 'status': 'completed', 'generated_by': 'gemini-3-flash-preview'}
                )
            else:
                VerseTranslation.objects.update_or_create(
                    book=book, chapter=chapter_num, verse=verse_num,
                    language_code=language, footnote_id=None,
                    defaults={'verse_text': translated_text, 'status': 'completed', 'generated_by': 'gemini-3-flash-preview'}
                )
            translation_stats['verses'] += 1
    
    # --- OT FOOTNOTE TRANSLATION ---
    footnotes_collection = {}
    
    if book == 'Genesis':
        rbt_queryset = results.get('rbt', [])
        for verse_obj in rbt_queryset:
            html_content = verse_obj.html or ''
            verse_num = verse_obj.verse
            if html_content:
                footnote_refs = re.findall(r'\?footnote=(\d+-\d+-\d+[a-zA-Z]?)', html_content)
                for fn_ref in footnote_refs:
                    fn_content = get_footnote(fn_ref, book)
                    if fn_content:
                        f_id = f"{book}-{fn_ref}"
                        if f_id not in footnotes_collection:
                            footnotes_collection[f_id] = {
                                'verse': verse_num,
                                'chapter': chapter_num,
                                'content': fn_content,
                                'id': f_id
                            }
    else:
        html_dict = results.get('html', {})
        for verse_key, value in html_dict.items():
            if isinstance(value, tuple) and len(value) >= 2:
                html_content = value[1]
            else:
                html_content = value
            if html_content:
                footnote_refs = re.findall(r'\?footnote=([^"&\s]+)', html_content)
                for fn_ref in footnote_refs:
                    fn_content = get_footnote(fn_ref, book)
                    if fn_content:
                        f_id = f"{book}-{fn_ref}"
                        if f_id not in footnotes_collection:
                            footnotes_collection[f_id] = {
                                'verse': int(verse_key) if verse_key.isdigit() else 0,
                                'chapter': chapter_num,
                                'content': fn_content,
                                'id': f_id
                            }
    
    if footnotes_collection:
        existing_footnote_ids = set(VerseTranslation.objects.filter(
            language_code=language,
            status__in=['completed', 'processing'],
            footnote_id__in=list(footnotes_collection.keys())
        ).values_list('footnote_id', flat=True))
        
        footnotes_to_translate = {}
        for f_id, data in footnotes_collection.items():
            if f_id not in existing_footnote_ids:
                footnotes_to_translate[f_id] = data['content']
        
        if footnotes_to_translate:
            # Mark as processing
            for f_id in footnotes_to_translate.keys():
                data = footnotes_collection.get(f_id, {})
                VerseTranslation.objects.update_or_create(
                    book=book,
                    chapter=data.get('chapter', chapter_num),
                    verse=data.get('verse', 0),
                    language_code=language,
                    footnote_id=f_id,
                    defaults={'status': 'processing', 'footnote_text': ''}
                )
            
            translated_footnotes = translate_footnotes_batch(footnotes_to_translate, language)
            
            if '__quota_exceeded__' in translated_footnotes:
                raise Exception('Translation quota exceeded')
            
            for f_id, f_text in translated_footnotes.items():
                if '[Translation unavailable' in f_text:
                    continue
                
                data = footnotes_collection.get(f_id, {})
                VerseTranslation.objects.update_or_create(
                    book=book,
                    chapter=data.get('chapter', chapter_num),
                    verse=data.get('verse', 0),
                    language_code=language,
                    footnote_id=f_id,
                    defaults={'footnote_text': f_text, 'status': 'completed', 'generated_by': 'gemini-3-flash-preview'}
                )
                translation_stats['footnotes'] += 1
    
    return translation_stats


@csrf_exempt
def start_translation_job(request):
    """
    API endpoint to start a background translation job.
    Returns immediately with job ID for status polling.
    
    This is the new non-blocking translation approach:
    1. Creates a job record in the database
    2. Background worker picks up and processes the job
    3. Frontend polls for status updates
    """
    from .chapter_views_part1 import get_results  # Late import
    
    book = request.GET.get('book')
    chapter_num = request.GET.get('chapter')
    language = request.GET.get('lang')
    
    if not book or not chapter_num or not language or language == 'en':
        return JsonResponse({
            'status': 'error',
            'message': 'Invalid parameters or English language'
        })
    
    try:
        chapter_num = int(chapter_num)
    except ValueError:
        return JsonResponse({'status': 'error', 'message': 'Invalid chapter number'})
    
    try:
        # Special handling for Joseph and Aseneth (storehouse book)
        if book == "Joseph and Aseneth":
            # For storehouse, we don't validate through get_results
            # The storehouse view has its own data structure
            from search.translation_worker import create_translation_job
            
            job = create_translation_job(book, chapter_num, language)
            
            return JsonResponse({
                'status': 'ok',
                'job_id': job.job_id,
                'message': f'Translation job created for {book} chapter {chapter_num}'
            })
        
        # Validate that source content exists before creating a job
        results = get_results(book, chapter_num, None, 'en')
        if not results:
            return JsonResponse({'status': 'error', 'message': 'No source content found for this chapter'})
        
        # Determine if the chapter contains any source text
        has_source = False
        if book == 'Genesis':
            if results.get('rbt'):
                has_source = True
        elif book in old_testament_books:
            html = results.get('html') or {}
            if isinstance(html, dict) and any(v for v in html.values()):
                has_source = True
        elif book in new_testament_books:
            chapter_rows = results.get('chapter_reader') or []
            if chapter_rows:
                has_source = True
        else:
            if results.get('rbt') or results.get('html') or results.get('chapter_reader'):
                has_source = True
        
        if not has_source:
            return JsonResponse({'status': 'error', 'message': 'No source content found for this chapter'})
        
        from search.translation_worker import create_translation_job
        
        job = create_translation_job(book, chapter_num, language)
        
        return JsonResponse({
            'status': 'ok',
            'job_id': job.job_id,
            'message': f'Translation job created for {book} chapter {chapter_num}'
        })
        
    except Exception as e:
        import traceback
        traceback.print_exc()
        return JsonResponse({'status': 'error', 'message': str(e)})


@csrf_exempt
def translation_job_status(request):
    """
    API endpoint to check the status of a translation job.
    Frontend should poll this endpoint to track progress.
    """
    job_id = request.GET.get('job_id')
    
    if not job_id:
        return JsonResponse({'status': 'error', 'message': 'Missing job_id'})
    
    try:
        from search.translation_worker import get_job_status
        
        status = get_job_status(job_id)
        
        if status is None:
            return JsonResponse({'status': 'error', 'message': 'Job not found'})
        
        return JsonResponse(status)
        
    except Exception as e:
        return JsonResponse({'status': 'error', 'message': str(e)})


@csrf_exempt
def clear_translation_cache(request):
    """
    API endpoint to clear cache after translation completes.
    Called by frontend after job completion.
    """
    book = request.GET.get('book')
    chapter_num = request.GET.get('chapter')
    language = request.GET.get('lang')
    
    if not book or not chapter_num or not language:
        return JsonResponse({'status': 'error', 'message': 'Missing parameters'})
    
    try:
        chapter_num = int(chapter_num)
        cache_key = get_cache_key(book, chapter_num, None, language)
        cache.delete(cache_key)
        
        return JsonResponse({
            'status': 'ok',
            'message': f'Cache cleared for {book} chapter {chapter_num} ({language})'
        })
        
    except Exception as e:
        return JsonResponse({'status': 'error', 'message': str(e)})
