from attrs import field
from django.http import HttpResponse
from django.shortcuts import render, redirect
from search.models import Genesis, GenesisFootnotes, EngLXX, LITV, TranslationUpdates, VerseTranslation
from django.db.models import Q, Max, Min
from django.http import JsonResponse
from django.core.cache import cache
import re
import pytz
from urllib.parse import urlencode
import pythonbible as bible
from pythonbible.errors import InvalidChapterError
import requests
from translate.translator import *
from search.rbt_titles import rbt_books
from search.translation_utils import SUPPORTED_LANGUAGES, translate_chapter_batch, translate_footnotes_batch
from dateutil.relativedelta import relativedelta
from calendar import month_name
import calendar
from django.http import JsonResponse
from django.db.models import Count
from django.views.decorators.csrf import csrf_exempt
from django.db.models.query import QuerySet
from django.db.models.functions import TruncDate, TruncWeek, TruncMonth, TruncHour
from itertools import groupby
from pythonbible.errors import (
    InvalidBookError,
    InvalidChapterError,
    InvalidVerseError
)
from bs4 import BeautifulSoup
from collections import OrderedDict, defaultdict
from django.views.decorators.http import require_http_methods
import traceback
from django.utils import timezone
from datetime import datetime, timedelta, timezone as dt_timezone
from .db_utils import get_db_connection, execute_query, table_has_column
import os

# Import storehouse_view from modular views
from search.views.storehouse_views import storehouse_view

INTERLINEAR_CACHE_VERSION = 'v2'

def home(request):
    return HttpResponse("You're at the home page.")

@csrf_exempt
def update_count(request):
    if request.method == 'GET':
        today = datetime.now()

        start_date = today.replace(hour=0, minute=0, second=0, microsecond=0)
        end_date = today.replace(hour=23, minute=59, second=59, microsecond=999999)

        update_count = TranslationUpdates.objects.filter(
            date__range=[start_date, end_date]
        ).count()

        response = JsonResponse({'updateCount': update_count})
        response["Access-Control-Allow-Origin"] = "*"  # Allow all domains
        response["Access-Control-Allow-Methods"] = "GET, OPTIONS"
        response["Access-Control-Allow-Headers"] = "Content-Type"

        return response
    

def updates(request):
    # Get the 'date' parameter from the request's GET parameters
    date_param = request.GET.get('date')
    month_param = request.GET.get('month')
    today = datetime.now()

    if date_param:
        # If 'date' parameter is provided, filter updates for the given date
        try:
            # Assuming the date parameter is in the format 'YYYY-MM-DD'
            date = datetime.strptime(date_param, '%Y-%m-%d')
            start_date = datetime.combine(date, datetime.min.time())
            end_date = datetime.combine(date, datetime.max.time())
            results = TranslationUpdates.objects.filter(date__range=[start_date, end_date])
            previous_month = (date - relativedelta(months=1)).strftime('%m')

        except ValueError:
            # Handle invalid date format
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
        # If 'date' parameter is not provided, show updates for the current month
        start_date = today.replace(day=1)
        end_date = (today + timedelta(days=32)).replace(day=1) - timedelta(days=1)
        results = TranslationUpdates.objects.filter(date__range=[start_date, end_date])
        current_month = today.strftime('%m')
        previous_month = (datetime.now() - relativedelta(months=1)).strftime('%m')

    current_month = today.strftime('%m')
    current_day = today.strftime('%Y-%m-%d')


    def parse_and_construct_url(result):

        if '.' in result.reference:
            # Handle references like 'Gen.1.1'
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

# Retrieve and format each footnote into a table row
def get_footnote(footnote_id, book, chapter_num=None, verse_num=None):

    
    if book == "Genesis":

        results = GenesisFootnotes.objects.filter(
            footnote_id=footnote_id).values('footnote_html')


        # Split the footnote_id by '-' and get the last slice
        footnote_parts = footnote_id.split('-')
        footnote_ref = footnote_parts[-1]
        chapter = footnote_parts[0]
        verse = footnote_parts[1]

        if not results:
            footnote_html = f"No footnote found for {footnote_id}."

        else:
            footnote_html = results[0]['footnote_html']

        note_location = f'<div class="note-location">{book} {chapter}:{verse}</div>'

        # Create an HTML table with two columns
        table_html = (
            f'<tr>'
            f'<td style="border-bottom: 1px solid #d2d2d2;">'
            f'<a href="?footnote={chapter}-{verse}-{footnote_ref}">{footnote_ref}</a>'
            f'</td>'
            f'<td style="border-bottom: 1px solid #d2d2d2;">{note_location}{footnote_html}</td>'
            f'</tr>'
        )

        return table_html

    elif book in nt_abbrev or book in new_testament_books:

        # Normalize book abbreviation and full name
        book_abbrev = book_abbreviations.get(book, book)
        # In case an abbreviation was passed, resolve full book name for display
        abbrev_to_book = {abbrev: bk for bk, abbrev in book_abbreviations.items()}
        full_book = abbrev_to_book.get(book, book) if book not in book_abbreviations else book

        if book_abbrev[0].isdigit():
            table = f"table_{book_abbrev}_footnotes"
        else:
            table = f"{book_abbrev}_footnotes"

        table = table.lower()

        footnote_parts = footnote_id.split('-')
        footnote_number = footnote_parts[-1]

        footnote_ref = book_abbrev + '-' + footnote_number

        chapter_part = footnote_parts[0] if footnote_parts else chapter_num
        verse_part = footnote_parts[1] if len(footnote_parts) > 1 else verse_num
        note_location = ''
        if chapter_part and verse_part:
            note_location = f'<div class="note-location">{full_book} {chapter_part}:{verse_part}</div>'
        elif chapter_part:
            note_location = f'<div class="note-location">{full_book} {chapter_part}</div>'

        # Construct the SQL query to retrieve HTML
        sql_query = f"SELECT footnote_html FROM new_testament.{table} WHERE footnote_id = %s"
        result = execute_query(sql_query, (footnote_ref,), fetch='one')

        if result:
            footnote_html = result[0]
            # Create an HTML table with two columns
            table_html = (
                f'<tr>'
                f'<td style="border-bottom: 1px solid #d2d2d2;">'
                f'<a href="?footnote={chapter_num}-{verse_num}-{footnote_number}&book={book_abbrev}">{footnote_number}</a>'
                f'</td>'
                f'<td style="border-bottom: 1px solid #d2d2d2;">{note_location}{footnote_html}</td>'
                f'</tr>'
            )
        else:
            table_html = ''

        return table_html

    else:
        
        footnote_parts = footnote_id.split('-')
        if len(footnote_parts) == 4:
            rbt_heb_ref = f'{footnote_parts[0]}.{footnote_parts[1]}.{footnote_parts[2]}-{footnote_parts[3]}'
            foot_ref = f'{footnote_parts[0]}. {footnote_parts[1]}:{footnote_parts[2]}'
        else:
            footnote_parts2 = footnote_parts[0].split('.')
            rbt_heb_ref = f'{footnote_parts2[0]}.{footnote_parts2[1]}.{footnote_parts2[2]}-{footnote_parts[1]}'
            foot_ref = f'{footnote_parts2[0]}. {footnote_parts2[1]}:{footnote_parts2[2]}'
                
        # Ensure the correct schema is used
        execute_query("SET search_path TO old_testament;")

        # Construct the SQL query to retrieve the footnote
        sql_query = "SELECT footnote FROM old_testament.hebrewdata WHERE Ref = %s"
        result = execute_query(sql_query, (rbt_heb_ref,), fetch='one')

        if result:
            footnote_html = result[0]
            note_location = f'<div class="note-location">{foot_ref}</div>'
            # Create an HTML table with two columns
            table_html = (
                f'<tr>'
                f'<td style="border-bottom: 1px solid #d2d2d2;">{foot_ref}</td>'
                f'<td style="border-bottom: 1px solid #d2d2d2;">{note_location}{footnote_html}</td>'
                f'</tr>'
            )
        else:
            table_html = ''

        return table_html


FOOTNOTE_LINK_PATTERN = re.compile(r'\?footnote=([^&"\s]+)')


def collect_chapter_notes(html_chunks, book, chapter_num=None, verse_num=None):
    """Extract unique footnote rows from provided HTML snippets."""
    if not html_chunks:
        return []

    collected: list[str] = []
    seen: set[str] = set()

    for chunk in html_chunks:
        if not chunk:
            continue

        matches = FOOTNOTE_LINK_PATTERN.findall(str(chunk))
        for footnote_id in matches:
            if footnote_id in seen:
                continue

            seen.add(footnote_id)
            try:
                footnote_row = get_footnote(footnote_id, book, chapter_num, verse_num)
            except Exception as exc:
                print(f"[WARN] Unable to collect footnote {footnote_id}: {exc}")
                footnote_row = ''

            if footnote_row:
                collected.append(footnote_row)

    return collected


def build_notes_html(html_chunks, book, chapter_num=None, verse_num=None, translated_footnotes=None):
    """Format aggregated chapter notes into a table suitable for rendering.
    
    Args:
        html_chunks: List of HTML strings to extract footnote references from
        book: Book name
        chapter_num: Chapter number (optional)
        verse_num: Verse number (optional)
        translated_footnotes: Dict of {full_footnote_id: translated_content} for translations
    """
    rows = collect_chapter_notes_with_translations(
        html_chunks, book, chapter_num, verse_num, translated_footnotes
    )
    if not rows:
        return ''

    merged = ''.join(rows)
    return f'<table class="notes-table"><tbody>{merged}</tbody></table>'


def collect_chapter_notes_with_translations(html_chunks, book, chapter_num=None, verse_num=None, translated_footnotes=None):
    """Extract unique footnote rows, using translated content when available."""
    if not html_chunks:
        return []

    collected: list[str] = []
    seen: set[str] = set()
    translated_footnotes = translated_footnotes or {}

    for chunk in html_chunks:
        if not chunk:
            continue

        matches = FOOTNOTE_LINK_PATTERN.findall(str(chunk))
        for footnote_id in matches:
            if footnote_id in seen:
                continue

            seen.add(footnote_id)
            
            # Check if we have a translated version
            full_footnote_id = f"{book}-{footnote_id}"
            if full_footnote_id in translated_footnotes:
                # Translated footnotes already contain the full <tr>...</tr> row structure
                # Just use them directly
                footnote_row = translated_footnotes[full_footnote_id]
            else:
                # Fall back to original English footnote
                try:
                    footnote_row = get_footnote(footnote_id, book, chapter_num, verse_num)
                except Exception as exc:
                    print(f"[WARN] Unable to collect footnote {footnote_id}: {exc}", flush=True)
                    footnote_row = ''

            if footnote_row:
                collected.append(footnote_row)

    return collected


