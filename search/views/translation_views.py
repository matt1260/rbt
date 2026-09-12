"""
Translation API endpoints and cache management.
"""
import re
from django.db.models import Q
from django.http import JsonResponse
from django.views.decorators.csrf import csrf_exempt
from django.core.cache import cache
from search.db_utils import invalidate_cached_render
from search.models import VerseTranslation
from translate.translator import (
    book_abbreviations, new_testament_books, old_testament_books,
    nt_abbrev
)
from search.rbt_titles import rbt_books
from search.translation_utils import translate_chapter_batch, translate_footnotes_batch
from search.translation_utils import SUPPORTED_LANGUAGES
from .footnote_views import get_footnote

# Import get_results from chapter_views when needed (to avoid circular import)
# We'll use a late import pattern in the functions that need it

INTERLINEAR_CACHE_VERSION = 'v3'


# Gemini failures are persisted as ordinary rows with status='completed', so the
# only way to tell a real translation from a dead one is the text prefix.
TRANSLATION_ERROR_PREFIXES = ('[Translation error', '[Translation parsing error')

# Ceiling on per-request cache invalidations. Above this we let TTLs handle it
# rather than firing thousands of writes at the DB cache in one request.
MAX_CACHE_INVALIDATIONS = 400


def translation_error_q(field='verse_text'):
    """Q object matching rows whose text is a stored Gemini failure."""
    q = Q()
    for prefix in TRANSLATION_ERROR_PREFIXES:
        q |= Q(**{f'{field}__startswith': prefix})
    return q


def _nt_footnote_table(book_abbrev):
    table_abbrev = book_abbrev.lower()
    if table_abbrev and table_abbrev[0].isdigit():
        return f'table_{table_abbrev}_footnotes'
    return f'{table_abbrev}_footnotes'


