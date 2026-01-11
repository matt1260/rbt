"""
Background Translation Worker

This module handles translation jobs in a background thread, ensuring:
1. Non-blocking operation - doesn't block the main Django app
2. Persistence - job state is stored in database, survives interruptions
3. Atomic progress - partial progress is saved incrementally
4. Thread-safe - uses database locking to prevent duplicate processing
"""

import threading
import logging
import traceback
from datetime import datetime
from django.utils import timezone
from django.db import transaction, close_old_connections

logger = logging.getLogger(__name__)

# Global worker thread reference
_worker_thread = None
_worker_lock = threading.Lock()


class TranslationWorker:
    """
    Background worker that processes translation jobs.
    Runs in a separate thread to avoid blocking the main app.
    """
    
    def __init__(self):
        self.running = False
        self._stop_event = threading.Event()
    
    def start(self):
        """Start the worker thread"""
        global _worker_thread, _worker_lock
        
        with _worker_lock:
            if _worker_thread is not None and _worker_thread.is_alive():
                logger.info("Worker already running")
                print("[WORKER] Worker already running")
                return
            
            self.running = True
            self._stop_event.clear()
            _worker_thread = threading.Thread(target=self._run, daemon=True)
            _worker_thread.start()
            logger.info("Translation worker started")
            print("[WORKER] Translation worker thread started")
    
    def stop(self):
        """Stop the worker thread gracefully"""
        self._stop_event.set()
        self.running = False
        logger.info("Translation worker stop requested")
    
    def _run(self):
        """Main worker loop"""
        from search.models import TranslationJob
        
        print("[WORKER] Worker loop starting...")
        
        while not self._stop_event.is_set():
            try:
                # Close old database connections before each iteration
                close_old_connections()
                
                # Look for pending jobs
                job = self._claim_job()
                
                if job:
                    print(f"[WORKER] Processing job: {job.job_id}")
                    logger.info(f"Processing job: {job.job_id}")
                    self._process_job(job)
                    print(f"[WORKER] Finished job: {job.job_id}")
                else:
                    # No jobs, wait a bit before checking again
                    self._stop_event.wait(timeout=2.0)
                    
            except Exception as e:
                print(f"[WORKER] Error: {e}")
                logger.error(f"Worker error: {e}")
                traceback.print_exc()
                # Wait before retrying
                self._stop_event.wait(timeout=5.0)
        
        print("[WORKER] Worker loop stopped")
        logger.info("Translation worker stopped")
    
    def _claim_job(self):
        """
        Atomically claim a pending or orphaned processing job.
        Uses database row locking to prevent race conditions.
        
        Also picks up 'processing' jobs that were started more than 5 minutes ago
        (likely orphaned due to server restart).
        """
        from search.models import TranslationJob
        from datetime import timedelta
        
        try:
            with transaction.atomic():
                # First, try to get a pending job
                job = TranslationJob.objects.select_for_update(skip_locked=True).filter(
                    status='pending'
                ).order_by('created_at').first()
                
                if job:
                    # Mark as processing
                    job.status = 'processing'
                    job.started_at = timezone.now()
                    job.save()
                    print(f"[WORKER] Claimed pending job: {job.job_id}")
                    return job
                
                # Check for orphaned processing jobs (started more than 5 min ago)
                stale_threshold = timezone.now() - timedelta(minutes=5)
                orphaned_job = TranslationJob.objects.select_for_update(skip_locked=True).filter(
                    status='processing',
                    started_at__lt=stale_threshold
                ).order_by('started_at').first()
                
                if orphaned_job:
                    print(f"[WORKER] Resuming orphaned job: {orphaned_job.job_id}")
                    # Reset the start time but keep the progress
                    orphaned_job.started_at = timezone.now()
                    orphaned_job.save()
                    return orphaned_job
                    
        except Exception as e:
            logger.error(f"Error claiming job: {e}")
            print(f"[WORKER] Error claiming job: {e}")
        
        return None
    
    def _process_job(self, job):
        """Process a single translation job"""
        from search.models import TranslationJob, VerseTranslation
        from search.views.chapter_views_part1 import get_results
        from search.views.footnote_views import get_footnote
        from search.translation_utils import SUPPORTED_LANGUAGES
        from translate.translator import old_testament_books, new_testament_books, book_abbreviations
        import re
        
        try:
            book = job.book
            chapter_num = job.chapter
            language = job.language_code
            
            print(f"[WORKER] Starting translation: {book} ch{chapter_num} to {language}")
            logger.info(f"Starting translation: {book} ch{chapter_num} to {language}")
            
            # Special handling for Joseph and Aseneth (storehouse)
            if book == "Joseph and Aseneth":
                # Translate book name first
                self._translate_book_name(book, language)
                
                verses_to_translate, footnotes_to_translate = self._extract_storehouse_content(
                    book, chapter_num, language
                )
                
                # Update job totals
                job.total_verses = len(verses_to_translate)
                job.total_footnotes = len(footnotes_to_translate)
                job.save()
                
                # Translate verses in batches
                if verses_to_translate:
                    self._translate_verses(job, verses_to_translate, book, chapter_num, language)
                
                # Mark job complete
                job.status = 'completed'
                job.completed_at = timezone.now()
                job.save()
                logger.info(f"Job {job.job_id} completed successfully")
                return
            
            # Get chapter data for standard books
            results = get_results(book, chapter_num, None, 'en')
            
            if not results:
                raise ValueError(f"No results found for {book} chapter {chapter_num}")
            
            # Translate book name first (verse=0, chapter=0)
            self._translate_book_name(book, language)
            
            # Collect verses to translate
            verses_to_translate = {}
            footnotes_to_translate = {}
            
            # Determine book type and extract content
            if book == 'Genesis':
                verses_to_translate, footnotes_to_translate = self._extract_genesis_content(
                    results, book, chapter_num, language
                )
            elif book in old_testament_books:
                verses_to_translate, footnotes_to_translate = self._extract_ot_content(
                    results, book, chapter_num, language
                )
            elif book in new_testament_books:
                verses_to_translate, footnotes_to_translate = self._extract_nt_content(
                    results, book, chapter_num, language
                )
            else:
                raise ValueError(f"Unknown book: {book}")
            
            # Update job totals
            job.total_verses = len(verses_to_translate)
            job.total_footnotes = len(footnotes_to_translate)
            job.save()
            
            print(f"[WORKER] {book} ch{chapter_num}: {len(verses_to_translate)} verses, {len(footnotes_to_translate)} footnotes to translate")
            logger.info(f"Job {job.job_id}: {len(verses_to_translate)} verses, {len(footnotes_to_translate)} footnotes")
            
            # Translate verses in batches
            if verses_to_translate:
                self._translate_verses(job, verses_to_translate, book, chapter_num, language)
            else:
                print(f"[WORKER] No verses to translate")
            
            # Translate footnotes in batches
            if footnotes_to_translate:
                print(f"[WORKER] Starting footnote translation for {len(footnotes_to_translate)} footnotes")
                self._translate_footnotes(job, footnotes_to_translate, book, chapter_num, language)
            else:
                print(f"[WORKER] No footnotes to translate")
            
            # Mark job complete
            job.status = 'completed'
            job.completed_at = timezone.now()
            job.save()
            
            logger.info(f"Job {job.job_id} completed successfully")
            
        except Exception as e:
            logger.error(f"Job {job.job_id} failed: {e}")
            traceback.print_exc()
            
            job.status = 'failed'
            job.error_message = str(e)
            job.completed_at = timezone.now()
            job.save()
    
    def _extract_storehouse_content(self, book, chapter_num, language):
        """Extract translatable content from Joseph and Aseneth (storehouse)"""
        from search.models import VerseTranslation
        from search.db_utils import get_db_connection
        
        verses_to_translate = {}
        footnotes_to_translate = {}  # No footnotes for now
        
        # Get existing translations
        existing_verses = set(VerseTranslation.objects.filter(
            book=book, chapter=chapter_num, language_code=language,
            footnote_id__isnull=True
        ).values_list('verse', flat=True))
        
        try:
            # Query joseph_aseneth database for this chapter
            with get_db_connection() as conn:
                with conn.cursor() as cursor:
                    cursor.execute("SET search_path TO joseph_aseneth")
                    cursor.execute(
                        """
                        SELECT verse, english
                        FROM aseneth
                        WHERE chapter = %s
                        ORDER BY verse
                        """,
                        (chapter_num,)
                    )
                    rows = cursor.fetchall()
                    
                    for verse_value, english_text in rows:
                        if verse_value and english_text:
                            verse_num = int(verse_value) if str(verse_value).isdigit() else 0
                            if verse_num > 0 and verse_num not in existing_verses:
                                verses_to_translate[verse_num] = english_text
        except Exception as e:
            print(f"[WORKER] Error extracting storehouse content: {e}")
            import traceback
            traceback.print_exc()
        
        return verses_to_translate, footnotes_to_translate
    
    def _extract_genesis_content(self, results, book, chapter_num, language):
        """Extract translatable content from Genesis"""
        from search.models import VerseTranslation
        from search.views import get_footnote
        import re
        
        verses_to_translate = {}
        footnotes_to_translate = {}
        
        rbt = results.get('rbt', [])
        
        # Get existing translations
        existing_verses = set(VerseTranslation.objects.filter(
            book=book, chapter=chapter_num, language_code=language,
            status='completed', footnote_id__isnull=True
        ).values_list('verse', flat=True))
        
        existing_footnotes = set(VerseTranslation.objects.filter(
            book=book, chapter=chapter_num, language_code=language,
            status='completed'
        ).exclude(footnote_id__isnull=True).values_list('footnote_id', flat=True))
        
        for verse_obj in rbt:
            verse_num = verse_obj.verse
            verse_text = verse_obj.rbt_reader  # Paraphrase text
            
            # Check if verse needs translation
            if verse_num not in existing_verses and verse_text:
                verses_to_translate[verse_num] = verse_text
            
            # Extract footnotes from HTML
            html_content = verse_obj.html or ''
            footnote_refs = re.findall(r'\?footnote=(\d+-\d+-\d+[a-zA-Z]?)', html_content)
            
            for fn_ref in footnote_refs:
                full_id = f"{book}-{fn_ref}"
                if full_id not in existing_footnotes:
                    fn_content = get_footnote(fn_ref, book)
                    if fn_content:
                        footnotes_to_translate[full_id] = fn_content
        
        return verses_to_translate, footnotes_to_translate
    
    def _extract_ot_content(self, results, book, chapter_num, language):
        """Extract translatable content from OT books (non-Genesis)"""
        from search.models import VerseTranslation
        from search.views import get_footnote
        import re
        
        verses_to_translate = {}
        footnotes_to_translate = {}
        
        html_rows = results.get('html', {})
        
        # Get existing translations
        existing_verses = set(VerseTranslation.objects.filter(
            book=book, chapter=chapter_num, language_code=language,
            status='completed', footnote_id__isnull=True
        ).values_list('verse', flat=True))
        
        existing_footnotes = set(VerseTranslation.objects.filter(
            book=book, chapter=chapter_num, language_code=language,
            status='completed'
        ).exclude(footnote_id__isnull=True).values_list('footnote_id', flat=True))
        
        for verse_key, value in html_rows.items():
            verse_num = int(verse_key) if verse_key.isdigit() else 0
            
            if isinstance(value, tuple) and len(value) >= 2:
                html_content = value[1]  # Paraphrase
            else:
                html_content = value
            
            if verse_num not in existing_verses and html_content:
                verses_to_translate[verse_num] = html_content
            
            # Extract footnotes
            if html_content:
                footnote_refs = re.findall(r'\?footnote=([^"&\s]+)', html_content)
                for fn_ref in footnote_refs:
                    full_id = f"{book}-{fn_ref}"
                    if full_id not in existing_footnotes:
                        fn_content = get_footnote(fn_ref, book)
                        if fn_content:
                            footnotes_to_translate[full_id] = fn_content
        
        return verses_to_translate, footnotes_to_translate
    
    def _extract_nt_content(self, results, book, chapter_num, language):
        """Extract translatable content from NT books"""
        from search.models import VerseTranslation
        from search.views import get_footnote
        from translate.translator import book_abbreviations
        from search.db_utils import execute_query
        import re
        
        verses_to_translate = {}
        footnotes_to_translate = {}
        
        chapter_rows = results.get('chapter_reader', [])
        book_abbrev = book_abbreviations.get(book, book)
        
        print(f"[WORKER NT] Extracting content for {book} (abbrev: {book_abbrev}) ch{chapter_num}")
        
        # Get existing translations
        existing_verses = set(VerseTranslation.objects.filter(
            book=book, chapter=chapter_num, language_code=language,
            status='completed', footnote_id__isnull=True
        ).values_list('verse', flat=True))
        
        existing_footnotes = set(VerseTranslation.objects.filter(
            book=book, chapter=chapter_num, language_code=language,
            status='completed'
        ).exclude(footnote_id__isnull=True).values_list('footnote_id', flat=True))
        
        print(f"[WORKER NT] Existing: {len(existing_verses)} verses, {len(existing_footnotes)} footnotes")
        
        for row in chapter_rows:
            bk, ch_num, vrs, html_verse = row
            verse_num = int(vrs)
            
            if verse_num not in existing_verses and html_verse:
                verses_to_translate[verse_num] = html_verse
            
            # Extract footnotes
            if html_verse:
                sup_texts = re.findall(r'<sup>(.*?)</sup>', html_verse)
                if sup_texts:
                    print(f"[WORKER NT] Verse {verse_num} has {len(sup_texts)} footnote refs: {sup_texts}")
                for sup_text in sup_texts:
                    full_id = f"{book}-{sup_text}"
                    if full_id not in existing_footnotes:
                        # Query footnote content
                        # Books starting with numbers have 'table_' prefix
                        abbrev_lower = book_abbrev.lower()
                        if abbrev_lower[0].isdigit():
                            table_name = f"table_{abbrev_lower}_footnotes"
                        else:
                            table_name = f"{abbrev_lower}_footnotes"
                        # Footnote IDs in DB use abbreviation format (e.g., '1Jo-1')
                        db_footnote_id = f"{book_abbrev}-{sup_text}"
                        print(f"[WORKER NT] Querying {table_name} for footnote_id={db_footnote_id}")
                        try:
                            result = execute_query(
                                f"SELECT footnote_html FROM new_testament.{table_name} WHERE footnote_id = %s",
                                (db_footnote_id,), fetch='one'
                            )
                            if result and result[0]:
                                footnotes_to_translate[full_id] = result[0]
                                print(f"[WORKER NT] Found footnote {full_id}")
                            else:
                                print(f"[WORKER NT] No result for footnote {sup_text}")
                        except Exception as e:
                            print(f"[WORKER NT] Error querying footnote {sup_text}: {e}")
        
        print(f"[WORKER NT] Extracted {len(verses_to_translate)} verses, {len(footnotes_to_translate)} footnotes to translate")
        return verses_to_translate, footnotes_to_translate
    
    def _translate_book_name(self, book, language):
        """Translate book name and save as verse=0, chapter=0"""
        from search.models import VerseTranslation
        from search.translation_utils import translate_chapter_batch, SUPPORTED_LANGUAGES
        from search.rbt_titles import rbt_books
        import re
        
        # Skip if already translated
        existing = VerseTranslation.objects.filter(
            book=book, chapter=0, verse=0, language_code=language,
            status='completed', footnote_id__isnull=True
        ).first()
        
        if existing:
            print(f"[WORKER] Book name '{book}' already translated to {language}")
            return
        
        # Get English book name (with space between number and letters)
        display_book = re.sub(r'(\d+)([a-zA-Z]+)', r'\1 \2', book)
        english_name = rbt_books.get(display_book, display_book)
        
        print(f"[WORKER] Translating book name '{english_name}' ({book}) to {language}")
        
        try:
            # Use batch translation with verse=0 to trigger book name translation logic
            # This function rotates through multiple API keys automatically
            result = translate_chapter_batch({0: english_name}, language)
            translated_name = result.get(0, '')
            
            # Check if translation was successful (not an error message)
            if translated_name and not translated_name.startswith('[Translation'):
                # Save translation
                VerseTranslation.objects.create(
                    book=book,
                    chapter=0,
                    verse=0,
                    language_code=language,
                    verse_text=translated_name,
                    status='completed'
                )
                print(f"[WORKER] Book name translated: '{english_name}' -> '{translated_name}'")
            else:
                print(f"[WORKER] Failed to translate book name: {translated_name}")
        except Exception as e:
            print(f"[WORKER] Error translating book name: {e}")
            logger.error(f"Error translating book name {book} to {language}: {e}")
    
    def _translate_verses(self, job, verses_to_translate, book, chapter_num, language):
        """Translate verses and save incrementally"""
        from search.models import VerseTranslation
        from search.translation_utils import translate_chapter_batch, SUPPORTED_LANGUAGES
        
        if not verses_to_translate:
            return
        
        # Process in smaller batches for incremental progress
        batch_size = 10
        verse_items = list(verses_to_translate.items())
        
        for i in range(0, len(verse_items), batch_size):
            batch = dict(verse_items[i:i + batch_size])
            
            try:
                print(f"[WORKER] Translating {book} {chapter_num} verses batch {i//batch_size + 1}/{(len(verse_items)-1)//batch_size + 1}")
                translated = translate_chapter_batch(batch, language)
                
                # Save each translation
                for verse_num, translated_text in translated.items():
                    VerseTranslation.objects.update_or_create(
                        book=book,
                        chapter=chapter_num,
                        verse=verse_num,
                        language_code=language,
                        footnote_id=None,
                        defaults={
                            'verse_text': translated_text,
                            'status': 'completed',
                            'generated_by': 'gemini-3-flash-preview'
                        }
                    )
                    
                    # Update progress
                    job.translated_verses += 1
                    job.save()
                    
            except Exception as e:
                logger.error(f"Error translating verses batch: {e}")
                raise
    
    def _translate_footnotes(self, job, footnotes_to_translate, book, chapter_num, language):
        """Translate footnotes and save incrementally"""
        from search.models import VerseTranslation
        from search.translation_utils import translate_footnotes_batch, SUPPORTED_LANGUAGES
        
        if not footnotes_to_translate:
            return
        
        # Process in smaller batches
        batch_size = 12
        footnote_items = list(footnotes_to_translate.items())
        
        for i in range(0, len(footnote_items), batch_size):
            batch = dict(footnote_items[i:i + batch_size])
            
            try:
                print(f"[WORKER] Translating {book} {chapter_num} footnotes batch {i//batch_size + 1}/{(len(footnote_items)-1)//batch_size + 1}")
                translated = translate_footnotes_batch(batch, language)
                
                # Save each translation
                for footnote_id, translated_text in translated.items():
                    VerseTranslation.objects.update_or_create(
                        book=book,
                        chapter=chapter_num,
                        verse=0,  # Footnotes stored with verse=0
                        language_code=language,
                        footnote_id=footnote_id,
                        defaults={
                            'footnote_text': translated_text,
                            'status': 'completed',
                            'generated_by': 'gemini-3-flash-preview'
                        }
                    )
                    
                    # Update progress
                    job.translated_footnotes += 1
                    job.save()
                    
            except Exception as e:
                logger.error(f"Error translating footnotes batch: {e}")
                raise


