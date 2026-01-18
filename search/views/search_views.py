"""
Comprehensive Bible search functionality.

Supports searching across:
- Old Testament verses (Genesis + old_testament.ot)
- Old Testament Hebrew text (old_testament.hebrewdata, ot_consonantal)
- New Testament verses (new_testament.nt)
- New Testament Greek text (rbt_greek.strongs_greek)
- Footnotes (all book footnote tables)
- Bible references (using pythonbible)
"""

import logging
import re
from django.http import JsonResponse
from django.shortcuts import redirect, render
from django.views.decorators.http import require_GET
from django.db.models import Q
import pythonbible as bible

from search.models import Genesis, GenesisFootnotes, VerseTranslation
from search.db_utils import execute_query, get_db_connection
from search.views.utils import detect_script, strip_hebrew_vowels, highlight_match
from translate.translator import book_abbreviations, convert_book_name

logger = logging.getLogger(__name__)


def search_results_page(request):
    """
    Full search results page with pagination.
    Renders the template which uses JavaScript to fetch results from the API.
    
    Query params:
    - q: Search query
    - scope: 'all', 'ot', 'nt', 'hebrew', 'greek', 'footnotes'
    - page: Page number for pagination
    """
    query = request.GET.get('q', '').strip()
    scope = request.GET.get('scope', 'all').lower()
    search_type = request.GET.get('type', 'keyword')
    page = max(int(request.GET.get('page', 1)), 1)
    
    if not query:
        return redirect('/search/')
    
    context = {
        'query': query,
        'scope': scope,
        'search_type': search_type,
        'page': page,
    }
    return render(request, 'search_results_full.html', context)