def nt_chapter_translation_stats(book, chapter_num):
    """Per-language translation coverage for one NT chapter.

    Source tables key books by abbreviation ('Joh') while verse_translations
    keys them by full name ('John'), so both forms are needed here.

    Returns None for non-NT books -- this panel is NT-only for now.
    """
    from search.db_utils import execute_query  # local: keeps import graph flat
    from search.models import GeminiUsageLog
    from django.utils import timezone

    if book not in new_testament_books:
        return None

    try:
        chapter_num = int(chapter_num)
    except (TypeError, ValueError):
        return None

    book_abbrev = book_abbreviations.get(book, book)

    # --- source totals ---------------------------------------------------
    row = execute_query(
        'SELECT count(*) FROM new_testament.nt WHERE book = %s AND chapter = %s;',
        (book_abbrev, chapter_num), fetch='one'
    )
    source_verses = int(row[0]) if row else 0

    # Footnote ids in new_testament.<abbrev>_footnotes are sequential per BOOK
    # ('Joh-1' ... 'Joh-787') with no chapter component, so counting that table
    # would report the whole book. Count the notes this chapter's verses actually
    # reference instead.
    source_footnotes = 0
    try:
        rows = execute_query(
            'SELECT rbt FROM new_testament.nt WHERE book = %s AND chapter = %s;',
            (book_abbrev, chapter_num), fetch='all'
        ) or []
        chapter_html = ' '.join((r[0] or '') for r in rows)
        source_footnotes = len(set(
            re.findall(r'\?footnote=[0-9]+-[0-9]+-([0-9A-Za-z]+)', chapter_html)
        ))
    except Exception:
        source_footnotes = 0

    # --- translation rows, one query for the whole chapter ---------------
    rows = VerseTranslation.objects.filter(
        book=book, chapter=chapter_num, status='completed'
    ).values_list('language_code', 'verse', 'verse_text', 'footnote_id', 'footnote_text')

    per_lang = {}
    for lang, verse, verse_text, footnote_id, footnote_text in rows:
        d = per_lang.setdefault(lang, {
            'verses_ok': set(), 'verses_err': set(),
            'notes_ok': set(), 'notes_err': set(),
        })
        if footnote_id:
            text = footnote_text or ''
            bucket = 'notes_err' if text.startswith(TRANSLATION_ERROR_PREFIXES) else 'notes_ok'
            if text:
                d[bucket].add(footnote_id)
        else:
            text = verse_text or ''
            if not text:
                continue
            bucket = 'verses_err' if text.startswith(TRANSLATION_ERROR_PREFIXES) else 'verses_ok'
            d[bucket].add(verse)

    languages = []
    for code, label in SUPPORTED_LANGUAGES.items():
        if code == 'en':
            continue
        d = per_lang.get(code)
        v_ok = len(d['verses_ok']) if d else 0
        v_err = len(d['verses_err']) if d else 0
        n_ok = len(d['notes_ok']) if d else 0
        n_err = len(d['notes_err']) if d else 0
        v_missing = max(source_verses - v_ok - v_err, 0)
        n_missing = max(source_footnotes - n_ok - n_err, 0)

        if v_ok == 0 and v_err == 0:
            state = 'absent'
        elif v_err:
            state = 'errors'
        elif v_missing or n_missing:
            state = 'partial'
        else:
            state = 'complete'

        languages.append({
            'code': code, 'label': label, 'state': state,
            'verses_ok': v_ok, 'verses_err': v_err, 'verses_missing': v_missing,
            'notes_ok': n_ok, 'notes_err': n_err, 'notes_missing': n_missing,
        })

    order = {'errors': 0, 'partial': 1, 'absent': 2, 'complete': 3}
    languages.sort(key=lambda x: (order[x['state']], x['label']))

    summary = {'complete': 0, 'partial': 0, 'errors': 0, 'absent': 0}
    for entry in languages:
        summary[entry['state']] += 1
    summary['total'] = len(languages)
    summary['error_rows'] = sum(e['verses_err'] + e['notes_err'] for e in languages)

    # --- free-tier quota awareness ---------------------------------------
    quota = {'today': 0, 'rate_limited': 0, 'errors': 0}
    try:
        since = timezone.now().replace(hour=0, minute=0, second=0, microsecond=0)
        today = GeminiUsageLog.objects.filter(timestamp__gte=since)
        quota['today'] = today.count()
        quota['rate_limited'] = today.filter(status_code=429).count()
        quota['errors'] = today.exclude(status_code__in=[200, 429]).count()
    except Exception:
        pass

    return {
        'book': book,
        'book_abbrev': book_abbrev,
        'chapter': chapter_num,
        'source_verses': source_verses,
        'source_footnotes': source_footnotes,
        'languages': languages,
        'summary': summary,
        'quota': quota,
    }


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
             invalidate_cached_render(cache_key)
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
        
        translated_results = translate_chapter_batch(verses_to_translate, language, chapter=chapter_num)
        
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
                    defaults={'verse_text': translated_text, 'status': 'completed', 'generated_by': 'gemini-3.8-flash'}
                )
            else:
                VerseTranslation.objects.update_or_create(
                    book=book, chapter=chapter_num, verse=verse_num,
                    language_code=language, footnote_id=None,
                    defaults={'verse_text': translated_text, 'status': 'completed', 'generated_by': 'gemini-3.8-flash'}
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
                    defaults={'footnote_text': f_text, 'status': 'completed', 'generated_by': 'gemini-3.8-flash'}
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
        
        translated_results = translate_chapter_batch(verses_to_translate, language, chapter=chapter)
        
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
                    defaults={'verse_text': translated_text, 'status': 'completed', 'generated_by': 'gemini-3.8-flash'}
                )
            else:
                VerseTranslation.objects.update_or_create(
                    book=book, chapter=chapter_num, verse=verse_num,
                    language_code=language, footnote_id=None,
                    defaults={'verse_text': translated_text, 'status': 'completed', 'generated_by': 'gemini-3.8-flash'}
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
                    defaults={'footnote_text': f_text, 'status': 'completed', 'generated_by': 'gemini-3.8-flash'}
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

    if language not in SUPPORTED_LANGUAGES:
        return JsonResponse({
            'status': 'error',
            'message': f'Unsupported language: {language}'
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
        
        # Special handling for Gospel of Judas
        if book == "Gospel of Judas":
            from search.models import VerseTranslation
            # Only return 'cached' if both prose AND commentary are already translated
            prose_exists = VerseTranslation.objects.filter(
                book=book,
                chapter=chapter_num,
                verse=1,
                language_code=language,
                status__in=['completed', 'processing'],
                footnote_id__isnull=True,
            ).exists()
            commentary_exists = VerseTranslation.objects.filter(
                book=book,
                chapter=0,
                verse=2,
                language_code=language,
                status__in=['completed', 'processing'],
                footnote_id__isnull=True,
            ).exists()
            heading_exists = VerseTranslation.objects.filter(
                book=book,
                chapter=0,
                verse=3,
                language_code=language,
                status__in=['completed', 'processing'],
                footnote_id__isnull=True,
            ).exists()
            if prose_exists and commentary_exists and heading_exists:
                return JsonResponse({'status': 'cached', 'message': 'Translation already exists for this codex page.'})
            
            from search.translation_worker import create_translation_job
            job = create_translation_job(book, chapter_num, language)
            return JsonResponse({
                'status': 'ok',
                'job_id': job.job_id,
                'message': f'Translation job created for Gospel of Judas codex {chapter_num}'
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

        # If translations already exist for all verses, don't start a new job
        from search.models import VerseTranslation

        verses: list[int] = []
        if book == 'Genesis':
            for row in results.get('rbt') or []:
                try:
                    verses.append(int(row.verse))
                except Exception:
                    continue
        elif book in old_testament_books:
            html = results.get('html') or {}
            if isinstance(html, dict):
                for key in html.keys():
                    try:
                        verses.append(int(key))
                    except Exception:
                        continue
        elif book in new_testament_books:
            for row in results.get('chapter_reader') or []:
                try:
                    verses.append(int(row[2]))
                except Exception:
                    continue
        else:
            for row in results.get('chapter_reader') or []:
                try:
                    verses.append(int(row[2]))
                except Exception:
                    continue

        if verses:
            existing = set(VerseTranslation.objects.filter(
                book=book,
                chapter=chapter_num,
                language_code=language,
                status__in=['completed', 'processing'],
                footnote_id__isnull=True
            ).values_list('verse', flat=True))

            missing = [v for v in verses if v not in existing]
            if not missing:
                return JsonResponse({
                    'status': 'cached',
                    'message': 'Translations already exist for this chapter.'
                })
        
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
        invalidate_cached_render(cache_key)
        
        return JsonResponse({
            'status': 'ok',
            'message': f'Cache cleared for {book} chapter {chapter_num} ({language})'
        })
        
    except Exception as e:
        return JsonResponse({'status': 'error', 'message': str(e)})


@csrf_exempt
def retry_failed_translations(request):
    """Retry only failed verse translations for a chapter/language."""
    from .chapter_views_part1 import get_results  # Late import
    from search.translation_worker import create_translation_job

    book = request.GET.get('book')
    chapter_num = request.GET.get('chapter')
    language = request.GET.get('lang')

    if not book or not chapter_num or not language or language == 'en':
        return JsonResponse({'status': 'error', 'message': 'Invalid parameters or English language'})

    try:
        chapter_num = int(chapter_num)
    except ValueError:
        return JsonResponse({'status': 'error', 'message': 'Invalid chapter number'})

    # Remove failed translations (so worker will re-translate them)
    failed_q = Q(verse_text__startswith='[Translation error') | Q(verse_text__startswith='[Translation parsing error')
    failed_rows = VerseTranslation.objects.filter(
        book=book,
        chapter=chapter_num,
        language_code=language,
        footnote_id__isnull=True,
    ).filter(failed_q)

    failed_count = failed_rows.count()
    if failed_count == 0:
        return JsonResponse({'status': 'cached', 'message': 'No failed translations found.'})

    failed_rows.delete()

    # Validate source exists before creating job
    results = get_results(book, chapter_num, None, 'en')
    if not results:
        return JsonResponse({'status': 'error', 'message': 'No source content found for this chapter'})

    job = create_translation_job(book, chapter_num, language)
    return JsonResponse({
        'status': 'ok',
        'job_id': job.job_id,
        'message': f'Retry started for {failed_count} failed verses.'
    })


@csrf_exempt
def translation_stats_api(request):
    """JSON translation coverage for one NT chapter, for the verse editor panel."""
    book = request.GET.get('book')
    chapter_num = request.GET.get('chapter')
    if not book or not chapter_num:
        return JsonResponse({'status': 'error', 'message': 'Missing parameters'})

    stats = nt_chapter_translation_stats(book, chapter_num)
    if stats is None:
        return JsonResponse({
            'status': 'error',
            'message': 'Translation stats are available for New Testament books only.'
        })
    return JsonResponse({'status': 'ok', 'stats': stats})


@csrf_exempt
def clean_failed_translations(request):
    """Delete stored Gemini failures for an NT chapter without re-translating.

    Separate from retry_failed_translations, which deletes AND queues a new job.
    Cleaning costs no API quota, which matters on the free tier: it lets a bad
    run be cleared now and re-translated later when quota allows.

    lang may be a language code, or 'all' for every language in the chapter.
    """
    # This one deletes rows, so unlike the read-only/queueing endpoints it is
    # gated. Return JSON rather than letting @login_required 302 to a login page,
    # which the panel's fetch() could not make sense of.
    if not request.user.is_authenticated:
        return JsonResponse(
            {'status': 'error', 'message': 'Sign in to clean translations.'}, status=403
        )

    book = request.GET.get('book')
    chapter_num = request.GET.get('chapter')
    language = request.GET.get('lang')
    # chapter (default) | book | nt -- how wide to sweep.
    scope = request.GET.get('scope', 'chapter')

    if not language:
        return JsonResponse({'status': 'error', 'message': 'Missing parameters'})

    rows = VerseTranslation.objects.filter(status='completed')

    if scope == 'nt':
        rows = rows.filter(book__in=new_testament_books)
    else:
        if not book:
            return JsonResponse({'status': 'error', 'message': 'Missing parameters'})
        if book not in new_testament_books:
            return JsonResponse({
                'status': 'error',
                'message': 'This tool is limited to New Testament books.'
            })
        # Both spellings of the numbered books occur in verse_translations.
        book_forms = {book, book.replace(' ', '')}
        rows = rows.filter(book__in=list(book_forms))

        if scope != 'book':
            if not chapter_num:
                return JsonResponse({'status': 'error', 'message': 'Missing parameters'})
            try:
                chapter_num = int(chapter_num)
            except ValueError:
                return JsonResponse({'status': 'error', 'message': 'Invalid chapter number'})
            rows = rows.filter(chapter=chapter_num)

    if language != 'all':
        rows = rows.filter(language_code=language)

    failed = rows.filter(translation_error_q('verse_text') | translation_error_q('footnote_text'))
    languages_touched = sorted(set(failed.values_list('language_code', flat=True)))

    # Cached chapter payloads still hold the error text, so note what to drop
    # BEFORE the rows are gone.
    #
    # This previously took the CROSS PRODUCT of (book, chapter) x languages, which
    # at NT scope was 182 x 38 = 6,916 invalidations -- and each one is two cache
    # operations (a delete plus a tombstone write), so ~13.8k writes in a single
    # synchronous request. On 2026-09-07 that ran against a django_cache_table
    # already pinned at its row cap, forcing repeated culls, and the resulting WAL
    # churn filled the volume and crash-looped Postgres.
    #
    # Two changes: invalidate only the exact (book, chapter, language) triples that
    # actually had failures, and refuse to do it at all beyond a sane ceiling --
    # cache entries carry TTLs and will expire on their own, which is far better
    # than taking the database down to save a few stale reads.
    affected = set(failed.values_list('book', 'chapter', 'language_code'))
    removed = failed.count()
    invalidated = 0
    invalidation_skipped = False

    if removed:
        failed.delete()
        if len(affected) > MAX_CACHE_INVALIDATIONS:
            invalidation_skipped = True
        else:
            for bk, ch, code in affected:
                try:
                    invalidate_cached_render(get_cache_key(bk, ch, None, code))
                    invalidated += 1
                except Exception:
                    pass

    message = (
        f'Removed {removed} failed row(s) across {len(languages_touched)} language(s).'
        if removed else 'No failed translations found.'
    )
    if invalidation_skipped:
        message += (
            f' Skipped cache invalidation for {len(affected)} entries '
            '(over the safety limit); they will expire on their own.'
        )

    return JsonResponse({
        'status': 'ok',
        'removed': removed,
        'languages': languages_touched,
        'invalidated': invalidated,
        'invalidation_skipped': invalidation_skipped,
        'message': message,
    })


def nt_dashboard_stats():
    """NT-wide translation coverage, aggregated in SQL rather than per chapter.

    260 chapters x 71 languages is far too much to walk one chapter at a time,
    so this is two grouped queries plus one for footnotes.
    """
    from search.db_utils import execute_query
    from search.models import GeminiUsageLog
    from django.db.models import Count, Q
    from django.utils import timezone

    # new_testament_books is a membership list carrying BOTH spellings of the
    # numbered books ('1 John' and '1John'), so it has 38 entries for 27 books.
    # Good for filtering (verse_translations really does use both), wrong for
    # counting or iterating -- so collapse to one canonical name per abbreviation,
    # preferring the spaced form.
    abbrev_to_book = {}
    for b in new_testament_books:
        ab = book_abbreviations.get(b, b)
        if ab not in abbrev_to_book or (' ' in b and ' ' not in abbrev_to_book[ab]):
            abbrev_to_book[ab] = b
    book_to_abbrev = {b: ab for ab, b in abbrev_to_book.items()}
    nt_books_canonical = list(abbrev_to_book.values())

    src_rows = execute_query(
        'SELECT book, chapter, count(*) FROM new_testament.nt GROUP BY book, chapter;',
        fetch='all'
    ) or []

    source_by_book = {}
    source_total = 0
    chapters_by_book = {}
    for abbrev, chapter, n in src_rows:
        book = abbrev_to_book.get(abbrev)
        if not book:
            continue
        source_by_book[book] = source_by_book.get(book, 0) + int(n)
        chapters_by_book.setdefault(book, set()).add(int(chapter))
        source_total += int(n)

    err_q = translation_error_q('verse_text')

    # --- verses: one grouped query over NT books only ----------------------
    verse_rows = list(
        VerseTranslation.objects
        .filter(status='completed', footnote_id__isnull=True, book__in=new_testament_books)
        .values('book', 'language_code')
        .annotate(ok=Count('id', filter=~err_q), err=Count('id', filter=err_q))
    )

    # --- footnotes: same shape --------------------------------------------
    note_err_q = translation_error_q('footnote_text')
    note_rows = list(
        VerseTranslation.objects
        .filter(status='completed', book__in=new_testament_books)
        .exclude(footnote_id__isnull=True)
        .values('language_code')
        .annotate(ok=Count('id', filter=~note_err_q), err=Count('id', filter=note_err_q))
    )
    notes_by_lang = {r['language_code']: r for r in note_rows}

    # --- roll up per language ---------------------------------------------
    per_lang = {}
    per_book = {}
    for r in verse_rows:
        lang, book = r['language_code'], r['book']
        d = per_lang.setdefault(lang, {'ok': 0, 'err': 0, 'books': set()})
        d['ok'] += r['ok']
        d['err'] += r['err']
        if r['ok'] or r['err']:
            d['books'].add(book)

        # Merge '1 John' and '1John' into one bucket.
        ab = book_to_abbrev.get(book, book)
        b = per_book.setdefault(ab, {'ok': 0, 'err': 0, 'langs': set()})
        b['ok'] += r['ok']
        b['err'] += r['err']
        if r['ok'] or r['err']:
            b['langs'].add(lang)

    languages = []
    for code, label in SUPPORTED_LANGUAGES.items():
        if code == 'en':
            continue
        d = per_lang.get(code, {'ok': 0, 'err': 0, 'books': set()})
        n = notes_by_lang.get(code, {'ok': 0, 'err': 0})
        missing = max(source_total - d['ok'] - d['err'], 0)
        pct = round(100.0 * d['ok'] / source_total, 1) if source_total else 0.0
        if d['ok'] == 0 and d['err'] == 0:
            state = 'absent'
        elif d['err']:
            state = 'errors'
        elif missing:
            state = 'partial'
        else:
            state = 'complete'
        languages.append({
            'code': code, 'label': label, 'state': state, 'pct': pct,
            'verses_ok': d['ok'], 'verses_err': d['err'], 'verses_missing': missing,
            'books_started': len(d['books']),
            'notes_ok': n['ok'], 'notes_err': n['err'],
        })

    order = {'errors': 0, 'partial': 1, 'absent': 3, 'complete': 2}
    languages.sort(key=lambda x: (order[x['state']], -x['pct'], x['label']))

    books = []
    for book in nt_books_canonical:
        ab = book_to_abbrev.get(book, book)
        src = source_by_book.get(book, 0)
        b = per_book.get(ab, {'ok': 0, 'err': 0, 'langs': set()})
        books.append({
            'book': book,
            'chapters': len(chapters_by_book.get(book, ())),
            'source_verses': src,
            'verses_ok': b['ok'], 'verses_err': b['err'],
            'languages_started': len(b['langs']),
        })

    summary = {
        'source_verses': source_total,
        'books': len(nt_books_canonical),
        'chapters': sum(len(v) for v in chapters_by_book.values()),
        'languages_total': len(languages),
        'languages_started': sum(1 for x in languages if x['state'] != 'absent'),
        'languages_complete': sum(1 for x in languages if x['state'] == 'complete'),
        'languages_with_errors': sum(1 for x in languages if x['state'] == 'errors'),
        'verses_ok': sum(x['verses_ok'] for x in languages),
        'verses_err': sum(x['verses_err'] for x in languages),
        'notes_ok': sum(x['notes_ok'] for x in languages),
        'notes_err': sum(x['notes_err'] for x in languages),
    }

    # --- API / quota -------------------------------------------------------
    api = {'keys_configured': 0, 'today': 0, 'rate_limited': 0, 'errors': 0, 'by_key': []}
    try:
        from search.translation_utils import GEMINI_API_KEYS
        api['keys_configured'] = len(GEMINI_API_KEYS)
    except Exception:
        pass
    try:
        since = timezone.now().replace(hour=0, minute=0, second=0, microsecond=0)
        today = GeminiUsageLog.objects.filter(timestamp__gte=since)
        api['today'] = today.count()
        api['rate_limited'] = today.filter(status_code=429).count()
        api['errors'] = today.exclude(status_code__in=[200, 429]).count()
        api['by_key'] = list(
            today.values('api_key_abbrev').annotate(
                ok=Count('id', filter=Q(status_code=200)),
                limited=Count('id', filter=Q(status_code=429)),
                failed=Count('id', filter=~Q(status_code__in=[200, 429])),
            ).order_by('-ok')
        )
    except Exception:
        pass

    return {
        'summary': summary,
        'languages': languages,
        'books': books,
        'api': api,
    }


def translation_dashboard(request):
    """NT-wide translation dashboard: coverage, tools, prompt config, API status."""
    from django.shortcuts import render
    from django.http import HttpResponse
    from search.translation_utils import (
        TRANSLATION_GLOSSARY, LANGUAGE_TERM_OVERRIDES, build_glossary_section,
    )

    if not request.user.is_authenticated:
        return HttpResponse('Unauthorized', status=403)

    stats = nt_dashboard_stats()

    # Show the glossary as the model actually receives it, for a language that
    # has a pinned term where one exists.
    sample_lang = next(iter(LANGUAGE_TERM_OVERRIDES), 'es')
    context = {
        'stats': stats,
        'summary': stats['summary'],
        'languages': stats['languages'],
        'books': stats['books'],
        'api': stats['api'],
        'glossary': TRANSLATION_GLOSSARY,
        'overrides': LANGUAGE_TERM_OVERRIDES,
        'sample_lang': sample_lang,
        'sample_lang_name': SUPPORTED_LANGUAGES.get(sample_lang, sample_lang),
        'glossary_preview': build_glossary_section(sample_lang),
        'supported_languages': SUPPORTED_LANGUAGES,
    }
    return render(request, 'translation_dashboard.html', context)


def public_translation_coverage():
    """Translation coverage for the PUBLIC statistics page.

    Derived from nt_dashboard_stats() but deliberately stripped of every failure
    metric: readers should see what has been translated and how far along it is,
    not internal Gemini error counts. Nothing here exposes verses_err, notes_err,
    quota, API keys or the 'errors' state.
    """
    stats = nt_dashboard_stats()

    languages = []
    for e in stats['languages']:
        if e['state'] == 'absent':
            continue  # nothing to show for a language never started
        languages.append({
            'code': e['code'],
            'label': e['label'],
            'pct': e['pct'],
            'verses': e['verses_ok'],
            'notes': e['notes_ok'],
            'books': e['books_started'],
            # 'errors' is an internal state; publicly it is just in progress
            'state': 'complete' if e['state'] == 'complete' else 'in progress',
        })
    languages.sort(key=lambda x: (-x['pct'], x['label']))

    source_verses = stats['summary']['source_verses']
    books = []
    for b in stats['books']:
        src = b['source_verses'] or 0
        started = b['languages_started']
        books.append({
            'book': b['book'],
            'chapters': b['chapters'],
            'verses': src,
            'languages': started,
            'translated_verses': b['verses_ok'],
        })

    return {
        'summary': {
            'source_verses': source_verses,
            'books': stats['summary']['books'],
            'chapters': stats['summary']['chapters'],
            'languages_available': len(languages),
            'languages_total': stats['summary']['languages_total'],
            'translated_verses': stats['summary']['verses_ok'],
            'translated_notes': stats['summary']['notes_ok'],
        },
        'languages': languages,
        'books': books,
    }


@csrf_exempt
def translation_coverage_api(request):
    """Public JSON: which languages exist and how far along they are."""
    try:
        data = public_translation_coverage()
    except Exception:
        return JsonResponse({'status': 'error', 'message': 'Coverage unavailable'})
    response = JsonResponse({'status': 'ok', **data})
    response['Access-Control-Allow-Origin'] = '*'
    return response


def _prompt_config_payload():
    """Current editable prompt configuration, as a JSON-friendly dict."""
    from search.models import PromptRule, PromptGlossaryTerm
    return {
        'rules': {
            scope: list(
                PromptRule.objects.filter(scope=scope).order_by('order', 'id')
                .values('id', 'order', 'text', 'active')
            )
            for scope in ('chapter', 'footnote', 'both')
        },
        'glossary': [
            {
                'term': t.term,
                'sense': t.sense,
                'use_guidance': t.use_guidance,
                'avoid': t.avoid,
                'active': t.active,
                'order': t.order,
                'overrides': [
                    {'language_code': o.language_code, 'rendering': o.rendering,
                     'active': o.active}
                    for o in t.overrides.all().order_by('language_code')
                ],
            }
            for t in PromptGlossaryTerm.objects.order_by('order', 'term')
                                              .prefetch_related('overrides')
        ],
    }


@csrf_exempt
def prompt_config_api(request):
    """Read or replace the editable translation prompt configuration.

    GET  -> the current configuration plus a rendered preview.
    POST -> replace it wholesale from a JSON body.

    Auth-gated on both verbs: this determines what every future translation is
    asked to do, and the GET exposes the full instruction set.
    """
    import json as _json
    from django.db import transaction
    from search.models import PromptRule, PromptGlossaryTerm, PromptLanguageOverride
    from search.translation_utils import (
        build_glossary_section, build_language_awareness_section, build_rules_section,
    )

    if not request.user.is_authenticated:
        return JsonResponse(
            {'status': 'error', 'message': 'Sign in to view or edit the prompt configuration.'},
            status=403)

    if request.method == 'GET':
        lang = request.GET.get('lang') or 'pl'
        return JsonResponse({
            'status': 'ok',
            'config': _prompt_config_payload(),
            'preview': {
                'language': lang,
                'chapter_rules': build_rules_section('chapter'),
                'footnote_rules': build_rules_section('footnote'),
                'glossary': build_glossary_section(lang),
                'language_awareness': build_language_awareness_section(lang),
            },
            'languages': [{'code': c, 'label': l} for c, l in SUPPORTED_LANGUAGES.items()],
        })

    if request.method != 'POST':
        return JsonResponse({'status': 'error', 'message': 'GET or POST only'}, status=405)

    try:
        payload = _json.loads(request.body.decode('utf-8'))
    except Exception as exc:
        return JsonResponse({'status': 'error', 'message': f'Invalid JSON: {exc}'})

    # Validate everything BEFORE writing: a partially-applied prompt config would
    # be worse than a rejected one.
    errors = []
    rules = payload.get('rules') or {}
    if not isinstance(rules, dict):
        errors.append('"rules" must be an object keyed by scope.')
    else:
        for scope, items in rules.items():
            if scope not in ('chapter', 'footnote', 'both'):
                errors.append(f'Unknown rule scope "{scope}".')
            if not isinstance(items, list):
                errors.append(f'rules["{scope}"] must be a list.')
                continue
            for n, it in enumerate(items):
                if not isinstance(it, dict) or not str(it.get('text', '')).strip():
                    errors.append(f'rules["{scope}"][{n}] needs a non-empty "text".')

    glossary = payload.get('glossary')
    if glossary is None:
        glossary = []
    if not isinstance(glossary, list):
        errors.append('"glossary" must be a list.')
    else:
        seen = set()
        for n, g in enumerate(glossary):
            if not isinstance(g, dict):
                errors.append(f'glossary[{n}] must be an object.'); continue
            term = str(g.get('term', '')).strip()
            if not term:
                errors.append(f'glossary[{n}] needs a "term".')
            elif term in seen:
                errors.append(f'Duplicate glossary term "{term}".')
            else:
                seen.add(term)
            if not str(g.get('sense', '')).strip():
                errors.append(f'glossary[{n}] ("{term}") needs a "sense".')
            if not str(g.get('use_guidance', '')).strip():
                errors.append(f'glossary[{n}] ("{term}") needs "use_guidance".')
            for o in (g.get('overrides') or []):
                if not isinstance(o, dict) or not str(o.get('language_code', '')).strip():
                    errors.append(f'glossary[{n}] ("{term}") has an override with no language_code.')
                elif not str(o.get('rendering', '')).strip():
                    errors.append(
                        f'glossary[{n}] ("{term}") override "{o.get("language_code")}" needs a rendering.')

    total_rules = sum(len(v) for v in rules.values() if isinstance(v, list))
    if total_rules == 0:
        errors.append('Refusing to save: that would leave the prompt with no instructions.')

    if errors:
        return JsonResponse({'status': 'error', 'message': ' '.join(errors[:6]),
                             'errors': errors})

    with transaction.atomic():
        PromptRule.objects.all().delete()
        for scope, items in rules.items():
            for n, it in enumerate(items):
                PromptRule.objects.create(
                    scope=scope,
                    order=int(it.get('order') or n + 1),
                    text=str(it['text']).strip(),
                    active=bool(it.get('active', True)),
                )
        PromptGlossaryTerm.objects.all().delete()  # cascades to overrides
        for n, g in enumerate(glossary):
            term = PromptGlossaryTerm.objects.create(
                term=str(g['term']).strip(),
                sense=str(g['sense']).strip(),
                use_guidance=str(g['use_guidance']).strip(),
                avoid=str(g.get('avoid') or '').strip(),
                active=bool(g.get('active', True)),
                order=int(g.get('order') or n),
            )
            for o in (g.get('overrides') or []):
                PromptLanguageOverride.objects.create(
                    term=term,
                    language_code=str(o['language_code']).strip(),
                    rendering=str(o['rendering']).strip(),
                    active=bool(o.get('active', True)),
                )

    return JsonResponse({
        'status': 'ok',
        'message': f'Saved {total_rules} rule(s) and {len(glossary)} glossary term(s).',
        'config': _prompt_config_payload(),
    })