# Singleton worker instance
_worker_instance = None


def get_worker():
    """Get or create the singleton worker instance"""
    global _worker_instance
    if _worker_instance is None:
        _worker_instance = TranslationWorker()
    return _worker_instance


def ensure_worker_running():
    """Ensure the background worker is running"""
    worker = get_worker()
    worker.start()


def create_translation_job(book, chapter, language_code):
    """
    Create a new translation job and ensure worker is running.
    Returns the job instance.
    """
    import uuid
    from search.models import TranslationJob
    
    # Check if there's already a pending/processing job for this chapter
    existing = TranslationJob.objects.filter(
        book=book,
        chapter=chapter,
        language_code=language_code,
        status__in=['pending', 'processing']
    ).first()
    
    if existing:
        return existing
    
    # Create new job
    job = TranslationJob.objects.create(
        job_id=str(uuid.uuid4()),
        book=book,
        chapter=chapter,
        language_code=language_code,
        status='pending'
    )
    
    # Ensure worker is running
    ensure_worker_running()
    
    return job


def get_job_status(job_id):
    """Get the status of a translation job with queue information"""
    from search.models import TranslationJob
    
    try:
        job = TranslationJob.objects.get(job_id=job_id)
        
        # Calculate queue position if pending
        queue_position = None
        current_job = None
        
        if job.status == 'pending':
            # Count how many jobs are ahead in queue (older pending jobs)
            queue_position = TranslationJob.objects.filter(
                status='pending',
                created_at__lt=job.created_at
            ).count() + 1  # +1 because there's a processing job ahead
            
            # Get the currently processing job
            processing = TranslationJob.objects.filter(status='processing').first()
            if processing:
                current_job = {
                    'book': processing.book,
                    'chapter': processing.chapter,
                    'progress': processing.progress_percent
                }
        
        return {
            'job_id': job.job_id,
            'status': job.status,
            'progress': job.progress_percent,
            'total_verses': job.total_verses,
            'translated_verses': job.translated_verses,
            'total_footnotes': job.total_footnotes,
            'translated_footnotes': job.translated_footnotes,
            'error': job.error_message,
            'queue_position': queue_position,
            'current_job': current_job,
            'book': job.book,
            'chapter': job.chapter,
        }
    except TranslationJob.DoesNotExist:
        return None