# RBT DATABASE (uses django database for Genesis.
def get_results(book, chapter_num, verse_num=None, language='en'):
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
        if not rows:
            return []

        serialized: list[dict[str, object]] = []
        for raw in rows:
            row = tuple(raw)
            padded = list(row)
            if len(padded) < 25:
                padded += [None] * (25 - len(padded))

            (
                row_id,
                ref,
                eng,
                heb1,
                heb2,
                heb3,
                heb4,
                heb5,
                heb6,
                morph,
                unique,
                strongs,
                color,
                html_value,
                heb1_n,
                heb2_n,
                heb3_n,
                heb4_n,
                heb5_n,
                heb6_n,
                combined_heb,
                combined_heb_niqqud,
                footnote,
                morphology,
                *_
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

    # Sets/Retrieves cache only for verse, not whole chapter
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
            
            # Cache whole OT chapter
            cache.set(cache_key_base, data)
            #print('OT Chapter Cached: ', cache_key_base)

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
                rbt = rbt_table.objects.filter(chapter=chapter_num)  # filter chapter
                rbt = rbt.filter(verse=verse_num) # filter verse
                rbt_text = rbt.values_list('text', flat=True).first()
                rbt_html = rbt.values_list('html', flat=True).first() or ''
                rbt_paraphrase = rbt.values_list('rbt_reader', flat=True).first()
                rbt_heb = rbt.values_list('hebrew', flat=True).first()
                record_id_tuple = rbt.values_list('id').first()
                record_id = record_id_tuple[0] if record_id_tuple else None

                rbt_html = rbt_html.replace('</p><p>', '')
                
                
                # Generate a list of footnote references found in the verse
                #footnote_references = re.findall(r'href="\?footnote=(\d+-\d+-\d+)"', rbt_html)
                footnote_references = re.findall(r'\?footnote=(\d+-\d+-\d+[a-zA-Z]?)', rbt_html) if rbt_html else []
                
                footnote_list = footnote_references

                # Create a list to store footnote contents using get_footnote function
                footnote_contents = []
                for footnote_id in footnote_list:
                    
                    footnote_content = get_footnote(footnote_id, book) # get_footnote function
                    footnote_contents.append(footnote_content)

                # Fetch Hebrew interlinear data from hebrewdata table
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
                    
                    # Reverse the order for RTL display
                    strong_row.reverse()
                    english_row.reverse()
                    hebrew_row.reverse()

                    strong_row = '<tr class="strongs">' + ''.join(strong_row) + '</tr>'
                    english_row = '<tr class="eng_reader">' + ''.join(english_row) + '</tr>'
                    hebrew_row = '<tr class="hebrew_reader">' + ''.join(hebrew_row) + '</tr>'
                    hebrew_clean = '<font style="font-size: 26px;">' + ''.join(hebrew_clean) + '</font>'

                    # Strip niqqud from hebrew row
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
            
                # Get the previous and next row verse references
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
        
                # Convert references to 'Gen.1.1' format
                book_abbrev = book_abbreviations.get(book, book)
                rbt_heb_ref = f'{book_abbrev}.{chapter_num}.{verse_num}'
                rbt_heb_chapter = f'{book_abbrev}.{chapter_num}.'
                rbt_heb_ref2 = f'{book_abbrev}.{chapter_num}.{verse_num}-'

                # Retrieve a single OT row
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

                # Retrieve Hebrewdata rows matching a reference pattern
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
  
                #verse_footnote = row_data[4]
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
                
                # Reverse the order 
                strong_row.reverse()
                english_row.reverse()
                hebrew_row.reverse()
                #morph_row.reverse()

                strong_row = '<tr class="strongs">' + ''.join(strong_row) + '</tr>'
                english_row = '<tr class="eng_reader">' + ''.join(english_row) + '</tr>'
                hebrew_row = '<tr class="hebrew_reader">' + ''.join(hebrew_row) + '</tr>'
                #morph_row = '<tr class="morph_reader" style="word-wrap: break-word;">' + ''.join(morph_row) + '</tr>'
                hebrew_clean = '<font style="font-size: 26px;">' + ''.join(hebrew_clean) + '</font>'

                # strip niqqud from hebrew
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

                # incomplete. need to finish get_footnote() for rest of OT books
                footnote_list = re.findall(r'\?footnote=([^&"]+)', rbt_paraphrase)

                # Create a list to store footnote contents using get_footnote function
                footnote_contents = []
                for footnote_id in footnote_list:
                    footnote_content = get_footnote(footnote_id, book) # get_footnote function
                    footnote_contents.append(footnote_content)

            elif book in new_testament_books:
                
                book_abbrev = book_abbreviations.get(book, book)

                # Get NT html for the current verse
                sql_query = """
                    SELECT verseText, rbt, verseID, nt_id
                    FROM new_testament.nt
                    WHERE book = %s AND chapter = %s AND startVerse = %s
                """

                result = execute_query(sql_query, (book_abbrev, chapter_num, verse_num), fetch='one')


                if result:
                    # Get the next verse
                    sql_next = """
                        SELECT book, chapter, startVerse
                        FROM new_testament.nt
                        WHERE nt_id > %s
                        ORDER BY nt_id ASC
                        LIMIT 1
                    """

                    next_record = execute_query(sql_next, (result[3],), fetch='one')
 
                    # Get the previous verse
                    sql_prev = """
                        SELECT book, chapter, startVerse
                        FROM new_testament.nt
                        WHERE nt_id < %s
                        ORDER BY nt_id DESC
                        LIMIT 1
                    """

                    prev_record = execute_query(sql_prev, (result[3],), fetch='one')

                    # Get all verses up to current verse of current chapter
                    sql_footnotes = """
                        SELECT rbt
                        FROM new_testament.nt
                        WHERE book = %s AND chapter = %s AND CAST(startVerse AS INTEGER) <= %s
                    """

                    verses = execute_query(sql_footnotes, (book_abbrev, chapter_num, verse_num), fetch='all')

                    footnote_references = extract_footnote_references(verses)
                    previous_footnote = footnote_references[-1] if footnote_references else 'No footnote in this chapter or previous chapter found.'

                    # Get all verses after the current verse of the chapter and next chapter
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
                
                # Get all chapters for the given book
                sql_query = """
                    SELECT chapter
                    FROM new_testament.nt
                    WHERE book LIKE %s;
                """
                chapters = execute_query(sql_query, (f'{book_abbrev}%',), fetch='all') or []

                # Extract unique chapters and sort
                unique_chapters = set(int(row[0]) for row in chapters)
                chapter_list = sorted(map(str, unique_chapters), key=lambda x: int(x))

                                
                if prev_record is not None:
                    
                    abbreviation = prev_record[0]
                    
                    # Ensure the input is capitalized
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
                    
                    # Ensure the input is capitalized
                    if abbreviation[0].isdigit():
                        abbreviation = abbreviation[0] + abbreviation[1:].capitalize()
                    else:
                        abbreviation = abbreviation.capitalize()
                    
                    next_book = convert_book_name(abbreviation) if abbreviation in nt_abbrev else None
                    if not next_book:
                        next_book = abbreviation
                    
                    next_ref = f'?book={next_book}&chapter={next_record[1]}&verse={next_record[2]}'

                
                
                # GET GREEK INTERLINEAR
                
                # Convert references to 'Gen.1.1-' format
                if book in book_abbreviations:
                    book_abbrev = book_abbreviations[book]
                    rbt_grk_ref = f'{book_abbrev}.{chapter_num}.{verse_num}-'
                else:
                    rbt_grk_ref = f'{book}.{chapter_num}.{verse_num}-'

                # Query strongs_greek for the given verse reference
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
                        
                        # For AI assistance
                        entries.append({
                            "seq": i,
                            "lemma": lemma,
                            "english": english,
                            "morph": morph,
                            "morph_description": morph_desc,
                        })
                        
                        # check and replace words
                        strongs, lemma, english = replace_words(strongs, lemma, english)

                        interlinear += '<table class="tablefloat">\n<tbody>\n'
                        interlinear += '<tr>\n<td class="interlinear" height="160" valign="middle" align="left">\n'
                        interlinear += f'<span class="pos"><a href="https://biblehub.com/greek/{strongs}.htm" target="_blank">Strongs {strongs}</a></span>&nbsp;\n'
                        interlinear += f'<span class="strongsnt2"> <a href="https://biblehub.com/greek/strongs_{strongs}.htm" target="_blank">[list]</a></span><br>\n'
                        
                        # Get Greek Lexicographical Links
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

                        # Set color
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


                # collect footnotes if any
                if rbt_html is not None:
      
                    footnote_references = re.findall(r'\?footnote=(\d+-\d+-\d+[a-zA-Z]?)', rbt_html)
                    footnote_list = footnote_references
                  
                    # Create a list to store footnote contents using get_footnote function
                    footnote_contents = []
                    for footnote_id in footnote_list:
                        
                        footnote_content = get_footnote(footnote_id, book_abbrev, chapter_num, verse_num) # get_footnote function
                        footnote_contents.append(footnote_content)
                    
        

            ##### Fetch Smith Literal Translation Verse ##############
            try:
                
                slt_reference = bible.get_references(f'{book} {chapter_num}:{verse_num}')
                slt_ref = slt_reference[0]
                slt_book = slt_ref.book.name
                slt_book = slt_book.title()

                # Query the verses table
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
                book=englxx_book)  # run book filter
            eng_lxx = eng_lxx.filter(chapter=chapter_num) # run chapter filter
            eng_lxx = eng_lxx.filter(startVerse=verse_num)  # run verse filter
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
                        if data:  # Only assign if data is non-empty
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
            #print('Verse Data Cached: ', cache_key_base)

            return data

        # Get whole chapter
        elif book in old_testament_books:
            # Convert references to 'Gen.1.1-' format
            if book in book_abbreviations:
                book_abbrev = book_abbreviations[book]
                rbt_heb_ref = f'{book_abbrev}.{chapter_num}.{verse_num}-'
                rbt_heb_chapter = f'{book_abbrev}.{chapter_num}.'
            else:
                rbt_heb_ref = f'{book}.{chapter_num}.{verse_num}-'
                rbt_heb_chapter = f'{book}.{chapter_num}.'
                book_abbrev = book

            # Get all HTML for the chapter
            chapter_reader = execute_query(
                "SELECT Ref, html FROM old_testament.hebrewdata WHERE ref LIKE %s ORDER BY ref;",
                (f'{rbt_heb_chapter}%',),
                fetch='all'
            )

            # Get full data for the chapter
            data = execute_query(
                "SELECT id, Ref, Eng, html, footnote FROM old_testament.hebrewdata WHERE Ref LIKE %s ORDER BY ref;",
                (f'{rbt_heb_chapter}%',),
                fetch='all'
            )

            # Get list of all unique chapters
            rbt_ref = rbt_heb_chapter[:4]
            chapter_references = execute_query(
                "SELECT Ref FROM old_testament.hebrewdata WHERE Ref LIKE %s;",
                (f'{rbt_ref}%',),
                fetch='all'
            )

            commentary = None

            # Extract verse numbers as integers and group data
            regex_pattern = re.compile(fr'{book_abbrev}\.{chapter_num}\.(\d+)')
            
            # Create a dictionary to group by verse number
            verse_groups = {}
            
            for item in data:
                ref = item[1]
                eng = item[2]
                html_content = item[3]
   
                match = regex_pattern.search(ref)
                if match:
                    verse_num = int(match.group(1))  # Convert to integer for proper sorting

                    if verse_num not in verse_groups:
                        verse_groups[verse_num] = []
                    
                    verse_groups[verse_num].append((eng, html_content))

            # Sort by verse number and create the final html dictionary
            html = {}
            sorted_verse_nums = sorted(verse_groups.keys())

            for verse_num in sorted(verse_groups.keys()):  # Sort by integer verse numbers
                verse_key = f"{verse_num:02d}"  # Format as 01, 02, 03, etc. consistently
                
                # Combine all entries for this verse
                eng_parts = []
                html_parts = []
                
                for eng, html_content in verse_groups[verse_num]:
                    if eng:
                        eng_parts.append(eng)
                    if html_content:
                        html_parts.append(html_content)
                
                # Store as tuple of combined parts
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

            # Cache whole OT chapter
            cache.set(cache_key_base, data)
            return data
           
        elif book in new_testament_books:
            
            if book in book_abbreviations:
                book_abbrev = book_abbreviations[book]

            # Get all verses for the chapter
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

            # Get all chapters for the book
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
            
            # Cache whole NT chapter
            cache.set(cache_key_base, data)
            #print('NT Chapter Cached: ', cache_key_base)

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
        # Use the cached data
        cached_data['cached_hit'] = True
        return cached_data

