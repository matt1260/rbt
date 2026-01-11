"""
Core chapter and verse display views.

Contains the central get_results() function that fetches verse data across
all Bible books (Genesis, OT, NT) and handles chapter/verse rendering.
"""

import re
import os
import json
import calendar
from datetime import datetime, timedelta
from collections import OrderedDict
from urllib.parse import urlencode

from django.http import HttpResponse, JsonResponse
from django.shortcuts import render, redirect
from django.core.cache import cache
from django.db.models import Q, Max, Min
from django.views.decorators.csrf import csrf_exempt
from dateutil.relativedelta import relativedelta
import pythonbible as bible
from pythonbible.errors import InvalidBookError, InvalidChapterError, InvalidVerseError
from bs4 import BeautifulSoup

from search.models import Genesis, GenesisFootnotes, EngLXX, LITV, TranslationUpdates, VerseTranslation
from search.db_utils import get_db_connection, execute_query, table_has_column
from search.views.footnote_views import get_footnote, build_notes_html
from search.translation_utils import SUPPORTED_LANGUAGES
from translate.translator import (
    book_abbreviations, convert_book_name,
    old_testament_books, new_testament_books, nt_abbrev,
    build_heb_interlinear, replace_words, greek_lookup,
    ot_prev_next_references, extract_footnote_references, load_json
)
from search.rbt_titles import rbt_books

# Cache version for interlinear data
INTERLINEAR_CACHE_VERSION = 'v2'


def home(request):
    """Root home page."""
    return HttpResponse("You're at the home page.")


@csrf_exempt
def update_count(request):
    """Get count of translation updates for today."""
    if request.method == 'GET':
        today = datetime.now()

        start_date = today.replace(hour=0, minute=0, second=0, microsecond=0)
        end_date = today.replace(hour=23, minute=59, second=59, microsecond=999999)

        update_count = TranslationUpdates.objects.filter(
            date__range=[start_date, end_date]
        ).count()

        response = JsonResponse({'updateCount': update_count})
        response["Access-Control-Allow-Origin"] = "*"
        response["Access-Control-Allow-Methods"] = "GET, OPTIONS"
        response["Access-Control-Allow-Headers"] = "Content-Type"

        return response


def updates(request):
    """
    Translation updates page showing changes by date or month.
    
    Query params:
    - date: Show updates for specific date (YYYY-MM-DD)
    - month: Show updates for specific month number
    """
    date_param = request.GET.get('date')
    month_param = request.GET.get('month')
    today = datetime.now()

    if date_param:
        try:
            date = datetime.strptime(date_param, '%Y-%m-%d')
            start_date = datetime.combine(date, datetime.min.time())
            end_date = datetime.combine(date, datetime.max.time())
            results = TranslationUpdates.objects.filter(date__range=[start_date, end_date])
            previous_month = (date - relativedelta(months=1)).strftime('%m')
        except ValueError:
            results = TranslationUpdates.objects.none()
            previous_month = None

    elif month_param:
        try:
            current_year = datetime.now().year
            results = TranslationUpdates.objects.filter(
                date__month=int(month_param),
                date__year=current_year
            )
            
            current_month = int(month_param)
            previous_month = (current_month - 2) % 12 + 1
            month_param = calendar.month_name[int(month_param)]
        except ValueError as e:
            print(f'Error: {e}')
            results = TranslationUpdates.objects.none()
    else:
        start_date = today.replace(day=1)
        end_date = (today + timedelta(days=32)).replace(day=1) - timedelta(days=1)
        results = TranslationUpdates.objects.filter(date__range=[start_date, end_date])
        current_month = today.strftime('%m')
        previous_month = (datetime.now() - relativedelta(months=1)).strftime('%m')

    current_month = today.strftime('%m')
    current_day = today.strftime('%Y-%m-%d')

    def parse_and_construct_url(result):
        if '.' in result.reference:
            ref = result.reference.split('.')
            
            if len(ref) == 3:
                bookref_raw = ref[0]
                converted_bookref = convert_book_name(bookref_raw)
                bookref = converted_bookref if converted_bookref else bookref_raw
                if bookref:
                    bookref = bookref.capitalize()
                    bookref = bookref.replace(' ', '_')
                else:
                    return None

                chapter = ref[1]
                verse = ref[2]
                if '-' in verse:
                    verse = verse.split('-')[0]
                url = f'?book={bookref}&chapter={chapter}&verse={verse}'
            else:
                url = 'None'
        else:
            parts = result.reference.split()
            book = parts[0]
            chapter, verse = map(int, parts[1].split(':'))
            url = f'?book={book}&chapter={chapter}&verse={verse}'

        return url
    
    update_entries = []
    for result in results:
        try:
            url = parse_and_construct_url(result)
        except Exception:
            url = None

        raw_date = result.date
        if isinstance(raw_date, datetime):
            display_date = raw_date.date()
        else:
            display_date = raw_date

        update_entries.append({
            'date': display_date,
            'reference': result.reference,
            'version': result.version,
            'url': url,
        })

    context = {
        'month': month_param if month_param else date_param if date_param else datetime.now().strftime('%B %Y'),
        'updates': update_entries,
        'update_count': len(update_entries),
        'previous_month': previous_month,
        'current_month': current_month,
        'current_day': current_day,
    }

    return render(request, 'updates.html', context)