@require_GET
def search_api(request):
    """
    Comprehensive Bible Search API.
    
    Searches across all Bible texts, Hebrew/Greek lexicons, and footnotes.
    Auto-detects script type (Hebrew, Greek, Latin) and reference format.
    
    Query params:
    - q: Search query (required, min 2 characters)
    - scope: 'all', 'ot', 'nt', 'hebrew', 'greek', 'footnotes' (default: 'all')
    - type: 'keyword', 'reference', 'exact' (default: auto-detect)
    - limit: Max results per category (default: 20, max: 100)
    - page: Page number for pagination (default: 1)
    
    Returns JSON with:
    - results: Dict with arrays for each category (ot_verses, nt_verses, etc.)
    - counts: Total count per category
    - total: Overall result count
    - script_detected: Which scripts found in query (hebrew/greek/latin)
    """
    query = request.GET.get('q', '').strip()
    scope = request.GET.get('scope', 'all').lower()
    requested_type = request.GET.get('type', 'auto')
    search_type = requested_type
    language = request.GET.get('lang', '').strip().lower()
    translations_only = request.GET.get('translations_only') == '1' or scope == 'translations'
    limit = min(int(request.GET.get('limit', 20)), 100)
    page = max(int(request.GET.get('page', 1)), 1)
    offset = (page - 1) * limit
    
    if not query or len(query) < 2:
        return JsonResponse({
            'error': 'Query must be at least 2 characters',
            'results': {},
            'total': 0
        })
    
    # Detect script type
    script = detect_script(query)
    has_non_ascii = bool(re.search(r'[^\x00-\x7F]', query))
    if has_non_ascii and not script['hebrew'] and not script['greek'] and scope == 'all':
        translations_only = True
    
    # Cache parsed references to avoid duplicate parsing
    parsed_refs = None

    # Auto-detect search type
    if search_type == 'auto':
        # Check if it looks like a reference
        try:
            parsed_refs = bible.get_references(query)
            if parsed_refs:
                search_type = 'reference'
            else:
                search_type = 'keyword'
        except:
            search_type = 'keyword'
    
    results = {
        'ot_verses': [],
        'ot_hebrew': [],
        'nt_verses': [],
        'nt_greek': [],
        'footnotes': [],
        'storehouse': [],
        'references': [],
        'translations': []
    }
    
    counts = {
        'ot_verses': 0,
        'ot_hebrew': 0,
        'nt_verses': 0,
        'nt_greek': 0,
        'footnotes': 0,
        'storehouse': 0,
        'references': 0,
        'translations': 0
    }

    def search_translations_only():
        qs = VerseTranslation.objects.filter(verse_text__icontains=query).exclude(verse_text__isnull=True).exclude(verse_text__exact='')
        if language and language != 'en':
            qs = qs.filter(language_code=language)

        counts['translations'] = qs.count()
        rows = qs.order_by('book', 'chapter', 'verse')[offset:offset + limit]
        for row in rows:
            lang_code = row.language_code or language or 'en'
            results['translations'].append({
                'type': 'translation',
                'book': row.book,
                'chapter': row.chapter,
                'verse': row.verse,
                'language': lang_code,
                'text': highlight_match(row.verse_text or '', query),
                'url': f'/?book={row.book}&chapter={row.chapter}&verse={row.verse}&lang={lang_code}'
            })

        return JsonResponse({
            'query': query,
            'scope': 'translations',
            'type': search_type,
            'script_detected': script,
            'results': results,
            'counts': counts,
            'total': counts['translations'],
            'page': page,
            'limit': limit,
            'lang': language or None,
            'translations_only': True,
            'has_more': counts['translations'] > len(results['translations'])
        })
    
    # Reference search
    if search_type == 'reference':
        try:
            # Use cached refs if available (from auto-detection), otherwise parse
            refs = parsed_refs if parsed_refs is not None else bible.get_references(query)
            if refs:
                ref = refs[0]
                book_name = ref.book.name
                
                # Normalize book name
                if book_name == 'SONG_OF_SONGS':
                    book_name = 'Song of Solomon'
                elif book_name.endswith('_1'):
                    book_name = '1 ' + book_name[:-2].capitalize()
                elif book_name.endswith('_2'):
                    book_name = '2 ' + book_name[:-2].capitalize()
                else:
                    book_name = book_name.replace('_', ' ').title()
                
                results['references'].append({
                    'type': 'reference',
                    'book': book_name,
                    'chapter': ref.start_chapter,
                    'verse': ref.start_verse,
                    'url': f'/?book={book_name}&chapter={ref.start_chapter}' + 
                           (f'&verse={ref.start_verse}' if ref.start_verse else ''),
                    'display': f'{book_name} {ref.start_chapter}' + 
                              (f':{ref.start_verse}' if ref.start_verse else '')
                })
                counts['references'] = 1
        except Exception as e:
            pass  # Not a valid reference, continue with keyword search

    # If the caller explicitly requested reference mode, avoid expensive keyword searches
    if requested_type == 'reference':
        total_results = counts['references']
        return JsonResponse({
            'query': query,
            'scope': scope,
            'type': search_type,
            'script_detected': script,
            'results': results,
            'counts': counts,
            'total': total_results,
            'page': page,
            'limit': limit,
            'lang': language or None,
            'translations_only': translations_only,
            'has_more': counts['references'] > len(results['references'])
        })
    
    # Translation-only fast path (non-English query or explicit request)
    if translations_only:
        return search_translations_only()

    # Keyword search
    if search_type == 'keyword' or not results['references']:
        
        # Prepare query variations
        query_stripped = strip_hebrew_vowels(query) if script['hebrew'] else query
        
        # =================================================================
        # SEARCH OLD TESTAMENT VERSES (old_testament.ot)
        # =================================================================
        if scope in ['all', 'ot', 'english']:
            try:
                # Search in Genesis (Django ORM) - html=Hebrew Literal, rbt_reader=Paraphrase
                genesis_results = Genesis.objects.filter(
                    Q(html__icontains=query) | 
                    Q(rbt_reader__icontains=query) |
                    Q(hebrew__icontains=query)
                )[:limit]
                
                for result in genesis_results:
                    # Determine which field matched and set version accordingly
                    if result.html and query.lower() in result.html.lower():
                        text = result.html
                        version = 'Hebrew Literal'
                    elif result.rbt_reader and query.lower() in result.rbt_reader.lower():
                        text = result.rbt_reader
                        version = 'Paraphrase'
                    elif result.hebrew and query.lower() in result.hebrew.lower():
                        text = result.hebrew
                        version = 'Hebrew Text'
                    else:
                        text = result.html or result.rbt_reader or ''
                        version = 'Hebrew Literal' if result.html else 'Paraphrase'
                    
                    results['ot_verses'].append({
                        'type': 'ot_verse',
                        'source': 'genesis',
                        'book': 'Genesis',
                        'chapter': result.chapter,
                        'verse': result.verse,
                        'text': highlight_match(text, query),
                        'version': version,
                        'url': f'/?book=Genesis&chapter={result.chapter}&verse={result.verse}'
                    })
                
                # Search in old_testament.ot
                ot_rows = execute_query(
                    """
                    SELECT book, chapter, verse, html, literal 
                    FROM old_testament.ot 
                    WHERE html ILIKE %s OR literal ILIKE %s
                    ORDER BY book, chapter, verse
                    LIMIT %s OFFSET %s
                    """,
                    (f'%{query}%', f'%{query}%', limit, offset),
                    fetch='all'
                )
                
                for row in ot_rows or []:
                    # Convert book abbreviation to full name, fallback to abbreviation if not found
                    book_abbrev = row[0] if row[0] else ''
                    book_name = convert_book_name(book_abbrev)
                    if not book_name:
                        # Fallback: use the abbreviation itself if conversion fails
                        book_name = book_abbrev
                    
                    # row[3]=html (Paraphrase), row[4]=literal (RBT Interlinear)
                    # Determine which field matched
                    if row[3] and query.lower() in row[3].lower():
                        text = row[3]
                        version = 'Paraphrase'
                    elif row[4] and query.lower() in row[4].lower():
                        text = row[4]
                        version = 'RBT Interlinear'
                    else:
                        text = row[3] or row[4] or ''
                        version = 'Paraphrase' if row[3] else 'RBT Interlinear'
                    
                    results['ot_verses'].append({
                        'type': 'ot_verse',
                        'source': 'old_testament.ot',
                        'book': book_name,
                        'chapter': row[1],
                        'verse': row[2],
                        'text': highlight_match(text, query),
                        'version': version,
                        'url': f'/?book={book_name}&chapter={row[1]}&verse={row[2]}'
                    })
                
                # Get count
                count_result = execute_query(
                    "SELECT COUNT(*) FROM old_testament.ot WHERE html ILIKE %s OR literal ILIKE %s",
                    (f'%{query}%', f'%{query}%'),
                    fetch='one'
                )
                counts['ot_verses'] = (count_result[0] if count_result else 0) + len(genesis_results)
                
            except Exception as e:
                print(f"OT verse search error: {e}")
        
        # =================================================================
        # SEARCH HEBREW DATA (old_testament.hebrewdata)
        # =================================================================
        if scope in ['all', 'ot', 'hebrew'] and (script['hebrew'] or script['latin']):
            try:
                # Search Hebrew with and without vowels
                hebrew_rows = execute_query(
                    """
                    SELECT id, Ref, Eng, combined_heb, combined_heb_niqqud, morphology, Strongs
                    FROM old_testament.hebrewdata 
                    WHERE combined_heb ILIKE %s 
                       OR combined_heb_niqqud ILIKE %s 
                       OR Eng ILIKE %s
                    ORDER BY Ref
                    LIMIT %s OFFSET %s
                    """,
                    (f'%{query_stripped}%', f'%{query}%', f'%{query}%', limit, offset),
                    fetch='all'
                )
                
                for row in hebrew_rows or []:
                    ref_parts = (row[1] or '').split('.')
                    book_code = ref_parts[0] if len(ref_parts) > 0 else ''
                    chapter = ref_parts[1] if len(ref_parts) > 1 else ''
                    verse = ref_parts[2].split('-')[0] if len(ref_parts) > 2 else ''
                    book_name = convert_book_name(book_code) if book_code else ''
                    if not book_name and book_code:
                        # Fallback: use abbreviation if conversion fails
                        book_name = book_code
                    
                    results['ot_hebrew'].append({
                        'type': 'hebrew_word',
                        'source': 'old_testament.hebrewdata',
                        'id': row[0],
                        'reference': row[1],
                        'book': book_name,
                        'chapter': chapter,
                        'verse': verse,
                        'english': row[2],
                        'hebrew': row[3],
                        'hebrew_niqqud': row[4],
                        'morphology': row[5],
                        'strongs': row[6],
                        'url': f'/?book={book_name}&chapter={chapter}&verse={verse}' if book_name else None
                    })
                
                count_result = execute_query(
                    """SELECT COUNT(*) FROM old_testament.hebrewdata 
                       WHERE combined_heb ILIKE %s OR combined_heb_niqqud ILIKE %s OR Eng ILIKE %s""",
                    (f'%{query_stripped}%', f'%{query}%', f'%{query}%'),
                    fetch='one'
                )
                counts['ot_hebrew'] = count_result[0] if count_result else 0
                
            except Exception as e:
                print(f"Hebrew search error: {e}")
        
        # =================================================================
        # SEARCH OLD TESTAMENT CONSONANTAL (old_testament.ot_consonantal)
        # =================================================================
        if scope in ['all', 'ot', 'hebrew'] and script['hebrew']:
            try:
                with get_db_connection() as conn:
                    cursor = conn.cursor()
                    cursor.execute("SET search_path TO old_testament")
                    cursor.execute(
                        """
                        SELECT ref, hebrew 
                        FROM ot_consonantal 
                        WHERE hebrew ILIKE %s
                        ORDER BY ref
                        LIMIT %s OFFSET %s
                        """,
                        (f'%{query_stripped}%', limit, offset)
                    )
                    consonantal_rows = cursor.fetchall()
                
                for row in consonantal_rows or []:
                    # Parse ref like "Gen.1.1" into parts
                    ref = row[0] if row[0] else ''
                    ref_parts = ref.split('.')
                    book_abbrev = ref_parts[0] if len(ref_parts) > 0 else ''
                    chapter = ref_parts[1] if len(ref_parts) > 1 else ''
                    verse = ref_parts[2] if len(ref_parts) > 2 else ''
                    book_name = convert_book_name(book_abbrev)
                    
                    results['ot_hebrew'].append({
                        'type': 'consonantal_text',
                        'source': 'old_testament.ot_consonantal',
                        'book': book_name,
                        'chapter': chapter,
                        'verse': verse,
                        'hebrew': row[1],
                        'text': highlight_match(row[1], query_stripped),
                        'url': f'/?book={book_name}&chapter={chapter}&verse={verse}'
                    })
                    
            except Exception as e:
                print(f"Consonantal search error: {e}")
        
        # =================================================================
        # SEARCH NEW TESTAMENT VERSES
        # =================================================================
        if scope in ['all', 'nt', 'english']:
            try:
                nt_rows = execute_query(
                    """
                    SELECT book, chapter, startVerse, rbt, verseText
                    FROM new_testament.nt 
                    WHERE rbt ILIKE %s OR verseText ILIKE %s
                    ORDER BY book, chapter, startVerse
                    LIMIT %s OFFSET %s
                    """,
                    (f'%{query}%', f'%{query}%', limit, offset),
                    fetch='all'
                )
                
                for row in nt_rows or []:
                    book_abbrev = row[0] if row[0] else ''
                    book_name = convert_book_name(book_abbrev)
                    if not book_name:
                        # Fallback: use abbreviation if conversion fails
                        book_name = book_abbrev
                    text = row[3] or row[4] or ''
                    results['nt_verses'].append({
                        'type': 'nt_verse',
                        'source': 'new_testament.nt',
                        'book': book_name,
                        'chapter': row[1],
                        'verse': row[2],
                        'text': highlight_match(text, query),
                        'url': f'/?book={book_name}&chapter={row[1]}&verse={row[2]}'
                    })
                
                count_result = execute_query(
                    "SELECT COUNT(*) FROM new_testament.nt WHERE rbt ILIKE %s OR verseText ILIKE %s",
                    (f'%{query}%', f'%{query}%'),
                    fetch='one'
                )
                counts['nt_verses'] = count_result[0] if count_result else 0
                
            except Exception as e:
                print(f"NT verse search error: {e}")
        
        # =================================================================
        # SEARCH NEW TESTAMENT GREEK (rbt_greek.strongs_greek)
        # =================================================================
        if scope in ['all', 'nt', 'greek'] and (script['greek'] or script['latin']):
            try:
                greek_rows = execute_query(
                    """
                    SELECT verse, strongs, translit, lemma, english, morph, morph_desc
                    FROM rbt_greek.strongs_greek 
                    WHERE lemma ILIKE %s OR english ILIKE %s
                    ORDER BY verse
                    LIMIT %s OFFSET %s
                    """,
                    (f'%{query}%', f'%{query}%', limit, offset),
                    fetch='all'
                )
                
                for row in greek_rows or []:
                    # Parse reference like "Mat.1.1-01" into parts
                    verse_ref = row[0] if row[0] else ''
                    parts = verse_ref.split('.')
                    book_abbrev = parts[0] if len(parts) > 0 else ''
                    chapter_num = parts[1] if len(parts) > 1 else ''
                    verse_part = parts[2].split('-')[0] if len(parts) > 2 else ''
                    book_name = convert_book_name(book_abbrev)
                    
                    results['nt_greek'].append({
                        'type': 'greek_word',
                        'source': 'rbt_greek.strongs_greek',
                        'book': book_name,
                        'chapter': chapter_num,
                        'verse': verse_part,
                        'reference': verse_ref,
                        'strongs': row[1],
                        'translit': row[2],
                        'lemma': row[3],
                        'english': row[4],
                        'morphology': row[5],
                        'morph_desc': row[6],
                        'url': f'/?book={book_name}&chapter={chapter_num}&verse={verse_part}'
                    })
                
                count_result = execute_query(
                    "SELECT COUNT(*) FROM rbt_greek.strongs_greek WHERE lemma ILIKE %s OR english ILIKE %s",
                    (f'%{query}%', f'%{query}%'),
                    fetch='one'
                )
                counts['nt_greek'] = count_result[0] if count_result else 0
                
            except Exception as e:
                print(f"Greek search error: {e}")
        
        # =================================================================
        # SEARCH FOOTNOTES
        # =================================================================
        if scope in ['all', 'footnotes']:
            try:
                # Search Genesis footnotes (Django ORM)
                genesis_footnotes = GenesisFootnotes.objects.filter(
                    footnote_html__icontains=query
                )[:limit]
                
                for fn in genesis_footnotes:
                    parts = fn.footnote_id.split('-') if fn.footnote_id else []
                    chapter = parts[0] if len(parts) > 0 else ''
                    verse = parts[1] if len(parts) > 1 else ''
                    results['footnotes'].append({
                        'type': 'footnote',
                        'source': 'genesis_footnotes',
                        'book': 'Genesis',
                        'footnote_id': fn.footnote_id,
                        'chapter': chapter,
                        'verse': verse,
                        'text': highlight_match(fn.footnote_html, query),
                        'url': f'/?book=Genesis&chapter={chapter}&verse={verse}'
                    })
                
                # Search OT hebrewdata footnotes
                ot_footnotes = execute_query(
                    """
                    SELECT Ref, footnote 
                    FROM old_testament.hebrewdata 
                    WHERE footnote ILIKE %s AND footnote IS NOT NULL AND footnote != ''
                    ORDER BY Ref
                    LIMIT %s OFFSET %s
                    """,
                    (f'%{query}%', limit, offset),
                    fetch='all'
                )
                
                for row in ot_footnotes or []:
                    ref_parts = (row[0] or '').split('.')
                    book_code = ref_parts[0] if len(ref_parts) > 0 else ''
                    chapter = ref_parts[1] if len(ref_parts) > 1 else ''
                    verse = ref_parts[2].split('-')[0] if len(ref_parts) > 2 else ''

                    # Try to convert abbreviation to full book name
                    book_name = convert_book_name(book_code) if book_code else ''

                    # If conversion failed, attempt to find the book column from old_testament.ot
                    if not book_name and book_code:
                        try:
                            sample = execute_query(
                                "SELECT book FROM old_testament.ot WHERE Ref LIKE %s LIMIT 1",
                                (f'{book_code}.%',),
                                fetch='one'
                            )
                            sample_book = sample[0] if sample else None
                            if sample_book:
                                book_name = convert_book_name(sample_book) or sample_book
                                # Log the prefix mismatch for debugging
                                try:
                                    logger.warning(
                                        'OT footnote ref prefix mismatch: ref prefix %s maps to book column %s',
                                        book_code, sample_book
                                    )
                                except Exception:
                                    pass
                        except Exception:
                            # Ignore DB lookup errors and fall back
                            pass

                    # Final fallback to abbreviation itself if nothing else worked
                    if not book_name:
                        book_name = book_code or ''

                    results['footnotes'].append({
                        'type': 'footnote',
                        'source': 'old_testament.hebrewdata',
                        'book': book_name,
                        'reference': row[0],
                        'chapter': chapter,
                        'verse': verse,
                        'text': highlight_match(row[1], query),
                        'url': f'/?book={book_name}&chapter={chapter}&verse={verse}'
                    })
                
                # Search NT footnotes (all book_footnotes tables)
                footnote_tables = execute_query(
                    """
                    SELECT table_name FROM information_schema.tables 
                    WHERE table_schema = 'new_testament' AND table_name LIKE '%_footnotes'
                    """,
                    fetch='all'
                )
                
                for table_row in footnote_tables or []:
                    table_name = table_row[0]
                    book_code = table_name.replace('_footnotes', '').replace('table_', '')
                    
                    # Check if vrs column exists in this table
                    has_vrs = False
                    try:
                        col_check = execute_query(
                            """
                            SELECT column_name FROM information_schema.columns 
                            WHERE table_schema = 'new_testament' 
                            AND table_name = %s 
                            AND column_name = 'vrs'
                            """,
                            (table_name,),
                            fetch='one'
                        )
                        has_vrs = col_check is not None
                    except Exception:
                        pass
                    
                    # Query with or without vrs column based on what exists
                    if has_vrs:
                        nt_fn_rows = execute_query(
                            f"""
                            SELECT footnote_id, footnote_html, vrs 
                            FROM new_testament.{table_name} 
                            WHERE footnote_html ILIKE %s
                            LIMIT %s
                            """,
                            (f'%{query}%', limit // 5),
                            fetch='all'
                        )
                    else:
                        nt_fn_rows = execute_query(
                            f"""
                            SELECT footnote_id, footnote_html 
                            FROM new_testament.{table_name} 
                            WHERE footnote_html ILIKE %s
                            LIMIT %s
                            """,
                            (f'%{query}%', limit // 5),
                            fetch='all'
                        )
                    
                    for fn_row in nt_fn_rows or []:
                        footnote_id = fn_row[0] or ''
                        vrs_value = fn_row[2] if len(fn_row) > 2 else None
                        parts = footnote_id.split('-')

                        # Get book abbreviation from footnote_id (e.g., 'Mat-8b' -> 'Mat')
                        book_abbrev = parts[0] if parts and any(c.isalpha() for c in parts[0]) else book_code
                        
                        # Try to map to full book name - handle numbered books (1ti, 2jo, 3jo)
                        # Try multiple variations: as-is, capitalized, title case, uppercase
                        book_name = None
                        for variant in [book_abbrev, book_abbrev.capitalize(), book_abbrev.title(), book_abbrev.upper()]:
                            book_name = convert_book_name(variant)
                            if book_name:
                                break
                        
                        # If still no match, use the abbreviation with proper capitalization
                        if not book_name:
                            # For numbered books like "1ti", capitalize the letters: "1Ti"
                            if book_abbrev and book_abbrev[0].isdigit():
                                book_name = book_abbrev[0] + book_abbrev[1:].capitalize()
                            else:
                                book_name = book_abbrev.capitalize()
                        
                        # For NT footnotes, we need to find which verse references this footnote
                        # Format is: Mat-8b -> need to find verse with ?footnote=2-11-8b&book=Mat
                        footnote_number = parts[-1] if len(parts) > 1 else parts[0] if parts else ''
                        
                        # First try the vrs column if it exists
                        chapter = ''
                        verse = ''
                        if vrs_value:
                            # vrs format is typically "chapter:verse" like "2:11"
                            vrs_parts = str(vrs_value).split(':')
                            if len(vrs_parts) == 2:
                                chapter = vrs_parts[0].strip()
                                verse = vrs_parts[1].strip()
                        
                        # If vrs didn't provide the info, search for the footnote reference in NT verses
                        if not chapter or not verse:
                            try:
                                # Try multiple search patterns to find the verse
                                # Start with specific patterns, then get more general
                                patterns = [
                                    f'%footnote=%-{footnote_number}&book={book_abbrev}%',  # Full pattern: ?footnote=2-11-8b&book=Mat
                                    f'%footnote=%-%{footnote_number}%',  # Relaxed: ?footnote=X-X-8b
                                    f'%>{footnote_number}</sup>%',  # Superscript: >8b</sup>
                                    f'%<sup>{footnote_number}</sup>%',  # Full superscript tag
                                ]
                                
                                for pattern in patterns:
                                    verse_search = execute_query(
                                        f"""
                                        SELECT chapter, startverse 
                                        FROM new_testament.nt 
                                        WHERE book = %s AND rbt LIKE %s
                                        LIMIT 1
                                        """,
                                        (book_abbrev, pattern),
                                        fetch='one'
                                    )
                                    if verse_search:
                                        chapter = str(verse_search[0])
                                        verse = str(verse_search[1])
                                        break
                            except Exception:
                                pass
                        
                        # Only include footnotes where we found the chapter and verse
                        # Skip footnotes with incomplete location information
                        if chapter and verse:
                            url = f'/?book={book_name}&chapter={chapter}&verse={verse}'
                            reference = f'{book_name} {chapter}:{verse}'
                            
                            results['footnotes'].append({
                                'type': 'footnote',
                                'source': f'new_testament.{table_name}',
                                'book': book_name,
                                'footnote_id': footnote_id,
                                'chapter': chapter,
                                'verse': verse,
                                'reference': reference,
                                'text': highlight_match(fn_row[1], query),
                                'url': url
                            })
                
                counts['footnotes'] = len(results['footnotes'])
                
            except Exception as e:
                print(f"Footnote search error: {e}")

        # =================================================================
        # SEARCH JOSEPH AND ASENETH (joseph_aseneth.aseneth)
        # =================================================================
        if scope in ['all', 'storehouse']:
            try:
                with get_db_connection() as conn:
                    with conn.cursor() as cursor:
                        cursor.execute("SET search_path TO joseph_aseneth")
                        cursor.execute(
                            """
                            SELECT chapter, verse, english, greek
                            FROM aseneth
                            WHERE english ILIKE %s OR greek ILIKE %s
                            ORDER BY chapter, verse
                            LIMIT %s OFFSET %s
                            """,
                            (f'%{query}%', f'%{query}%', limit, offset)
                        )
                        as_rows = cursor.fetchall()

                        for row in as_rows or []:
                            chapter = str(row[0]) if row[0] is not None else ''
                            verse = str(row[1]) if row[1] is not None else ''
                            english = row[2] or ''
                            greek = row[3] or ''

                            # Prefer English snippet when available, otherwise Greek
                            text_field = english if query.lower() in (english or '').lower() else greek

                            results['storehouse'].append({
                                'type': 'storehouse_verse',
                                'source': 'joseph_aseneth.aseneth',
                                'book': 'Joseph and Aseneth',
                                'chapter': chapter,
                                'verse': verse,
                                'reference': f'Joseph and Aseneth {chapter}' + (f":{verse}" if verse else ''),
                                'text': highlight_match(text_field, query),
                                # Use canonical storehouse URL (no verse arg)
                                'url': f'/aseneth/?chapter={chapter}'
                            })

                        cursor.execute(
                            "SELECT COUNT(*) FROM aseneth WHERE english ILIKE %s OR greek ILIKE %s",
                            (f'%{query}%', f'%{query}%')
                        )
                        cnt = cursor.fetchone()
                        counts['storehouse'] = cnt[0] if cnt else 0

            except Exception as e:
                print(f"Storehouse search error: {e}")
    
    # Deduplicate verse results to avoid duplicate entries (e.g., same reference from multiple sources)
    def dedupe_by_ref(items):
        seen = set()
        out = []
        for it in items:
            key = (it.get('book'), str(it.get('chapter')), str(it.get('verse')))
            if key in seen:
                continue
            seen.add(key)
            out.append(it)
        return out

    # Log and sanitize missing book names
    missing_books = []
    for cat in ['ot_verses', 'nt_verses', 'footnotes', 'storehouse']:
        cleaned = []
        for it in results.get(cat, []) or []:
            if not it.get('book'):
                missing_books.append((cat, it))
                it['book'] = ''
            cleaned.append(it)
        results[cat] = cleaned

    # Apply deduplication for verses, footnotes and storehouse
    results['ot_verses'] = dedupe_by_ref(results.get('ot_verses', []))
    results['nt_verses'] = dedupe_by_ref(results.get('nt_verses', []))
    results['footnotes'] = dedupe_by_ref(results.get('footnotes', []))
    results['storehouse'] = dedupe_by_ref(results.get('storehouse', []))

    # Recompute counts after deduplication
    counts['ot_verses'] = len(results['ot_verses'])
    counts['nt_verses'] = len(results['nt_verses'])
    counts['footnotes'] = len(results['footnotes'])
    counts['storehouse'] = len(results['storehouse'])

    # Calculate totals
    total_results = sum(counts.values())

    # If there are missing book entries, log a sample for debugging
    if missing_books:
        try:
            client_ip = request.META.get('REMOTE_ADDR', 'unknown') if request is not None else 'unknown'
            sample = missing_books[:10]
            logger.warning(
                "Missing book names in search results",
                extra={
                    'query': query,
                    'client_ip': client_ip,
                    'sample_missing': sample,
                    'missing_count': len(missing_books),
                }
            )
        except Exception:
            logger.exception('Failed to log missing book names')

    return JsonResponse({
        'query': query,
        'scope': scope,
        'type': search_type,
        'script_detected': script,
        'results': results,
        'counts': counts,
        'total': total_results,
        'page': page,
        'limit': limit,
        'lang': language or None,
        'translations_only': translations_only,
        'has_more': any(counts[k] > len(results[k]) for k in counts)
    })


@require_GET  
def search_suggestions(request):
    """
    Quick suggestions for autocomplete as user types.
    
    Returns:
    - Reference suggestions (if query looks like a book/chapter)
    - Book name suggestions (matching query prefix)
    """
    query = request.GET.get('q', '').strip()
    
    if len(query) < 2:
        return JsonResponse({'suggestions': []})
    
    suggestions = []
    
    # Check for reference match
    try:
        refs = bible.get_references(query)
        if refs:
            ref = refs[0]
            book_name = ref.book.name.replace('_', ' ').title()
            if ref.book.name == 'SONG_OF_SONGS':
                book_name = 'Song of Solomon'
            
            display = f'{book_name} {ref.start_chapter}'
            if ref.start_verse:
                display += f':{ref.start_verse}'
            
            suggestions.append({
                'type': 'reference',
                'text': display,
                'url': f'/?book={book_name}&chapter={ref.start_chapter}' + 
                       (f'&verse={ref.start_verse}' if ref.start_verse else '')
            })
    except:
        pass
    
    # Book name suggestions
    book_names = [
        'Genesis', 'Exodus', 'Leviticus', 'Numbers', 'Deuteronomy',
        'Joshua', 'Judges', 'Ruth', '1 Samuel', '2 Samuel', '1 Kings', '2 Kings',
        '1 Chronicles', '2 Chronicles', 'Ezra', 'Nehemiah', 'Esther', 'Job',
        'Psalms', 'Proverbs', 'Ecclesiastes', 'Song of Solomon', 'Isaiah',
        'Jeremiah', 'Lamentations', 'Ezekiel', 'Daniel', 'Hosea', 'Joel',
        'Amos', 'Obadiah', 'Jonah', 'Micah', 'Nahum', 'Habakkuk', 'Zephaniah',
        'Haggai', 'Zechariah', 'Malachi', 'Matthew', 'Mark', 'Luke', 'John',
        'Acts', 'Romans', '1 Corinthians', '2 Corinthians', 'Galatians',
        'Ephesians', 'Philippians', 'Colossians', '1 Thessalonians',
        '2 Thessalonians', '1 Timothy', '2 Timothy', 'Titus', 'Philemon',
        'Hebrews', 'James', '1 Peter', '2 Peter', '1 John', '2 John', '3 John',
        'Jude', 'Revelation'
    ]
    
    for book in book_names:
        if book.lower().startswith(query.lower()):
            suggestions.append({
                'type': 'book',
                'text': book,
                'url': f'/?book={book}&chapter=1'
            })
    
    return JsonResponse({'suggestions': suggestions[:10]})