# / root home
def search(request):
    query = request.GET.get('q')  # keyword search form used
    ref_query = request.GET.get('ref')
    chapter_num = request.GET.get('chapter')
    book = request.GET.get('book')
    verse_num = request.GET.get('verse')
    footnote_id = request.GET.get('footnote')
    language = request.GET.get('lang', 'en')  # Get language parameter, default to English
    
    error = None
    reference = None
    
    # REFERENCE SEARCH
    if ref_query:

        try:
            reference = bible.get_references(ref_query)
        except (InvalidBookError, InvalidChapterError,
                InvalidVerseError) as e:
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
   
    # KEYWORD SEARCH return search_results.html
    if query:
        # New behavior: return search_input.html and let JavaScript handle the search
        context = {'query': query, 'scope': request.GET.get('scope', 'all')}
        return render(request, 'search_input.html', context)
        
        # OLD CODE BELOW (commented out - keeping for reference)
        """
        results = []
        gen_results = []
        rbt_result_count = 0
        links = []

        # Function to check if query is within the text content only
        def is_query_in_text_content(html, query):
            soup = BeautifulSoup(html, "html.parser")
            text_content = soup.get_text()
            return query.lower() in text_content.lower()

        def process_genesis_results(query):
            # Retrieve results from the Genesis model
            results = Genesis.objects.filter(html__icontains=query)
            filtered_results = []

            # Strip only paragraph tags from results and apply bold to search query
            for result in results:
                if is_query_in_text_content(result.html, query):
                    # Remove all tags
                    result.html = re.sub(r'<[^>]+>', '', result.html)

                    # Apply bold to search query
                    result.html = re.sub(
                        f'({re.escape(query)})',
                        r'<strong>\1</strong>',
                        result.html,
                        flags=re.IGNORECASE
                    )

                    filtered_results.append(result)
            
            # Count the number of results
            rbt_result_count = len(filtered_results)
            
            return filtered_results, rbt_result_count

        if book == "Gen":
            gen_results, result_count = process_genesis_results(query)
            rbt_result_count += result_count

        # Search the Hebrew or Greek databases
        nt_books = [
            'Mat', 'Mar', 'Luk', 'Joh', 'Act', 'Rom', '1Co', '2Co', 'Gal', 'Eph',
            'Phi', 'Col', '1Th', '2Th', '1Ti', '2Ti', 'Tit', 'Phm', 'Heb', 'Jam',
            '1Pe', '2Pe', '1Jo', '2Jo', '3Jo', 'Jud', 'Rev'
        ]
        ot_books = [
                'Exo', 'Lev', 'Num', 'Deu', 'Jos', 'Jdg', 'Rut', '1Sa', '2Sa',
                '1Ki', '2Ki', '1Ch', '2Ch', 'Ezr', 'Neh', 'Est', 'Job', 'Psa', 'Pro',
                'Ecc', 'Sng', 'Isa', 'Jer', 'Lam', 'Eze', 'Dan', 'Hos', 'Joe', 'Amo',
                'Oba', 'Jon', 'Mic', 'Nah', 'Hab', 'Zep', 'Hag', 'Zec', 'Mal'
            ]
        
        if book == 'all':
            results = []
            gen_results, gen_result_count = process_genesis_results(query)
            rbt_result_count += gen_result_count

            # Query OT verses containing the text
            ot_rows = execute_query(
                "SELECT book, chapter, verse, html FROM old_testament.ot WHERE html LIKE %s;",
                (f'%{query}%',),
                fetch='all'
            )

            for row in ot_rows:
                if is_query_in_text_content(row[3], query):
                    # Remove all tags
                    row_html = re.sub(r'<[^>]+>', '', row[3])

                    # Apply bold to search query
                    row_html = re.sub(
                        f'({re.escape(query)})',
                        r'<strong>\1</strong>',
                        row_html,  
                        flags=re.IGNORECASE
                    )
                    book_name = convert_book_name(row[0])
                    #print(f"Book name: {book_name},{row[0]}")
                    results.append((book_name, row[1], row[2], row_html))

            # Query NT verses containing the text
            nt_rows = execute_query(
                "SELECT book, chapter, startVerse, rbt FROM new_testament.nt WHERE rbt LIKE %s;",
                (f'%{query}%',),
                fetch='all'
            )

            for row in nt_rows:
                if is_query_in_text_content(row[3], query):
                    # Remove all tags
                    row_html = re.sub(r'<[^>]+>', '', row[3])
                    # Apply bold to search query
                    row_html = re.sub(
                        f'({re.escape(query)})',
                        r'<strong>\1</strong>',
                        row_html,  
                        flags=re.IGNORECASE
                    )
                    book_name = convert_book_name(row[0])
                    results.append((book_name, row[1], row[2], row_html))
            
            rbt_result_count += len(results)   
    
        elif book == 'NT':

            # Query NT verses containing the search text
            nt_rows = execute_query(
                "SELECT book, chapter, startVerse, rbt FROM new_testament.nt WHERE rbt LIKE %s;",
                (f"%{query}%",),
                fetch='all'
            )

            for row in nt_rows:
                if is_query_in_text_content(row[3], query):
                    # Remove all tags
                    row_html = re.sub(r'<[^>]+>', '', row[3])
                    # Apply bold to search query
                    row_html = re.sub(
                        f'({re.escape(query)})',
                        r'<strong>\1</strong>',
                        row_html,  
                        flags=re.IGNORECASE
                    )
                    book_name = convert_book_name(row[0])
                    results.append((book_name, row[1], row[2], row_html))
            rbt_result_count = len(results)    
    
        elif book == 'OT':
            gen_results, result_count = process_genesis_results(query)
            rbt_result_count =+ result_count
            

            # Query OT verses containing the search text
            ot_rows = execute_query(
                "SELECT book, chapter, verse, html FROM old_testament.ot WHERE html LIKE %s;",
                (f"%{query}%",),
                fetch='all'
            )

            for row in ot_rows:
                if is_query_in_text_content(row[3], query):
                    # Remove all tags
                    row_html = re.sub(r'<[^>]+>', '', row[3])
                    # Apply bold to search query
                    row_html = re.sub(
                        f'({re.escape(query)})',
                        r'<strong>\1</strong>',
                        row_html,  
                        flags=re.IGNORECASE
                    )
                    book_name = convert_book_name(row[0])
                    results.append((book_name, row[1], row[2], row_html))
            rbt_result_count += len(results)


        elif book in ot_books:

            # Query OT verses for a specific book containing the search text
            ot_rows = execute_query(
                "SELECT book, chapter, verse, html FROM old_testament.ot WHERE book = %s AND html LIKE %s;",
                (book, f"%{query}%"),
                fetch='all'
            )

            for row in ot_rows:
                if is_query_in_text_content(row[3], query):
                    # Remove all tags
                    row_html = re.sub(r'<[^>]+>', '', row[3])
                    # Apply bold to search query
                    row_html = re.sub(
                        f'({re.escape(query)})',
                        r'<strong>\1</strong>',
                        row_html,  
                        flags=re.IGNORECASE
                    )
                    book_name = convert_book_name(row[0])
                    
                    results.append((book_name, row[1], row[2], row_html)) 
            rbt_result_count += len(results)

        elif book in nt_books:

            # Query NT verses for a specific book containing the search text
            nt_rows = execute_query(
                "SELECT book, chapter, startVerse, rbt FROM new_testament.nt WHERE book = %s AND rbt LIKE %s;",
                (book, f"%{query}%"),
                fetch='all'
            )

            for row in nt_rows:
                if is_query_in_text_content(row[3], query):
                    # Remove all tags
                    row_html = re.sub(r'<[^>]+>', '', row[3])
                    # Apply bold to search query
                    row_html = re.sub(
                        f'({re.escape(query)})',
                        r'<strong>\1</strong>',
                        row_html,  
                        flags=re.IGNORECASE
                    )
                    book_name = convert_book_name(row[0])
                    
                    results.append((book_name, row[1], row[2], row_html))
            rbt_result_count += len(results)   

        query_count = 0

        # Ensure a missing book param defaults to searching all books
        if not book:
            book = 'all'

        # if individual book is searched convert the full to the abbrev
        if book not in ['NT', 'OT', 'all']:
            book2 = convert_book_name(book) or book
            # If conversion fails, fall back to 'all'
            if book2:
                book = book2.lower()
            else:
                book = 'all'
                book2 = 'All Books'
        else:
            book2 = book

        if book2 == 'all':
            book2 = 'All Books'

        page_title = f'Search results for "{query}"'
        context = {'gen_results': gen_results,
                   'results': results,
                   'query': query, 
                   'rbt_result_count': rbt_result_count, 
                   'links': links, 
                   'query_count': query_count,
                   'book2': book2, 
                   'book': book }
        return render(request, 'search_results.html', {'page_title': page_title, **context})
        """
    
    # SINGLE VERSE return verse.html
    elif book and chapter_num and verse_num:

        try:
            
            results = get_results(book, chapter_num, verse_num, language)
            
            if not results['rbt_greek']:
                if not results['hebrew']:
                    context = {'error': 'Verse is Invalid'}
                    return render(request, 'search_input.html', context)
            
            replacements = load_json('interlinear_english.json') # NT
            greek = results['rbt_greek']
            interlinear = results['interlinear'] # NT
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
            #morph_row = results['morph_row']
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

            context = {'previous_verse': previous_verse, 
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
                    'error': error,
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
            context = {'error': "Invalid verse" }
            return render(request, 'search_input.html', context)
        
    # SINGLE CHAPTER
    elif book and chapter_num:
        
        try:

            source_book = book
            results = get_results(book, chapter_num, None, language)
            
            hebrew_literal = ""
            nt_literal = ""
            paraphrase = ""
            
            # Check if the Django Genesis object is returned
            if book == 'Genesis':
                
                rbt = results['rbt']
                cached_hit = results['cached_hit']
                chapter_list = results['chapter_list']
                notes_sources: list[str] = []
                
                # Handle translations for non-English languages
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


            # parse the list for other books
            else:
                chapter_rows = results['chapter_reader']
                html_rows = results['html']
                chapter_list = results['chapter_list']
                cached_hit = results['cached_hit']
                commentary = results['commentary']
                
                print(f"[RENDER DEBUG] Book: '{book}', Has chapter_rows: {len(chapter_rows) if chapter_rows else 0}")
                print(f"[RENDER DEBUG] Is NT book: {book in new_testament_books}")
                print(f"[RENDER DEBUG] Is OT book: {book in old_testament_books}")
                
                if commentary is not None:
                    commentary = commentary[0]

                if book in new_testament_books:

                    # Handle translations for non-English languages
                    translation_quota_exceeded = False
                    verses_to_translate = {}
                    footnotes_to_translate = {}
                    
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
                        # Only fetch verse translations (where footnote_id is None) meaning it is the verse text
                        # We must use proper filtering to assume new API handles creation
                        
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
                        # Since translations now contain complete HTML, simply replace the entire verse
                        updated_rows = []
                        for row in chapter_rows:
                            bk, ch_num, vrs, html_verse = row
                            if int(vrs) in translated_verses:
                                # Complete replacement - translated HTML includes headers, spans, everything
                                html_verse = translated_verses[int(vrs)]
                            updated_rows.append((bk, ch_num, vrs, html_verse))
                        chapter_rows = updated_rows

                    footnotes_collection = {}
                    def query_footnote(book, sup_text):
                        # Use book abbreviation for table name lookup
                        book_abbrev = book_abbreviations.get(book, book)
                        footnote_id = f"{book}-{sup_text}"

                        # Determine schema based on book classification
                        # book here is likely an abbreviation from the DB (e.g., 'Psa')
                        # We need to check the full book name against the lists
                        schema = 'new_testament' if book in new_testament_books else 'old_testament'
                        
                        print(f"[QUERY_FOOTNOTE DEBUG] book='{book}', abbrev='{book_abbrev}', sup_text='{sup_text}', schema={schema}")

                        # Determine table name using abbreviation
                        # Books starting with numbers have 'table_' prefix (NT only)
                        abbrev_lower = book_abbrev.lower() # type: ignore
                        if schema == 'new_testament' and abbrev_lower[0].isdigit():
                            table_name = f"table_{abbrev_lower}_footnotes"
                        else:
                            table_name = f"{abbrev_lower}_footnotes"

                        # Set schema
                        execute_query(f"SET search_path TO {schema};")

                        # Footnote IDs in DB use abbreviation format (e.g., '1Jo-1')
                        db_footnote_id = f"{book_abbrev}-{sup_text}"
                        
                        # Query the footnote
                        try:
                            result = execute_query(
                                f"SELECT footnote_html FROM {schema}.{table_name} WHERE footnote_id = %s",
                                (db_footnote_id,),
                                fetch='one'
                            )
                            # Return footnote text or None
                            return result[0] if result else None
                        except Exception as e:
                            print(f"[FOOTNOTE QUERY ERROR] Schema: {schema}, Table: {table_name}, ID: {db_footnote_id}, Error: {e}")
                            return None

                    for row in chapter_rows:
                        bk, chapter_num, vrs, html_verse = row
                        if html_verse:

                            close_text = '' if html_verse.endswith('</span>') else '<br>'

                            sup_texts = re.findall(r'<sup>(.*?)</sup>', html_verse)
                            for sup_text in sup_texts:
                                # Query the database for each book and number
                                data = query_footnote(bk, sup_text)
                                
                                # Store footnote in collection
                                if data:
                                    footnotes_collection[sup_text] = {
                                        'verse': vrs,
                                        'content': data,
                                        'id': sup_text
                                    }
                                
                                # Replace the reference with a link with hover content
                                # html_verse = html_verse.replace(
                                #     f'<sup>{sup_text}</sup>', 
                                #     f'<div class="footnote_content"><sup><a href="#footnote-{sup_text}" class="footnote-link">{sup_text}</a></sup><div class="footnote_hover">{data}</div></div>'
                                # )

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
                    
                    # Handle footnote translations for non-English languages
                    if language != 'en' and footnotes_collection:
                        # Check which footnotes need translation
                        # DB stores footnote_id as 'Book-X' format (e.g., 'John-1', 'John-1a')
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
                            # footnote_key is the sup_text (e.g. '1', '1a')
                            # DB stores full ID as 'Book-X' (e.g. 'John-1')
                            full_footnote_id = f"{book}-{footnote_key}"
                            if full_footnote_id not in existing_footnote_ids:
                                footnotes_to_translate[footnote_key] = True

                        # Blocking translation REMOVED here
                        # Logic moved to translate_chapter_api
                        
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
                            # footnote_id in collection is the short key (e.g. '1', '1a')
                            # stored footnote_id is full key (e.g. 'John-1-1-1')
                            # Check if the collected footnote ID is just the suffix or full?
                            # In collection: 'id': sup_text.
                            # So we construct full ID for lookup.
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
                        # DEBUG PRINT
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
                        'html': nt_literal, 
                        'paraphrase': paraphrase, 
                        'book': display_book,
                        'original_book': original_book,  # Keep original for API calls
                        'chapter_num': chapter_num, 
                        'chapter_list': chapter_list,
                        'footnotes': footnotes_collection,
                        'current_language': language,
                        'supported_languages': SUPPORTED_LANGUAGES,
                        'translation_quota_exceeded': translation_quota_exceeded,
                        'needs_translation': needs_translation
                    }
                    
                    return render(request, 'nt_chapter.html', {'page_title': page_title, **context})

                # Rest of Hebrew books (Old Testament except Genesis)
                else:
                    # Handle translations for non-English languages
                    translation_quota_exceeded = False
                    verses_to_translate = {}
                    footnotes_to_translate = {}
                    book_name_translation = None
                    translated_footnotes = {}  # Initialize here for use later
                    
                    # Build verse_data from html_rows (already grouped by verse) - NOT chapter_rows (word-level)
                    # html_rows is a dict: {'01': (eng_literal, html_paraphrase), '02': ...}
                    sorted_verse_keys = sorted(html_rows.keys(), key=lambda x: int(x) if x.isdigit() else float('inf'))
                    
                    if language != 'en':
                        # Check which verses need translation (completed OR processing)
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
                        # For English, build verse_data from html_rows (one entry per verse)
                        verse_data = []
                        for vrs_key in sorted_verse_keys:
                            eng_literal, html_paraphrase = html_rows[vrs_key]
                            verse_num_int = int(vrs_key) if vrs_key.isdigit() else float('inf')
                            verse_data.append((verse_num_int, vrs_key, html_paraphrase))
                    
                    # Collect footnotes from verse HTML for translation
                    footnotes_collection = {}
                    
                    # Process sorted verses (one entry per verse now)
                    for verse_num, vrs, html_verse in verse_data:
                        # Strip leading zeros for display and links
                        display_vrs = vrs.lstrip('0') or '0'
                        if html_verse:
                            # Extract footnote references from verse HTML
                            sup_texts = re.findall(r'\?footnote=([^"&\s]+)', html_verse)
                            for sup_text in sup_texts:
                                if sup_text not in footnotes_collection:
                                    # Get footnote content from OT footnotes
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

                    # Handle footnote translations for non-English languages
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

        except Exception as e:   

            context = {'error': e }
            return render(request, 'search_input.html', context)
    
    # SINGLE FOOTNOTE
    elif footnote_id:
        
        if book:
            # footnote_id format: abbrev-chapter-verse-footnote (e.g., Psa-150-2-02)
            footnote_parts = footnote_id.split('-')
            
            # Handle different formats
            if len(footnote_parts) == 4:
                # Format: Psa-150-2-02 (abbrev-chapter-verse-footnote)
                book_abbrev_from_url, chapter, verse, footnote_ref = footnote_parts
            elif len(footnote_parts) == 3:
                # Format: 150-2-02 (chapter-verse-footnote)
                chapter, verse, footnote_ref = footnote_parts
            else:
                # Fallback
                footnote_ref = footnote_parts[-1]
                chapter = footnote_parts[0] if len(footnote_parts) > 1 else '1'
                verse = footnote_parts[1] if len(footnote_parts) > 2 else '1'
            
            chapter_ref = chapter
            verse_ref = verse
            db_footnote_id = f'{book}-{footnote_ref}'

            if book in book_abbreviations:
                book_abbrev = book_abbreviations[book]
                full_book_name = book  # Book is already full name
            else:
                book_abbrev = book.lower()
                abbrev_to_book = {abbrev: bk for bk, abbrev in book_abbreviations.items()}
                full_book_name = abbrev_to_book.get(book, book)

            if book[0].isdigit():
                table = f"table_{book_abbrev}_footnotes"
            else:
                table = f"{book_abbrev}_footnotes"

            # Check for translated footnote first if language is not English
            footnote_html = None
            if language and language != 'en':
                try:
                    # The stored format is: book-abbrev-chapter-verse-footnote (e.g., Psalms-Psa-150-2-02)
                    # The URL footnote_id is: abbrev-chapter-verse-footnote (e.g., Psa-150-2-02)
                    # So construct the full ID
                    full_footnote_id = f'{book}-{footnote_id}'  # Psalms-Psa-150-2-02
                    
                    possible_ids = [
                        full_footnote_id,  # Psalms-Psa-150-2-02
                        f'{book}-{chapter}-{verse}-{footnote_ref}',  # Psalms-150-2-02
                        f'{book}-{footnote_ref}',  # Psalms-02
                        db_footnote_id,  # Psalms-02
                    ]
                    translation = VerseTranslation.objects.filter(
                        book=book,
                        language_code=language,
                        footnote_id__in=possible_ids,
                        status='completed'
                    ).first()
                    if translation and translation.footnote_text:
                        footnote_html = translation.footnote_text
                except Exception as e:
                    print(f"Error checking footnote translation: {e}")

            # Fall back to original if no translation found
            if not footnote_html:
                # Determine correct schema based on book classification
                schema = 'new_testament' if book in new_testament_books else 'old_testament'
                
                # For OT books, the footnote ID format might be just the abbreviation + number
                # e.g., for Psa-150-2-02, the DB stores it as Psa-02
                if schema == 'old_testament':
                    # Use just book abbreviation + footnote number
                    db_query_id = f"{book_abbrev}-{footnote_ref}"
                else:
                    # NT uses full book name + footnote suffix
                    db_query_id = db_footnote_id
                
                try:
                    data = execute_query(
                        f"SELECT footnote_html FROM {schema}.{table} WHERE footnote_id = %s",
                        (db_query_id,),
                        fetch='all'
                    )
                    footnote_html = data[0][0] if data and len(data) > 0 else None
                except Exception as e:
                    print(f"[FOOTNOTE JSON ERROR] Schema: {schema}, Table: {table}, ID: {db_query_id}, Error: {e}")
                    footnote_html = None
                
                if not footnote_html:
                    footnote_html = "Footnote not found."

            # Create an HTML table with two columns
            table_html = f'<tr><td style="border-bottom: 1px solid #d2d2d2;"><a href="?footnote={chapter}-{verse}-{footnote_ref}&book={book_abbrev}&lang={language}">{footnote_ref}</a></td><td style="border-bottom: 1px solid #d2d2d2;">{footnote_html}</td></tr>'

            footnote_html = f'<table><tbody>{table_html}</tbody></table>'
            
            page_title = f'{full_book_name} {chapter}:{verse}'
            context = {'footnote_html': footnote_html,
            'footnote': db_footnote_id,
            'book': full_book_name,
            'chapter_ref': chapter_ref, 
            'verse_ref': verse_ref, 
            }

            return render(request, 'footnote.html', {'page_title': page_title, **context})

        # Genesis and other OT footnotes
        else:

            footnote_split = footnote_id.split('-')
            # Check the length of the split result
            if len(footnote_split) == 3:
                chapter_ref, verse_ref, footnote_ref = footnote_split

                # Genesis footnotes only
                book = 'Genesis'
                footnote_html = get_footnote(footnote_id, book)
                footnote_html = f'<table><tbody>{footnote_html}</tbody></table>'

                verse_results = Genesis.objects.filter(
                    chapter=chapter_ref, verse=verse_ref).values('html')
                hebrew_result = Genesis.objects.filter(
                    chapter=chapter_ref, verse=verse_ref).values('hebrew')

                hebrew = hebrew_result[0]['hebrew']

                verse_html = verse_results[0]['html']
                verse_html = re.sub(r'#(sdfootnote(\d+)sym)',
                                    rf'?footnote={chapter_ref}-{verse_ref}-\g<2>', verse_html)
                verse_results[0]['html'] = verse_html
                book = "Genesis"

            elif len(footnote_split) == 4:
                book, chapter_ref, verse_ref, footnote_ref = footnote_split
                footnote_id = f'{book}.{chapter_ref}.{verse_ref}-{footnote_ref}'
                
                # function call to get footnote HTML content
                footnote_html = get_footnote(footnote_id, book)
                footnote_html = f'<table><tbody>{footnote_html}</tbody></table>'
                
                rbt_heb_ref = f'{book}.{chapter_ref}.{verse_ref}'
                execute_query("SET search_path TO old_testament;")

                # Fetch html and hebrew columns for the given Ref
                rowdata = execute_query(
                    "SELECT html, hebrew FROM old_testament.ot WHERE Ref = %s",
                    (rbt_heb_ref,),
                    fetch='one'
                )
                    
                # Check if the result is not None
                if rowdata:
                    verse_html, hebrew = rowdata

                else:
                    hebrew = "Not found"
                    verse_html = "Not found"

                book = convert_book_name(book)


            context = {'book': book,
                    'hebrew': hebrew, 
                    'verse_html': verse_html, 
                    'footnote_html': footnote_html,
                    'footnote': footnote_id, 
                    'chapter_ref': chapter_ref, 
                    'verse_ref': verse_ref, 
                    }
        
            return render(request, 'footnote.html', context)

    else:
        context = {'error': error }
        return render(request, 'search_input.html', context)
    