def get_results(book, chapter_num, verse_num=None, language='en'):
    """
    Central function for fetching verse/chapter data from all Bible sources.
    
    Handles:
    - Genesis (Django ORM)
    - Old Testament books (old_testament schema)
    - New Testament books (new_testament schema)
    - Hebrew interlinear data (old_testament.hebrewdata)
    - Greek interlinear data (rbt_greek.strongs_greek)
    - Footnotes across all sources
    - Smith Literal Translation and Brenton LXX
    - Caching for performance
    
    Args:
        book: Book name (e.g., 'Genesis', '1 John')
        chapter_num: Chapter number
        verse_num: Verse number (None for whole chapter)
        language: Language code for translations (default: 'en')
    
    Returns:
        dict: Comprehensive verse/chapter data including:
            - rbt: RBT translation HTML
            - hebrew/greek: Original language text
            - interlinear: Word-by-word analysis
            - footnotes: Footnote content
            - chapter_list: Available chapters
            - cached_hit: Whether data came from cache
    """
    # Initialize all return variables
    rbt_nt = None
    rbt_greek = None
    rbt_text = None
    rbt_html = None
    rbt_heb = None
    eng_lxx = None
    replacements = None
    footnote_contents = None
    next_ref = None
    prev_ref = None
    previous_footnote = None
    next_footnote = None
    chapter_footnotes = None
    record_id = None
    verse_id = None
    chapter_list = None
    rbt_paraphrase = None
    interlinear = None
    linear_english = None
    cached_hit = False
    strong_row = None
    english_row = None
    hebrew_row = None
    morph_row = None
    hebrew_clean = None
    commentary = None
    entries = None
    hebrew_cards = None
    hebrewdata_rows: list[dict[str, object]] = []

    def build_empty_result():
        return {
            "chapter_list": [],
            "rbt_greek": None,
            "interlinear": '',
            "slt": None,
            "litv": None,
            "eng_lxx": None,
            "rbt_text": None,
            "rbt": None,
            "rbt_paraphrase": None,
            "hebrew": None,
            "footnote_content": [],
            "previous_footnote": None,
            "next_footnote": None,
            "next_ref": None,
            "prev_ref": None,
            "record_id": None,
            "verse_id": None,
            "html": None,
            "linear_english": '',
            "entries": [],
            "replacements": [],
            "cached_hit": cached_hit,
            "strong_row": None,
            "english_row": None,
            "hebrew_row": None,
            "morph_row": None,
            "hebrew_clean": None,
            "hebrew_interlinear_cards": [],
            "hebrewdata_rows": [],
        }

    def _serialize_hebrew_rows(rows: list | tuple | None) -> list[dict[str, object]]:
        """Convert Hebrew data rows to serializable dict format."""
        if not rows:
            return []

        serialized: list[dict[str, object]] = []
        for raw in rows:
            row = tuple(raw)
            padded = list(row)
            if len(padded) < 25:
                padded += [None] * (25 - len(padded))

            (
                row_id, ref, eng, heb1, heb2, heb3, heb4, heb5, heb6,
                morph, unique, strongs, color, html_value,
                heb1_n, heb2_n, heb3_n, heb4_n, heb5_n, heb6_n,
                combined_heb, combined_heb_niqqud, footnote, morphology, *_
            ) = padded

            clean_token = ''.join(filter(None, [heb1_n, heb2_n, heb3_n, heb4_n, heb5_n, heb6_n]))
            token_ordinal = None
            if ref:
                try:
                    token_ordinal = ref.split('-')[-1]
                except Exception:
                    token_ordinal = None

            serialized.append({
                'id': row_id,
                'ref': ref,
                'token': token_ordinal,
                'english': eng or '',
                'english_original': eng or '',
                'morph_code': morph or '',
                'morphology': morphology or '',
                'morphology_original': morphology or '',
                'hebrew': combined_heb or clean_token or '',
                'hebrew_niqqud': combined_heb_niqqud or ''.join(filter(None, [heb1, heb2, heb3, heb4, heb5, heb6])) or '',
                'strongs': strongs or '',
                'unique': unique or '0',
                'color': color or '',
                'footnote': footnote or '',
                'footnote_original': footnote or '',
                'html': html_value or '',
            })

        return serialized

    # Cache key setup
    sanitized_book = book.replace(':', '_').replace(' ', '')
    cache_key_base = f'{sanitized_book}_{chapter_num}_{verse_num}_{language}_{INTERLINEAR_CACHE_VERSION}'
    cached_data = cache.get(cache_key_base)

    if not cached_data:
        
        ## Get Genesis from django database ##
        if book == 'Genesis' and verse_num is None:
            
            rbt_book_model_map = {
                'Genesis': Genesis,
            }

            rbt_table = rbt_book_model_map.get(book)
            if rbt_table is None:
                data = {
                    'rbt': [],
                    'chapter_list': [],
                    'cached_hit': cached_hit,
                    'html': rbt_html
                }
                cache.set(cache_key_base, data)
                return data

            rbt = rbt_table.objects.filter(chapter=chapter_num).order_by("verse")
            chapter_list = [str(i) for i in range(1, 51)]

            data = {
                'rbt': rbt,
                'chapter_list': chapter_list,
                'cached_hit': cached_hit,
                'html': rbt_html
            }
            
            cache.set(cache_key_base, data)
            return data

        if verse_num is not None:
            
            ## FETCH COMPLETED RBT VERSE IF AVAILABLE ##
            if book == 'Genesis':
                rbt_book_model_map = {
                    'Genesis': Genesis,
                }
                rbt_table = rbt_book_model_map.get(book)
                if rbt_table is None:
                    return build_empty_result()
                rbt = rbt_table.objects.filter(chapter=chapter_num, verse=verse_num)
                rbt_text = rbt.values_list('text', flat=True).first()
                rbt_html = rbt.values_list('html', flat=True).first() or ''
                rbt_paraphrase = rbt.values_list('rbt_reader', flat=True).first()
                rbt_heb = rbt.values_list('hebrew', flat=True).first()
                record_id_tuple = rbt.values_list('id').first()
                record_id = record_id_tuple[0] if record_id_tuple else None

                rbt_html = rbt_html.replace('</p><p>', '')
                
                footnote_references = re.findall(r'\?footnote=(\d+-\d+-\d+[a-zA-Z]?)', rbt_html) if rbt_html else []
                footnote_list = footnote_references

                footnote_contents = []
                for footnote_id in footnote_list:
                    footnote_content = get_footnote(footnote_id, book)
                    footnote_contents.append(footnote_content)

                # Fetch Hebrew interlinear data
                book_abbrev = book_abbreviations.get(book, book)
                rbt_heb_ref2 = f'{book_abbrev}.{chapter_num}.{verse_num}-'

                has_lxx_column = table_has_column('old_testament', 'hebrewdata', 'lxx')
                base_columns = (
                    "id, Ref, Eng, Heb1, Heb2, Heb3, Heb4, Heb5, Heb6, Morph, uniq, Strongs, color, html, "
                    "heb1_n, heb2_n, heb3_n, heb4_n, heb5_n, heb6_n, combined_heb, combined_heb_niqqud, footnote, morphology"
                )
                select_columns = base_columns + ", lxx" if has_lxx_column else base_columns

                sql_query_hebrew = f"""
                    SELECT {select_columns}
                    FROM old_testament.hebrewdata
                    WHERE ref LIKE %s
                    ORDER BY ref;
                """
                rows_data = execute_query(sql_query_hebrew, (f'{rbt_heb_ref2}%',), fetch='all') or []
                hebrewdata_rows = _serialize_hebrew_rows(rows_data)

                if rows_data:
                    strong_row, english_row, hebrew_row, morph_row, hebrew_clean, hebrew_cards = build_heb_interlinear(rows_data, show_edit_buttons=False)
                    hebrewdata_rows = _serialize_hebrew_rows(rows_data)
                    
                    strong_row.reverse()
                    english_row.reverse()
                    hebrew_row.reverse()

                    strong_row = '<tr class="strongs">' + ''.join(strong_row) + '</tr>'
                    english_row = '<tr class="eng_reader">' + ''.join(english_row) + '</tr>'
                    hebrew_row = '<tr class="hebrew_reader">' + ''.join(hebrew_row) + '</tr>'
                    hebrew_clean = '<font style="font-size: 26px;">' + ''.join(hebrew_clean) + '</font>'

                    niqqud_pattern = '[\u0591-\u05BD\u05BF\u05C1-\u05C5\u05C7]'
                    dash_pattern = '־'
                    hebrew_row = re.sub(niqqud_pattern + '|' + dash_pattern, '', hebrew_row)

                    raw_cards = hebrew_cards or []
                    hebrew_cards = []
                    for card in raw_cards:
                        hebrew_no_niqqud = re.sub(niqqud_pattern + '|' + dash_pattern, '', card['hebrew']).strip()
                        hebrew_cards.append({
                            'id': card.get('id'),
                            'hebrew': hebrew_no_niqqud,
                            'hebrew_niqqud': card['hebrew'],
                            'english': card['english'],
                            'strongs': card['strongs'],
                            'strongs_list': card.get('strongs_list', []),
                            'morph': card['morph'],
                            'lxx': card.get('lxx', ''),
                            'lxx_words': card.get('lxx_words', []),
                            'lxx_data': card.get('lxx_data', []),
                        })

                    hebrew_cards.sort(
                        key=lambda c: (c['id'] is None, c['id'] if c['id'] is not None else -1)
                    )
                else:
                    strong_row = None
                    english_row = None
                    hebrew_row = None
                    morph_row = None
                    hebrew_clean = None
                    hebrew_cards = []
                    hebrewdata_rows = []

                chapter_list = [str(i) for i in range(1, 51)]
            
                # Get previous and next verse references
                current_row_id = rbt.values_list('id', flat=True).first()

                prev_ref = f'?book={book}&chapter={chapter_num}&verse={verse_num}'
                next_ref = prev_ref

                if current_row_id is not None:
                    prev_row_id = rbt_table.objects.filter(id__lt=current_row_id).aggregate(max_id=Max('id'))['max_id']
                    if prev_row_id is not None:
                        prev_ref_qs = rbt_table.objects.filter(id=prev_row_id)
                        prev_chapter = prev_ref_qs.values_list('chapter', flat=True).first()
                        prev_verse = prev_ref_qs.values_list('verse', flat=True).first()
                        if prev_chapter is not None and prev_verse is not None:
                            prev_ref = f'?book={book}&chapter={prev_chapter}&verse={prev_verse}'

                    next_row_id = rbt_table.objects.filter(id__gt=current_row_id).aggregate(min_id=Min('id'))['min_id']
                    if next_row_id is not None:
                        next_ref_qs = rbt_table.objects.filter(id=next_row_id)
                        next_chapter = next_ref_qs.values_list('chapter', flat=True).first()
                        next_verse = next_ref_qs.values_list('verse', flat=True).first()
                        if next_chapter is not None and next_verse is not None:
                            next_ref = f'?book={book}&chapter={next_chapter}&verse={next_verse}'
                
            # Old Testament books
            elif book in old_testament_books:
        
                book_abbrev = book_abbreviations.get(book, book)
                rbt_heb_ref = f'{book_abbrev}.{chapter_num}.{verse_num}'
                rbt_heb_chapter = f'{book_abbrev}.{chapter_num}.'
                rbt_heb_ref2 = f'{book_abbrev}.{chapter_num}.{verse_num}-'

                sql_query_ot = """
                    SELECT id, Ref, html, hebrew, footnote, literal
                    FROM old_testament.ot
                    WHERE Ref = %s;
                """

                row_data = execute_query(sql_query_ot, (rbt_heb_ref,), fetch='one')
                if row_data is None:
                    data = build_empty_result()
                    cache.set(cache_key_base, data)
                    return data

                has_lxx_column = table_has_column('old_testament', 'hebrewdata', 'lxx')
                base_columns = (
                    "id, Ref, Eng, Heb1, Heb2, Heb3, Heb4, Heb5, Heb6, Morph, uniq, Strongs, color, html, "
                    "heb1_n, heb2_n, heb3_n, heb4_n, heb5_n, heb6_n, combined_heb, combined_heb_niqqud, footnote, morphology"
                )
                select_columns = base_columns + ", lxx" if has_lxx_column else base_columns

                sql_query_hebrew = f"""
                    SELECT {select_columns}
                    FROM old_testament.hebrewdata
                    WHERE ref LIKE %s
                    ORDER BY ref;
                """
                rows_data = execute_query(sql_query_hebrew, (f'{rbt_heb_ref2}%',), fetch='all') or []
                hebrewdata_rows = _serialize_hebrew_rows(rows_data)
  
                ref = row_data[1]
                prev_ref, next_ref = ot_prev_next_references(ref)
    
                if row_data[2] is not None:
                    rbt_paraphrase = row_data[2]
                    rbt_html = row_data[5]
                else:
                    rbt_paraphrase = "No verse found"
                    rbt_html = 'No verse found'
                
                rbt_heb = row_data[3]
                    
                strong_row, english_row, hebrew_row, morph_row, hebrew_clean, hebrew_cards = build_heb_interlinear(rows_data, show_edit_buttons=False)
                
                strong_row.reverse()
                english_row.reverse()
                hebrew_row.reverse()

                strong_row = '<tr class="strongs">' + ''.join(strong_row) + '</tr>'
                english_row = '<tr class="eng_reader">' + ''.join(english_row) + '</tr>'
                hebrew_row = '<tr class="hebrew_reader">' + ''.join(hebrew_row) + '</tr>'
                hebrew_clean = '<font style="font-size: 26px;">' + ''.join(hebrew_clean) + '</font>'

                niqqud_pattern = '[\u0591-\u05BD\u05BF\u05C1-\u05C5\u05C7]'
                dash_pattern = '־'
                hebrew_row = re.sub(niqqud_pattern + '|' + dash_pattern, '', hebrew_row)

                raw_cards = hebrew_cards or []
                hebrew_cards = []
                for card in raw_cards:
                    hebrew_no_niqqud = re.sub(niqqud_pattern + '|' + dash_pattern, '', card['hebrew']).strip()
                    hebrew_cards.append({
                        'id': card.get('id'),
                        'hebrew': hebrew_no_niqqud,
                        'hebrew_niqqud': card['hebrew'],
                        'english': card['english'],
                        'strongs': card['strongs'],
                        'strongs_list': card.get('strongs_list', []),
                        'morph': card['morph'],
                        'lxx': card.get('lxx', ''),
                        'lxx_words': card.get('lxx_words', []),
                        'lxx_data': card.get('lxx_data', []),
                    })

                hebrew_cards.sort(
                    key=lambda c: (c['id'] is None, c['id'] if c['id'] is not None else -1)
                )

                footnote_list = re.findall(r'\?footnote=([^&"]+)', rbt_paraphrase)

                footnote_contents = []
                for footnote_id in footnote_list:
                    footnote_content = get_footnote(footnote_id, book)
                    footnote_contents.append(footnote_content)

            elif book in new_testament_books:
                
                book_abbrev = book_abbreviations.get(book, book)

                sql_query = """
                    SELECT verseText, rbt, verseID, nt_id
                    FROM new_testament.nt
                    WHERE book = %s AND chapter = %s AND startVerse = %s
                """

                result = execute_query(sql_query, (book_abbrev, chapter_num, verse_num), fetch='one')

                if result:
                    sql_next = """
                        SELECT book, chapter, startVerse
                        FROM new_testament.nt
                        WHERE nt_id > %s
                        ORDER BY nt_id ASC
                        LIMIT 1
                    """
                    next_record = execute_query(sql_next, (result[3],), fetch='one')
 
                    sql_prev = """
                        SELECT book, chapter, startVerse
                        FROM new_testament.nt
                        WHERE nt_id < %s
                        ORDER BY nt_id DESC
                        LIMIT 1
                    """
                    prev_record = execute_query(sql_prev, (result[3],), fetch='one')

                    sql_footnotes = """
                        SELECT rbt
                        FROM new_testament.nt
                        WHERE book = %s AND chapter = %s AND CAST(startVerse AS INTEGER) <= %s
                    """
                    verses = execute_query(sql_footnotes, (book_abbrev, chapter_num, verse_num), fetch='all')

                    footnote_references = extract_footnote_references(verses)
                    previous_footnote = footnote_references[-1] if footnote_references else 'No footnote in this chapter or previous chapter found.'

                    next_footnotes = """
                        SELECT rbt
                        FROM new_testament.nt
                        WHERE book = %s AND (
                            (chapter = %s AND CAST(startVerse AS INTEGER) > %s) OR
                            (chapter = %s AND CAST(startVerse AS INTEGER) >= 1)
                        )
                    """
                    next_verses = execute_query(next_footnotes, (book_abbrev, chapter_num, verse_num, str(int(chapter_num) + 1)), fetch='all')

                    next_footnote_references = extract_footnote_references(next_verses)
                    next_footnote = next_footnote_references[0] if next_footnote_references else "No more footnotes in this or next chapter."

                if result:
                    rbt_greek = result[0]
                    rbt_html = result[1]
                    verse_id = result[2]
                else:
                    rbt_greek = ''
                    rbt_html = "No verse found"
                
                sql_query = """
                    SELECT chapter
                    FROM new_testament.nt
                    WHERE book LIKE %s;
                """
                chapters = execute_query(sql_query, (f'{book_abbrev}%',), fetch='all') or []

                unique_chapters = set(int(row[0]) for row in chapters)
                chapter_list = sorted(map(str, unique_chapters), key=lambda x: int(x))

                if prev_record is not None:
                    abbreviation = prev_record[0]
                    if abbreviation[0].isdigit():
                        abbreviation = abbreviation[0] + abbreviation[1:].capitalize()
                    else:
                        abbreviation = abbreviation.capitalize()
                    
                    prev_book = convert_book_name(abbreviation) if abbreviation in nt_abbrev else None
                    if not prev_book:
                        prev_book = abbreviation
                    prev_ref = f'?book={prev_book}&chapter={prev_record[1]}&verse={prev_record[2]}'
                
                if next_record is not None:
                    abbreviation = next_record[0]
                    if abbreviation[0].isdigit():
                        abbreviation = abbreviation[0] + abbreviation[1:].capitalize()
                    else:
                        abbreviation = abbreviation.capitalize()
                    
                    next_book = convert_book_name(abbreviation) if abbreviation in nt_abbrev else None
                    if not next_book:
                        next_book = abbreviation
                    next_ref = f'?book={next_book}&chapter={next_record[1]}&verse={next_record[2]}'

                # GET GREEK INTERLINEAR
                if book in book_abbreviations:
                    book_abbrev = book_abbreviations[book]
                    rbt_grk_ref = f'{book_abbrev}.{chapter_num}.{verse_num}-'
                else:
                    rbt_grk_ref = f'{book}.{chapter_num}.{verse_num}-'

                sql_query = """
                    SELECT verse, strongs, translit, lemma, english, morph, morph_desc
                    FROM rbt_greek.strongs_greek
                    WHERE verse LIKE %s
                    ORDER BY id ASC;
                """
                result = execute_query(sql_query, (f'{rbt_grk_ref}%',), fetch='all')
                interlinear = ''
                linear_english = ''
                entries = []

                for i, row in enumerate(result, start=1):
                    try:
                        verse, strongs, translit, lemma, english, morph, morph_desc = row
                        
                        entries.append({
                            "seq": i,
                            "lemma": lemma,
                            "english": english,
                            "morph": morph,
                            "morph_description": morph_desc,
                        })
                        
                        strongs, lemma, english = replace_words(strongs, lemma, english)

                        interlinear += '<table class="tablefloat">\n<tbody>\n'
                        interlinear += '<tr>\n<td class="interlinear" height="160" valign="middle" align="left">\n'
                        interlinear += f'<span class="pos"><a href="https://biblehub.com/greek/{strongs}.htm" target="_blank">Strongs {strongs}</a></span>&nbsp;\n'
                        interlinear += f'<span class="strongsnt2"> <a href="https://biblehub.com/greek/strongs_{strongs}.htm" target="_blank">[list]</a></span><br>\n'
                        
                        greek_lemma = greek_lookup(lemma)
                        
                        if greek_lemma in ['βασιλεία', 'βασιλείαν', 'βασιλείας']:
                            greek_lemma = 'βασίλεια'
                        if greek_lemma == 'Παραδείσῳ':
                            greek_lemma = 'παράδεισος'
                        
                        interlinear += f'<span class="strongsnt2"> <a href="https://logeion.uchicago.edu/{greek_lemma}" target="_blank">Λογεῖον</a></span><br>\n'
                        interlinear += f'<span class="strongsnt2"> <a href="https://www.perseus.tufts.edu/hopper/morph?l={greek_lemma}" target="_blank">Perseus</a></span><br>\n'
                        interlinear += f'<span class="translit">{translit}</span><br>\n'
                        interlinear += f'<span class="greek">{lemma}</span><br>\n'
                        interlinear += f'<span class="eng">{english}</span><br>\n'

                        color = "#000"
                        if "Feminine" in morph_desc:
                            color = "#FF1493"
                        elif "Masculine" in morph_desc:
                            color = "blue"
                        
                        interlinear += f'<a href="https://www.realbible.tech/greek-parsing/"><span class="morph" title="{morph_desc}" style="color: {color};">{morph}</span></a>\n'
                        interlinear += '</td>\n</tr>\n'
                        interlinear += '</tbody>\n</table>\n'

                        linear_english += f'{english} '
                    except Exception as e:
                        print(f"[ERROR] Exception on row {i}: {e}, row data: {row}")

                if rbt_html is not None:
                    footnote_references = re.findall(r'\?footnote=(\d+-\d+-\d+[a-zA-Z]?)', rbt_html)
                    footnote_list = footnote_references
                  
                    footnote_contents = []
                    for footnote_id in footnote_list:
                        footnote_content = get_footnote(footnote_id, book_abbrev, chapter_num, verse_num)
                        footnote_contents.append(footnote_content)

            ##### Fetch Smith Literal Translation Verse ##############
            try:
                slt_reference = bible.get_references(f'{book} {chapter_num}:{verse_num}')
                slt_ref = slt_reference[0]
                slt_book = slt_ref.book.name
                slt_book = slt_book.title()

                sql_query = """
                    SELECT content
                    FROM smith_translation.verses
                    WHERE book = %s AND chapter = %s AND verse = %s
                """
                result = execute_query(sql_query, (slt_book, chapter_num, verse_num), fetch='one')
   
                slt = result[0] if result else None
                slt = f'<div class="single_verse"><strong>Julia Smith Literal 1876 Translation:</strong><br> {slt}</div>'
            except:
                slt = '<div class="single_verse"><strong>Julia Smith Literal 1876 Translation:</strong><br>None</div>'
            
            # BRENTON SEPTUAGINT in English Updated
            englxx_dict = {'Genesis': 'GEN', 'Exodus': 'EXO', 'Leviticus': 'LEV', 'Numbers': 'NUM', 'Deuteronomy': 'DEU', 'Joshua': 'JOS', 'Judges': 'JDG', 'Ruth': 'RUT', '1 Samuel': '1SA', '2 Samuel': '2SA', '1 Kings': '1KI', '2 Kings': '2KI', '1 Chronicles': '1CH', '2 Chronicles': '2CH', 'Ezra': 'EZR', 'Job': 'JOB', 'Psalms': 'PSA', 'Proverbs': 'PRO', 'Ecclesiastes': 'ECC', 'Song of Solomon': 'SNG', 'Isaiah': 'ISA', 'Jeremiah': 'JER', 'Lamentations': 'LAM', 'Ezekiel': 'EZK', 'Hosea': 'HOS', 'Joel': 'JOL',
                'Amos': 'AMO', 'Obadiah': 'OBA', 'Jonah': 'JON', 'Micah': 'MIC', 'Nahum': 'NAM', 'Habakkuk': 'HAB', 'Zephaniah': 'ZEP', 'Haggai': 'HAG', 'Zechariah': 'ZEC', 'Malachi': 'MAL', 'Tobit': 'TOB', 'Judith': 'JDT', 'Esther': 'ESG', 'Wisdom': 'WIS', 'Sirach': 'SIR', 'Baruch': 'BAR', 'Letter of Jeremiah': 'LJE', 'Susanna': 'SUS', 'Bel and the Dragon': 'BEL', '1 Maccabees': '1MA', '2 Maccabees': '2MA', '1 Esdras': '1ES', 'Prayer of Manasseh': 'MAN', '3 Maccabees': '3MA', '4 Maccabees': '4MA', 'Daniel': 'DAG'}
            englxx_book = englxx_dict.get(book, 'Unknown')
            eng_lxx = EngLXX.objects.filter(
                book=englxx_book)
            eng_lxx = eng_lxx.filter(chapter=chapter_num)
            eng_lxx = eng_lxx.filter(startVerse=verse_num)
            eng_lxx = eng_lxx.values_list('verseText', flat=True).first()
            if eng_lxx:
                eng_lxx = f'<div class="single_verse"><strong>Brenton Septuagint Translation:</strong><br> {eng_lxx}</div>'
            else:
                eng_lxx = ''

            # LITV Translation
            litv = LITV.objects.filter(book=book)
            litv = litv.filter(chapter=chapter_num)
            litv = litv.filter(verse=verse_num)
            litv = litv.values_list('text', flat=True).first()
            litv = f'<div class="single_verse"><strong>LITV Translation:</strong><br> {litv}</div>'

            replacements = []
            json_file = 'interlinear_english.json'

            if os.path.exists(json_file):
                try:
                    with open(json_file, 'r', encoding='utf-8') as f:
                        data = json.load(f)
                        if data:
                            replacements = data
                except json.JSONDecodeError as e:
                    print(f"[ERROR] Failed to load JSON: {e}")

            hebrew_cards = hebrew_cards or []

            data = {
                "chapter_list": chapter_list,
                "rbt_greek": rbt_greek,
                "interlinear": interlinear,
                "slt": slt,
                "litv": litv,
                "eng_lxx": eng_lxx,
                "rbt_text": rbt_text,
                "rbt": rbt_html,
                "rbt_paraphrase": rbt_paraphrase,
                "hebrew": rbt_heb,
                "footnote_content": footnote_contents,
                "previous_footnote": previous_footnote,
                "next_footnote": next_footnote,
                "next_ref": next_ref,
                "prev_ref": prev_ref,
                "record_id": record_id,
                "verse_id": verse_id,
                "html": rbt_html,
                "linear_english": linear_english,
                "entries": entries,
                "replacements": replacements,
                "cached_hit": cached_hit,
                "strong_row": strong_row, 
                "english_row": english_row,
                "hebrew_row": hebrew_row,
                "morph_row": morph_row,
                "hebrew_clean": hebrew_clean,
                "hebrew_interlinear_cards": hebrew_cards,
                "hebrewdata_rows": hebrewdata_rows,
            }

            cache.set(cache_key_base, data)
            return data

        # Get whole chapter
        elif book in old_testament_books:
            if book in book_abbreviations:
                book_abbrev = book_abbreviations[book]
                rbt_heb_ref = f'{book_abbrev}.{chapter_num}.{verse_num}-'
                rbt_heb_chapter = f'{book_abbrev}.{chapter_num}.'
            else:
                rbt_heb_ref = f'{book}.{chapter_num}.{verse_num}-'
                rbt_heb_chapter = f'{book}.{chapter_num}.'
                book_abbrev = book

            chapter_reader = execute_query(
                "SELECT Ref, html FROM old_testament.hebrewdata WHERE ref LIKE %s ORDER BY ref;",
                (f'{rbt_heb_chapter}%',),
                fetch='all'
            )

            data = execute_query(
                "SELECT id, Ref, Eng, html, footnote FROM old_testament.hebrewdata WHERE Ref LIKE %s ORDER BY ref;",
                (f'{rbt_heb_chapter}%',),
                fetch='all'
            )

            rbt_ref = rbt_heb_chapter[:4]
            chapter_references = execute_query(
                "SELECT Ref FROM old_testament.hebrewdata WHERE Ref LIKE %s;",
                (f'{rbt_ref}%',),
                fetch='all'
            )

            commentary = None

            regex_pattern = re.compile(fr'{book_abbrev}\.{chapter_num}\.(\d+)')
            
            verse_groups = {}
            
            for item in data:
                ref = item[1]
                eng = item[2]
                html_content = item[3]
   
                match = regex_pattern.search(ref)
                if match:
                    verse_num = int(match.group(1))

                    if verse_num not in verse_groups:
                        verse_groups[verse_num] = []
                    
                    verse_groups[verse_num].append((eng, html_content))

            html = {}
            sorted_verse_nums = sorted(verse_groups.keys())

            for verse_num in sorted(verse_groups.keys()):
                verse_key = f"{verse_num:02d}"
                
                eng_parts = []
                html_parts = []
                
                for eng, html_content in verse_groups[verse_num]:
                    if eng:
                        eng_parts.append(eng)
                    if html_content:
                        html_parts.append(html_content)
                
                html[verse_key] = (' '.join(eng_parts), ' '.join(html_parts))

            unique_chapters = set(int(reference[0].split('.')[1]) for reference in chapter_references)
            chapter_list = sorted(map(str, unique_chapters), key=lambda x: int(x))
            
            data = {
                'chapter_reader': chapter_reader,
                'html': html,
                'rbt': rbt_html,
                'commentary': commentary,
                'chapter_list': chapter_list,
                'cached_hit': cached_hit
            }

            cache.set(cache_key_base, data)
            return data
           
        elif book in new_testament_books:
            
            if book in book_abbreviations:
                book_abbrev = book_abbreviations[book]

            data = execute_query(
                """
                SELECT book, chapter, startVerse, rbt
                FROM new_testament.nt
                WHERE book = %s AND chapter = %s
                ORDER BY startVerse
                """,
                (book_abbrev, chapter_num),
                fetch='all'
            )

            html = data
            chapter_reader = data

            chapters = execute_query(
                "SELECT chapter FROM new_testament.nt WHERE book LIKE %s;",
                (f'{book_abbrev}%',),
                fetch='all'
            )

            unique_chapters = set(int(reference[0]) for reference in chapters)
            chapter_list = sorted(map(str, unique_chapters), key=lambda x: int(x))
            
            rbt = ''
            data = {
                'chapter_reader': chapter_reader,
                'html': html,
                'chapter_list': chapter_list,
                'rbt': rbt,
                'cached_hit': cached_hit,
                'commentary': None
            }
            
            cache.set(cache_key_base, data)
            return data   

        else:
            rbt = 'Error: Nothing found'
            rbt_html = 'Error'
            chapter_list = 'Error'
            chapter_reader = 'Error'
            return {
                'rbt': rbt,
                'chapter_reader': chapter_reader,
                'html': rbt_html,
                'chapter_list': chapter_list,
                'cached_hit': cached_hit
            }
    else:
        cached_data['cached_hit'] = True
        return cached_data