# storehouse_view has been moved to search/views/storehouse_views.py
# and is imported at the top of this file for URL routing compatibility


def word_view(request):
    rbt_heb_ref = request.GET.get('word')
    use_niqqud = request.GET.get('niqqud')

    if use_niqqud == 'no':
        field = 'combined_heb'
    else:
        field = 'combined_heb_niqqud'

    execute_query("SET search_path TO old_testament;")

    # Fetch the specific row
    rows_data = execute_query(
        f"SELECT id, Ref, {field} FROM old_testament.hebrewdata WHERE ref = %s",
        (rbt_heb_ref,),
        fetch='all'
    )

    if rows_data:
        id, ref, heb = rows_data[0]

        # Count occurrences grouped by ref
        search_results = execute_query(
            f"SELECT ref, COUNT(*) AS count FROM old_testament.hebrewdata WHERE {field} = %s GROUP BY ref",
            (heb,),
            fetch='all'
        )
    else:
        search_results = []



    html = '<ol>'
    count = 0
    for result in search_results:
        reference = result[0]  # 'ref' column
        reference = reference.split('-')
        reference = reference[0]
        verse = reference.split('.')
        
        bookref = verse[0]
        bookref = convert_book_name(bookref) or bookref
        bookref = bookref.lower()
        bookref = bookref.replace(' ', '_')

        chapter = verse[1]
        verse = verse[2]
        
        link = f'<a href="https://biblehub.com/{bookref}/{chapter}-{verse}.htm">{reference}</a>'
    
        html += f'<li style="margin-top: 0px; font-size: 12px;">{link}</li>'
        count += 1

    html = f'{html}</ol>'
    count = str(count)
    context = {'occurrences': html, 'count': count, 'heb_word': heb }
    
    return render(request, 'word.html', context)

def update_statistics_view(request):
    """Render the statistics dashboard page"""
    return render(request, 'statistics.html')

@csrf_exempt
@require_http_methods(["GET"])
def update_statistics_api(request):
    """API endpoint for fetching update statistics."""
    try:
        days_param = request.GET.get('days', '30')
        end_date = datetime.now()

        # Handle "all" case for days parameter
        if days_param == 'all':
            start_date = datetime(2024, 1, 1)
            days_back = (end_date - start_date).days
        else:
            try:
                days_back = max(0, int(days_param))
                start_date = end_date - timedelta(days=days_back)
            except (ValueError, TypeError):
                days_back = 30
                start_date = end_date - timedelta(days=30)

        # Base queryset filtered by date range
        base_queryset = TranslationUpdates.objects.filter(
            date__gte=start_date,
            date__lte=end_date
        )

        # 1. Daily updates
        daily_updates = list(
            base_queryset
            .annotate(day=TruncDate('date'))
            .values('day')
            .annotate(count=Count('date'))
            .order_by('day')
        )

        daily_data = {}
        for item in daily_updates:
            daily_data[item['day'].strftime('%Y-%m-%d')] = item['count']

        complete_daily_data = []
        current_date = start_date.date()
        while current_date <= end_date.date():
            date_str = current_date.strftime('%Y-%m-%d')
            complete_daily_data.append({
                'date': date_str,
                'count': daily_data.get(date_str, 0)
            })
            current_date += timedelta(days=1)

        # 2. Top 100 references
        top_references = list(
            base_queryset
            .exclude(reference__isnull=True)
            .exclude(reference__exact='')
            .exclude(reference='[]')
            .values('reference')
            .annotate(count=Count('date'))
            .order_by('-count')[:100]
        )

        # Generate links for each reference (Format A only)
        base_url = "https://rbtproject.up.railway.app"
        for item in top_references:
            reference = item['reference']
            try:
                parts = reference.strip().split()
                if len(parts) == 2:
                    book = parts[0]
                    chapter, verse = parts[1].split(':')
                    query_params = urlencode({
                        'book': book,
                        'chapter': chapter,
                        'verse': verse
                    })
                    item['link'] = f"{base_url}?{query_params}"
                else:
                    item['link'] = None
            except Exception:
                item['link'] = None

        # 3. Weekly aggregation
        weekly_updates = list(
            base_queryset
            .annotate(week=TruncWeek('date'))
            .values('week')
            .annotate(count=Count('date'))
            .order_by('week')
        )

        # 4. Monthly aggregation
        monthly_updates = list(
            base_queryset
            .annotate(month=TruncMonth('date'))
            .values('month')
            .annotate(count=Count('date'))
            .order_by('month')
        )

        # 5. Hourly pattern
        hourly_updates = (
            base_queryset
            .annotate(hour=TruncHour('date'))
            .values('hour')
            .annotate(count=Count('date'))
            .order_by('hour')
        )

        hourly_pattern = []
        hour_counts = defaultdict(int)
        for item in hourly_updates:
            hour_counts[item['hour'].hour] += item['count']

        for hour in range(24):
            hourly_pattern.append({'hour': hour, 'count': hour_counts.get(hour, 0)})

        # 6. Weekday pattern (last 4 weeks)
        four_weeks_ago = end_date - timedelta(weeks=4)
        weekday_stats = defaultdict(int)
        weekday_data = TranslationUpdates.objects.filter(
            date__gte=four_weeks_ago,
            date__lte=end_date
        ).values('date')

        for item in weekday_data:
            weekday = item['date'].strftime('%A')
            weekday_stats[weekday] += 1

        weekday_pattern = [
            {'day': day, 'count': weekday_stats[day]}
            for day in ['Monday', 'Tuesday', 'Wednesday', 'Thursday', 'Friday', 'Saturday', 'Sunday']
        ]

        # 7. Summary statistics
        total_updates = base_queryset.count()
        unique_references = base_queryset.values('reference').distinct().count()
        avg_daily = total_updates / max(days_back, 1)

        TOTAL_BIBLE_VERSES = 31102
        bible_completion_percentage = round((unique_references / TOTAL_BIBLE_VERSES) * 100, 2)

        # 8. Most active day
        most_active_day = max(complete_daily_data, key=lambda x: x['count']) if complete_daily_data else None

        # 9. Count unique OT references (pattern: e.g., '2-16-86')
        ot_footnote_pattern = re.compile(r'^\d+-\d+-\d+$')
        ot_footnote_references = set()
        for ref in base_queryset.exclude(reference__isnull=True).exclude(reference__exact='').values_list('reference', flat=True):
            if ot_footnote_pattern.match(ref.strip()):
                ot_footnote_references.add(ref.strip())
        ot_footnote_count = len(ot_footnote_references)
        # add the Genesis footnote count
        ot_footnote_count = ot_footnote_count + GenesisFootnotes.objects.filter(footnote_id__isnull=False).count()

        # Get all footnote tables
        footnote_tables = execute_query("""
            SELECT table_name 
            FROM information_schema.tables 
            WHERE table_schema = 'new_testament' 
            AND table_name LIKE '%_footnotes'
        """, fetch='all')

        nt_footnote_count = 0

        for table_row in footnote_tables:
            table_name = table_row[0]
            count_result = execute_query(
                f"SELECT COUNT(*) FROM new_testament.{table_name} WHERE footnote_id IS NOT NULL",
                fetch='one'
            )
            if count_result:
                nt_footnote_count += count_result[0]


        return JsonResponse({
            'summary': {
                'total_updates': total_updates,
                'unique_references': unique_references,
                'ot_footnote_count': ot_footnote_count,
                'nt_footnote_count': nt_footnote_count,
                'average_daily': round(avg_daily, 0),
                'date_range': {
                    'start': start_date.strftime('%Y-%m-%d'),
                    'end': end_date.strftime('%Y-%m-%d'),
                    'days': 'all' if days_param == 'all' else days_back
                },
                'most_active_day': most_active_day
            },
            'daily_updates': complete_daily_data,
            'weekly_updates': [
                {
                    'week': item['week'].strftime('%Y-%m-%d'),
                    'count': item['count']
                } for item in weekly_updates
            ],
            'monthly_updates': [
                {
                    'month': item['month'].strftime('%Y-%m'),
                    'count': item['count']
                } for item in monthly_updates
            ],
            'top_references': top_references,
            'hourly_pattern': hourly_pattern,
            'weekday_pattern': weekday_pattern,
            'bible_completion': {
                'unique_verses': unique_references,
                'total_verses': TOTAL_BIBLE_VERSES,
                'percentage_complete': bible_completion_percentage
            }
        })

    except Exception as e:
        return JsonResponse({
            'error': str(e),
            'traceback': traceback.format_exc()
        }, status=500)
    

# =============================================================================
# COMPREHENSIVE BIBLE SEARCH API
# =============================================================================

import json
import unicodedata
from django.views.decorators.http import require_GET

# Hebrew character range for detection
HEBREW_RANGE = '\u0590-\u05FF'
# Greek character range for detection  
GREEK_RANGE = '\u0370-\u03FF\u1F00-\u1FFF'

def detect_script(text):
    """Detect if text contains Hebrew, Greek, or Latin characters"""
    has_hebrew = bool(re.search(f'[{HEBREW_RANGE}]', text))
    has_greek = bool(re.search(f'[{GREEK_RANGE}]', text))
    return {
        'hebrew': has_hebrew,
        'greek': has_greek,
        'latin': not has_hebrew and not has_greek
    }

def strip_hebrew_vowels(text):
    """Remove Hebrew niqqud (vowel points) from text"""
    niqqud_pattern = '[\u0591-\u05BD\u05BF\u05C1-\u05C5\u05C7]'
    return re.sub(niqqud_pattern, '', text)

def highlight_match(text, query, max_length=200):
    """Highlight search term in text and truncate around match"""
    if not text:
        return ''
    
    # Remove HTML tags for display
    clean_text = re.sub(r'<[^>]+>', '', str(text))
    
    # Find match position (case insensitive)
    pattern = re.compile(f'({re.escape(query)})', re.IGNORECASE)
    match = pattern.search(clean_text)
    
    if match:
        start_pos = max(0, match.start() - 50)
        end_pos = min(len(clean_text), match.end() + max_length - 50)
        excerpt = clean_text[start_pos:end_pos]
        
        if start_pos > 0:
            excerpt = '...' + excerpt
        if end_pos < len(clean_text):
            excerpt = excerpt + '...'
        
        # Apply highlighting
        highlighted = pattern.sub(r'<mark>\1</mark>', excerpt)
        return highlighted
    
    return clean_text[:max_length] + ('...' if len(clean_text) > max_length else '')


def search_results_page(request):
    """
    Full search results page with pagination.
    Renders the template which uses JavaScript to fetch results from the API.
    """
    query = request.GET.get('q', '').strip()
    scope = request.GET.get('scope', 'all').lower()
    page = max(int(request.GET.get('page', 1)), 1)
    
    if not query:
        return redirect('/search/')
    
    context = {
        'query': query,
        'scope': scope,
        'page': page,
    }
    return render(request, 'search_results_full.html', context)


@require_GET
def search_api(request):
    """
    Comprehensive Bible Search API
    
    Query params:
    - q: Search query (required)
    - scope: 'all', 'ot', 'nt', 'hebrew', 'greek', 'footnotes' (default: 'all')
    - type: 'keyword', 'reference', 'exact' (default: auto-detect)
    - limit: Max results per category (default: 20)
    - page: Page number for pagination (default: 1)
    """
    query = request.GET.get('q', '').strip()
    scope = request.GET.get('scope', 'all').lower()
    search_type = request.GET.get('type', 'auto')
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
    
    # Auto-detect search type
    if search_type == 'auto':
        # Check if it looks like a reference
        try:
            ref = bible.get_references(query)
            if ref:
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
        'references': []
    }
    
    counts = {
        'ot_verses': 0,
        'ot_hebrew': 0,
        'nt_verses': 0,
        'nt_greek': 0,
        'footnotes': 0,
        'references': 0
    }
    
    # Reference search
    if search_type == 'reference':
        try:
            refs = bible.get_references(query)
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
                    book_name = convert_book_name(row[0]) if row[0] else row[0]
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
                    book_name = convert_book_name(row[0]) if row[0] else row[0]
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
                    book_name = convert_book_name(book_code) if book_code else ''
                    
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
                    book_code = table_name.replace('_footnotes', '')
                    
                    nt_fn_rows = execute_query(
                        f"""
                        SELECT footnote_id, footnote_html 
                        FROM new_testament.{table_name} 
                        WHERE footnote_html ILIKE %s
                        LIMIT %s
                        """,
                        (f'%{query}%', limit // 5),  # Limit per table
                        fetch='all'
                    )
                    
                    for fn_row in nt_fn_rows or []:
                        parts = (fn_row[0] or '').split('-')
                        chapter = parts[0] if len(parts) > 0 else ''
                        verse = parts[1] if len(parts) > 1 else ''
                        book_name = convert_book_name(book_code) if book_code else book_code
                        
                        results['footnotes'].append({
                            'type': 'footnote',
                            'source': f'new_testament.{table_name}',
                            'book': book_name,
                            'footnote_id': fn_row[0],
                            'chapter': chapter,
                            'verse': verse,
                            'text': highlight_match(fn_row[1], query),
                            'url': f'/?book={book_name}&chapter={chapter}&verse={verse}'
                        })
                
                counts['footnotes'] = len(results['footnotes'])
                
            except Exception as e:
                print(f"Footnote search error: {e}")
    
    # Calculate totals
    total_results = sum(counts.values())
    
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
        'has_more': any(counts[k] > len(results[k]) for k in counts)
    })


@require_GET  
def search_suggestions(request):
    """Quick suggestions for autocomplete as user types"""
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


def footnote_json(request, footnote_id):
    """
    Return footnote content as JSON for popup display.
    Supports Genesis format (1-3-15), OT format (Eze-16-4-07), and NT format (Psa-150-2-02)
    """
    footnote_html = ""
    title = ""
    language = request.GET.get('lang', 'en')
    book = request.GET.get('book')  # Optional book parameter for NT
    
    try:
        footnote_parts = footnote_id.split('-')
        
        # Genesis format: 1-3-15 (chapter-verse-footnoteNum)
        if len(footnote_parts) == 3 and footnote_parts[0].isdigit():
            chapter_ref, verse_ref, footnote_ref = footnote_parts
            book = 'Genesis'
            title = f'Genesis {chapter_ref}:{verse_ref}'
            
            # Check for translation first
            if language and language != 'en':
                translation = VerseTranslation.objects.filter(
                    book=book,
                    language_code=language,
                    footnote_id__icontains=footnote_id,
                    status='completed'
                ).first()
                if translation and translation.footnote_text:
                    footnote_html = translation.footnote_text
            
            # Fallback to English
            if not footnote_html:
                results = GenesisFootnotes.objects.filter(
                    footnote_id=footnote_id).values('footnote_html')
                
                if results:
                    footnote_html = results[0]['footnote_html']
                else:
                    footnote_html = f"No footnote found for {footnote_id}."
        
        # NT format: Psa-150-2-02 (abbrev-chapter-verse-footnoteNum)
        elif len(footnote_parts) == 4 and not footnote_parts[0].isdigit():
            book_abbrev, chapter_ref, verse_ref, footnote_ref = footnote_parts
            
            # Map abbreviations to full book names
            abbrev_to_book = {abbrev: bk for bk, abbrev in book_abbreviations.items()}
            full_book_name = abbrev_to_book.get(book_abbrev, book_abbrev)
            
            # Determine if this is NT or OT book
            is_nt_book = full_book_name in new_testament_books
            
            title = f'{full_book_name} {chapter_ref}:{verse_ref}'
            # For OT books, use abbrev-footnote format (e.g., Psa-02)
            # For NT books, use fullname-footnote format (e.g., John-1)
            db_footnote_id = f'{book_abbrev}-{footnote_ref}' if not is_nt_book else f'{full_book_name}-{footnote_ref}'
            
            if language and language != 'en':
                # Try various footnote ID formats
                possible_ids = [
                    f'{full_book_name}-{footnote_id}',  # Psalms-Psa-150-2-02
                    f'{full_book_name}-{chapter_ref}-{verse_ref}-{footnote_ref}',  # Psalms-150-2-02
                    db_footnote_id,  # Psa-02 for OT, John-1 for NT
                ]
                translation = VerseTranslation.objects.filter(
                    book=full_book_name,
                    language_code=language,
                    footnote_id__in=possible_ids,
                    status='completed'
                ).first()
                if translation and translation.footnote_text:
                    footnote_html = translation.footnote_text
            
            # Fallback to English from database
            if not footnote_html:
                # Use correct schema based on book type
                schema = 'new_testament' if is_nt_book else 'old_testament'
                
                print(f"[FOOTNOTE JSON] Book: {full_book_name}, Abbrev: {book_abbrev}, Schema: {schema}, Is NT: {is_nt_book}")
                
                try:
                    if is_nt_book:
                        # NT books have separate footnote tables
                        if book_abbrev[0].isdigit():
                            table = f"table_{book_abbrev.lower()}_footnotes"
                        else:
                            table = f"{book_abbrev.lower()}_footnotes"
                        
                        result = execute_query(
                            f"SELECT footnote_html FROM {schema}.{table} WHERE footnote_id = %s",
                            (db_footnote_id,),
                            fetch='one'
                        )
                        if result and result[0]:
                            footnote_html = result[0]
                    else:
                        # OT books store footnotes in hebrewdata table
                        # Reference format: Psa.150.2-02
                        rbt_heb_ref = f'{book_abbrev}.{chapter_ref}.{verse_ref}-{footnote_ref}'
                        result = execute_query(
                            "SELECT footnote FROM old_testament.hebrewdata WHERE Ref = %s",
                            (rbt_heb_ref,),
                            fetch='one'
                        )
                        if result and result[0]:
                            footnote_html = result[0]
                    
                    if not footnote_html:
                        footnote_html = f"No footnote found for {footnote_id} (tried {db_footnote_id if is_nt_book else rbt_heb_ref})."
                        
                except Exception as e:
                    print(f"[FOOTNOTE JSON ERROR] {e}")
                    footnote_html = f"Error retrieving footnote: {e}"
        
        else:
            footnote_html = f"Invalid footnote format: {footnote_id}"
            title = "Error"
    
    except Exception as e:
        import traceback
        traceback.print_exc()
        footnote_html = f"Error retrieving footnote: {str(e)}"
        title = "Error"
    
    return JsonResponse({
        'footnote_id': footnote_id,
        'title': title,
        'content': footnote_html
    })



def get_cache_key(book, chapter_num, verse_num, language):
    sanitized_book = book.replace(':', '_').replace(' ', '')
    return f'{sanitized_book}_{chapter_num}_{verse_num}_{language}_{INTERLINEAR_CACHE_VERSION}'


def translate_chapter_api(request):
    """
    API endpoint to trigger translation for a chapter.
    This allows non-blocking translation handling on the frontend.
    """
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
        from .translation_utils import translate_chapter_batch, translate_footnotes_batch
        from .views import get_results, get_cache_key # Self-import
        
        # Force English source to get canonical text for translation
        # This bypasses any potentially partial/broken cached 'es', 'fr', etc. results
        results = get_results(book, chapter_num, None, 'en')
        
        # Import book lists for testament detection
        from translate.translator import new_testament_books, old_testament_books, book_abbreviations
        
        # Initialize translation_stats for all code paths
        translation_stats = {'verses': 0, 'footnotes': 0}
        
        if book in new_testament_books:
            chapter_rows = results['chapter_reader']
            print(f"[API DEBUG] Found {len(chapter_rows)} rows in chapter")
            
            # --- VERSE TEXT TRANSLATION ---
            
            # Check existing translations (completed OR processing to avoid duplicates)
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
                    # Send FULL verse content INCLUDING tooltips for translation
                    # The AI should translate tooltip content while preserving HTML structure
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
                # Get English display name for translation
                display_book_en = re.sub(r'(\d+)([a-zA-Z]+)', r'\1 \2', book)
                display_book_en = rbt_books.get(display_book_en, display_book_en)
                verses_to_translate[0] = display_book_en  # verse 0 = book name
                print(f"[API DEBUG] Book name needs translation: {display_book_en}")
            
            print(f"[API DEBUG] Verses to translate: {list(verses_to_translate.keys())}")
            
            if verses_to_translate:
                # Mark verses as 'processing' to prevent duplicate concurrent translations
                for verse_num in verses_to_translate.keys():
                    if verse_num == 0:  # Book name
                        VerseTranslation.objects.update_or_create(
                            book=book,
                            chapter=0,
                            verse=0,
                            language_code=language,
                            footnote_id=None,
                            defaults={'status': 'processing', 'verse_text': ''}
                        )
                    else:
                        VerseTranslation.objects.update_or_create(
                            book=book,
                            chapter=chapter_num,
                            verse=verse_num,
                            language_code=language,
                            footnote_id=None,
                            defaults={'status': 'processing', 'verse_text': ''}
                        )
                print(f"[API DEBUG] Marked {len(verses_to_translate)} verses as 'processing'")
                
                print(f"[API DEBUG] Calling translate_chapter_batch...")
                translated_results = translate_chapter_batch(verses_to_translate, language)
                print(f"[API DEBUG] Result keys: {list(translated_results.keys())}")
                
                if '__quota_exceeded__' in translated_results:
                    print(f"[API DEBUG] Quota exceeded")
                    return JsonResponse({'status': 'error', 'message': 'Translation quota exceeded'})
                
                # Check if ALL translations failed due to API key error
                all_failed = all('[Translation unavailable' in str(v) for v in translated_results.values())
                if all_failed and translated_results:
                    print(f"[API DEBUG] All translations failed - API key not configured")
                    return JsonResponse({'status': 'error', 'message': 'Translation service unavailable - API key not configured'})
                
                for verse_num, translated_text in translated_results.items():
                    # Skip saving if translation failed (contains error message)
                    if '[Translation unavailable' in translated_text or translated_text.startswith('[Translation unavailable'):
                        print(f"[API DEBUG] Skipping verse {verse_num} - translation failed")
                        continue
                    
                    # Handle book name translation (verse=0)
                    if verse_num == 0:
                        VerseTranslation.objects.update_or_create(
                            book=book,
                            chapter=0,
                            verse=0,
                            language_code=language,
                            footnote_id=None,
                            defaults={
                                'verse_text': translated_text,
                                'status': 'completed',
                                'generated_by': 'gemini-3-flash-preview'
                            }
                        )
                        print(f"[API DEBUG] Book name translated: {translated_text}")
                    else:
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
                    translation_stats['verses'] += 1

            print(f"[API DEBUG] Verse translation complete. Starting footnote extraction...")
            
            # --- FOOTNOTE TRANSLATION ---
            
            # Need to extract footnotes from HTML similar to main view
            footnotes_collection = {}
            
            # Helper to query footnote text (duplicated from main view - could be refactored)
            def query_footnote_text(book, sup_text):
                footnote_id = f"{book}-{sup_text}"
                if book[0].isdigit():
                    table_name = f"table_{book.lower()}_footnotes"
                else:
                    table_name = f"{book.lower()}_footnotes"
                
                # We need fresh connection/cursor usually, or use execute_query from db_utils
                from search.db_utils import execute_query
                execute_query("SET search_path TO new_testament;")
                result = execute_query(
                    f"SELECT footnote_html FROM new_testament.{table_name} WHERE footnote_id = %s",
                    (footnote_id,),
                    fetch='one'
                )
                return result[0] if result else None

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
                existing_footnote_ids = set()
                
                # Check DB for existing footnote translations (completed OR processing)
                # Since we iterate by collection keys (sup_text like '1-1-1'), we construct ID
                target_ids = [f"{book}-{k}" for k in footnotes_collection.keys()]
                
                found_objs = VerseTranslation.objects.filter(
                    language_code=language,
                    status__in=['completed', 'processing'],
                    footnote_id__in=target_ids
                ).values_list('footnote_id', flat=True)
                
                existing_footnote_ids = set(found_objs)
                print(f"[API DEBUG] Existing footnotes: {existing_footnote_ids}")
                
                footnotes_to_translate = {}
                for sup_text, data in footnotes_collection.items():
                    f_id = f"{book}-{sup_text}"
                    if f_id not in existing_footnote_ids:
                        footnotes_to_translate[f_id] = data['content']
                
                print(f"[API DEBUG] Footnotes to translate: {list(footnotes_to_translate.keys())}")

                if footnotes_to_translate:
                    # Mark footnotes as 'processing' to prevent duplicate concurrent translations
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
                            book=book,
                            chapter=c_obj,
                            verse=v_obj,
                            language_code=language,
                            footnote_id=f_id,
                            defaults={'status': 'processing', 'footnote_text': ''}
                        )
                    print(f"[API DEBUG] Marked {len(footnotes_to_translate)} footnotes as 'processing'")
                    
                    print(f"[API DEBUG] Starting footnote translation batch of {len(footnotes_to_translate)} items...")
                    translated_footnotes = translate_footnotes_batch(footnotes_to_translate, language)
                    print(f"[API DEBUG] Footnote translation returned, processing results...")
                    
                    if '__quota_exceeded__' in translated_footnotes:
                         return JsonResponse({'status': 'error', 'message': 'Translation quota exceeded'})
                    
                    # Check if ALL footnote translations failed due to API key error
                    all_failed = all('[Translation unavailable' in str(v) for v in translated_footnotes.values())
                    if all_failed and translated_footnotes:
                        print(f"[API DEBUG] All footnote translations failed - API key not configured")
                        return JsonResponse({'status': 'error', 'message': 'Translation service unavailable - API key not configured'})

                    for f_id, f_text in translated_footnotes.items():
                        # Skip saving if translation failed (contains error message)
                        if '[Translation unavailable' in f_text or f_text.startswith('[Translation unavailable'):
                            print(f"[API DEBUG] Skipping footnote {f_id} - translation failed")
                            continue
                        
                        # Helper to map back
                        found_sup = None
                        # Reverse lookup from ID
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
                            book=book,
                            chapter=c_obj,
                            verse=v_obj,
                            language_code=language,
                            footnote_id=f_id,
                            defaults={
                                'footnote_text': f_text,
                                'status': 'completed',
                                'generated_by': 'gemini-3-flash-preview'
                            }
                        )
                        translation_stats['footnotes'] += 1
        
        elif book == 'Genesis' or book in old_testament_books:
            # --- OT TRANSLATION HANDLING (including Genesis) ---
            # IMPORTANT: Only translate PARAPHRASE content, NOT Hebrew Literal
            print(f"[API DEBUG] Processing OT book: {book}")
            
            # Get book abbreviation for reference parsing
            book_abbrev = book_abbreviations.get(book, book)
            
            # --- PARAPHRASE TEXT TRANSLATION (not Hebrew Literal) ---
            existing_translations = VerseTranslation.objects.filter(
                book=book,
                chapter=chapter_num,
                language_code=language,
                status__in=['completed', 'processing'],
                footnote_id__isnull=True
            ).values_list('verse', flat=True)
            
            print(f"[API DEBUG] OT Existing translations: {list(existing_translations)}")
            
            verses_to_translate = {}
            
            # Genesis uses Django ORM queryset, other OT books use html dict
            if book == 'Genesis':
                # Genesis returns {'rbt': <queryset>, ...}
                rbt_queryset = results.get('rbt', [])
                print(f"[API DEBUG] Genesis has {len(rbt_queryset) if rbt_queryset else 0} verses in queryset")
                
                for verse_obj in rbt_queryset:
                    verse_num = verse_obj.verse
                    # Use rbt_reader (PARAPHRASE), NOT html (Hebrew Literal)
                    paraphrase_content = verse_obj.rbt_reader or ''
                    if verse_num not in existing_translations and paraphrase_content:
                        verses_to_translate[verse_num] = paraphrase_content
            else:
                # Other OT books use html dict with verse keys like '01', '02', etc
                # Format is {verse_key: (eng_literal, html_paraphrase)}
                # - eng_literal (index 0) = Eng field = Hebrew Literal pane = DO NOT translate
                # - html_paraphrase (index 1) = html field = Paraphrase pane = SHOULD translate
                html_dict = results.get('html', {})
                print(f"[API DEBUG] OT chapter has {len(html_dict)} verse groups")
                
                for verse_key, value in html_dict.items():
                    # Handle tuple format (eng_literal, html_paraphrase)
                    # We want the SECOND element (html/paraphrase), NOT the first (eng/literal)
                    if isinstance(value, tuple) and len(value) >= 2:
                        paraphrase_content = value[1] or ''  # Second element is paraphrase (html field)
                    else:
                        paraphrase_content = value if isinstance(value, str) else ''
                    verse_num = int(verse_key)
                    if verse_num not in existing_translations and paraphrase_content:
                        verses_to_translate[verse_num] = paraphrase_content
            
            # Check if book name needs translation
            book_name_exists = VerseTranslation.objects.filter(
                book=book,
                chapter=0,
                verse=0,
                language_code=language,
                status='completed',
                footnote_id__isnull=True
            ).exists()
            
            if not book_name_exists:
                # Get English display name for translation
                display_book_en = re.sub(r'(\d+)([a-zA-Z]+)', r'\1 \2', book)
                display_book_en = rbt_books.get(display_book_en, display_book_en)
                verses_to_translate[0] = display_book_en  # verse 0 = book name
                print(f"[API DEBUG] OT Book name needs translation: {display_book_en}")
            
            print(f"[API DEBUG] OT Verses to translate: {list(verses_to_translate.keys())}")
            
            if verses_to_translate:
                # Mark verses as 'processing'
                for verse_num in verses_to_translate.keys():
                    if verse_num == 0:  # Book name
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
                print(f"[API DEBUG] OT Marked {len(verses_to_translate)} verses as 'processing'")
                
                print(f"[API DEBUG] OT Calling translate_chapter_batch...")
                translated_results = translate_chapter_batch(verses_to_translate, language)
                print(f"[API DEBUG] OT Result keys: {list(translated_results.keys())}")
                
                if '__quota_exceeded__' in translated_results:
                    print(f"[API DEBUG] OT Quota exceeded")
                    return JsonResponse({'status': 'error', 'message': 'Translation quota exceeded'})
                
                # Check if ALL translations failed
                all_failed = all('[Translation unavailable' in str(v) for v in translated_results.values())
                if all_failed and translated_results:
                    print(f"[API DEBUG] OT All translations failed - API key not configured")
                    return JsonResponse({'status': 'error', 'message': 'Translation service unavailable - API key not configured'})
                
                # Save verse translations
                for verse_num, translated_text in translated_results.items():
                    if '[Translation unavailable' in translated_text:
                        print(f"[API DEBUG] OT Skipping verse {verse_num} - translation failed")
                        continue
                    
                    if verse_num == 0:  # Book name
                        VerseTranslation.objects.update_or_create(
                            book=book, chapter=0, verse=0,
                            language_code=language, footnote_id=None,
                            defaults={'verse_text': translated_text, 'status': 'completed', 'generated_by': 'gemini-3-flash-preview'}
                        )
                        translation_stats['verses'] += 1
                        print(f"[API DEBUG] OT Saved book name translation: {translated_text[:50]}")
                    else:
                        VerseTranslation.objects.update_or_create(
                            book=book, chapter=chapter_num, verse=verse_num,
                            language_code=language, footnote_id=None,
                            defaults={'verse_text': translated_text, 'status': 'completed', 'generated_by': 'gemini-3-flash-preview'}
                        )
                        translation_stats['verses'] += 1
            
            # --- OT FOOTNOTE TRANSLATION ---
            # OT footnotes are in hebrewdata table, referenced by Ref
            # Genesis footnotes use different format (chapter-verse-number pattern)
            footnotes_collection = {}
            
            if book == 'Genesis':
                # Genesis: extract footnotes from queryset verse HTML
                rbt_queryset = results.get('rbt', [])
                for verse_obj in rbt_queryset:
                    html_content = verse_obj.html or ''
                    verse_num = verse_obj.verse
                    if html_content:
                        # Genesis footnotes use pattern like "1-1-1", "1-1-2a" etc
                        footnote_refs = re.findall(r'\?footnote=(\d+-\d+-\d+[a-zA-Z]?)', html_content)
                        for fn_ref in footnote_refs:
                            # Get footnote content using get_footnote function
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
                # Other OT books: extract footnotes from html dict
                # Footnote links use pattern: ?footnote=Exo-20-1-06 (Book-Chapter-Verse-SubRef)
                html_dict = results.get('html', {})
                for verse_key, value in html_dict.items():
                    if isinstance(value, tuple) and len(value) >= 2:
                        html_content = value[1]
                    else:
                        html_content = value
                    if html_content:
                        # Extract footnote IDs from links (pattern: ?footnote=Exo-20-1-06)
                        # Ensure html_content is a string before regex
                        html_content_str = str(html_content) if html_content else ''
                        footnote_refs = re.findall(r'\?footnote=([^"&\s]+)', html_content_str)
                        for fn_ref in footnote_refs:
                            # Get footnote content using get_footnote function
                            fn_content = get_footnote(fn_ref, book)
                            if fn_content:
                                # Use full book name in ID for consistency
                                f_id = f"{book}-{fn_ref}"
                                if f_id not in footnotes_collection:
                                    footnotes_collection[f_id] = {
                                        'verse': int(verse_key) if verse_key.isdigit() else 0,
                                        'chapter': chapter_num,
                                        'content': fn_content,
                                        'id': f_id
                                    }
            
            if footnotes_collection:
                print(f"[API DEBUG] OT Found {len(footnotes_collection)} footnotes")
                
                existing_footnote_ids = set(VerseTranslation.objects.filter(
                    language_code=language,
                    status__in=['completed', 'processing'],
                    footnote_id__in=list(footnotes_collection.keys())
                ).values_list('footnote_id', flat=True))
                
                print(f"[API DEBUG] OT Existing footnotes: {existing_footnote_ids}")
                
                footnotes_to_translate = {}
                for f_id, data in footnotes_collection.items():
                    if f_id not in existing_footnote_ids:
                        footnotes_to_translate[f_id] = data['content']
                
                print(f"[API DEBUG] OT Footnotes to translate: {list(footnotes_to_translate.keys())}")
                
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
                    
                    print(f"[API DEBUG] OT Translating {len(footnotes_to_translate)} footnotes...")
                    translated_footnotes = translate_footnotes_batch(footnotes_to_translate, language)
                    
                    if '__quota_exceeded__' in translated_footnotes:
                        return JsonResponse({'status': 'error', 'message': 'Translation quota exceeded'})
                    
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
        
        else:
            # Book not in NT or OT lists - skip translation
            print(f"[API DEBUG] Book '{book}' not recognized for translation")
            return JsonResponse({'status': 'skipped', 'message': f'Book {book} not supported for translation'})
        
        print(f"[API DEBUG] All translations saved to database.")
        print(f"[API DEBUG] Translation complete. Verses: {translation_stats['verses']}, Footnotes: {translation_stats['footnotes']}")
        
        # CRITICAL: Clear cache for the target language so the main view 
        # picks up the newly saved translations immediately.
        try:
             # get_results uses verse_num=None by default
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
        # Validate that source content exists before creating a job
        results = get_results(book, chapter_num, None, 'en')
        if not results:
            return JsonResponse({'status': 'error', 'message': 'No source content found for this chapter'})
        
        # Determine if the chapter contains any source text depending on book type
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
            # Fallback check
            if results.get('rbt') or results.get('html') or results.get('chapter_reader'):
                has_source = True
        
        if not has_source:
            return JsonResponse({'status': 'error', 'message': 'No source content found for this chapter'})
        
        from .translation_worker import create_translation_job
        
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
        from .translation_worker import get_job_status
        
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
        
        # Special cache key for Joseph and Aseneth (storehouse)
        if book == "Joseph and Aseneth":
            cache_key = f'storehouse_{chapter_num}_{language}_{INTERLINEAR_CACHE_VERSION}'
            print(f"[CACHE DEBUG] Clearing storehouse cache: {cache_key}")
        else:
            cache_key = get_cache_key(book, chapter_num, None, language)
            print(f"[CACHE DEBUG] Clearing regular cache: {cache_key}")
        
        result = cache.delete(cache_key)
        print(f"[CACHE DEBUG] Cache delete result: {result}")
        
        return JsonResponse({
            'status': 'ok',
            'message': f'Cache cleared for {book} chapter {chapter_num} ({language})'
        })
        
    except Exception as e:
        print(f"[CACHE DEBUG] Cache clear error: {e}")
        return JsonResponse({'status': 'error', 'message': str(e)})

