from attrs import field
from django.http import HttpResponse
from django.shortcuts import render, redirect
from search.models import Genesis, GenesisFootnotes, EngLXX, LITV, TranslationUpdates
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
from .db_utils import get_db_connection, execute_query
import os

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
                bookref = ref[0]
                bookref = convert_book_name(bookref)
                bookref = bookref.capitalize()
                bookref = bookref.replace(' ', '_')

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
    
    for result in results:
        try:
            result.url = parse_and_construct_url(result)
        except:
            result.url = None
            
        result.date = result.date.date()

    context = {
        'month': month_param if month_param else date_param if date_param else datetime.now().strftime('%B %Y'),
        'updates': results,
        'update_count': results.count(),
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

        # Create an HTML table with two columns
        table_html = f'<tr><td style="border-bottom: 1px solid #d2d2d2;"><a href="?footnote={chapter}-{verse}-{footnote_ref}">{footnote_ref}</a></td><td style="border-bottom: 1px solid #d2d2d2;">{footnote_html}</td></tr>'

        return table_html
    
    
    elif book in nt_abbrev:

        if book[0].isdigit():
            table = f"table_{book}_footnotes"
        else:
            table = f"{book}_footnotes"
            
        table = table.lower()

        footnote_parts = footnote_id.split('-')
        footnote_number = footnote_parts[-1]

        footnote_ref = book + '-' + footnote_number

        # Construct the SQL query to retrieve HTML
        sql_query = f"SELECT footnote_html FROM new_testament.{table} WHERE footnote_id = %s"
        result = execute_query(sql_query, (footnote_ref,), fetch='one')

        if result:
            footnote_html = result[0]
            # Create an HTML table with two columns
            table_html = (
                f'<tr>'
                f'<td style="border-bottom: 1px solid #d2d2d2;">'
                f'<a href="?footnote={chapter_num}-{verse_num}-{footnote_number}&book={book}">{footnote_number}</a>'
                f'</td>'
                f'<td style="border-bottom: 1px solid #d2d2d2;">{footnote_html}</td>'
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
            # Create an HTML table with two columns
            table_html = (
                f'<tr>'
                f'<td style="border-bottom: 1px solid #d2d2d2;">{foot_ref}</td>'
                f'<td style="border-bottom: 1px solid #d2d2d2;">{footnote_html}</td>'
                f'</tr>'
            )
        else:
            table_html = ''

        return table_html


# RBT DATABASE (uses django database for Genesis.
def get_results(book, chapter_num, verse_num=None):
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

    # Sets/Retrieves cache only for verse, not whole chapter
    sanitized_book = book.replace(':', '_').replace(' ', '')
    cache_key_base = f'{sanitized_book}_{chapter_num}_{verse_num}'
    cached_data = cache.get(cache_key_base)

    
    if not cached_data:
        
        ## Get Genesis from django database ##
        if book == 'Genesis' and verse_num is None:
            
            rbt_book_model_map = {
                'Genesis': Genesis,
            }

            rbt_table = rbt_book_model_map.get(book)
            #rbt = rbt_table.objects.filter(chapter=chapter_num)  # run first filter
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
                rbt = rbt_table.objects.filter(chapter=chapter_num)  # filter chapter
                rbt = rbt.filter(verse=verse_num) # filter verse
                rbt_text = rbt.values_list('text', flat=True).first()
                rbt_html = rbt.values_list('html', flat=True).first()
                rbt_paraphrase = rbt.values_list('rbt_reader', flat=True).first()
                rbt_heb = rbt.values_list('hebrew', flat=True).first()
                record_id_tuple = rbt.values_list('id').first()
                record_id = record_id_tuple[0] if record_id_tuple else None

                rbt_html = rbt_html.replace('</p><p>', '')

                
                # Generate a list of footnote references found in the verse
                #footnote_references = re.findall(r'href="\?footnote=(\d+-\d+-\d+)"', rbt_html)
                footnote_references = re.findall(r'\?footnote=(\d+-\d+-\d+[a-zA-Z]?)', rbt_html)
                
                footnote_list = footnote_references

                # Create a list to store footnote contents using get_footnote function
                footnote_contents = []
                for footnote_id in footnote_list:
                    
                    footnote_content = get_footnote(footnote_id, book) # get_footnote function
                    footnote_contents.append(footnote_content)
            
            
                # Get the previous and next row verse references
                current_row_id = rbt.values_list('id', flat=True).first()

                prev_row_id = rbt_table.objects.filter(id__lt=current_row_id).aggregate(max_id=Max('id'))['max_id']
                prev_ref = rbt_table.objects.filter(id=prev_row_id)
                prev_chapter = prev_ref.values_list('chapter', flat=True).first()
                prev_verse = prev_ref.values_list('verse', flat=True).first()

                next_row_id = rbt_table.objects.filter(id__gt=current_row_id).aggregate(min_id=Min('id'))['min_id']
                next_ref = rbt_table.objects.filter(id=next_row_id)
                next_chapter = next_ref.values_list('chapter', flat=True).first()
                next_verse = next_ref.values_list('verse', flat=True).first()
            
                if prev_chapter is None:
                    prev_ref = f'?book={book}&chapter={chapter_num}&verse={verse_num}'
                else:
                    prev_ref = f'?book={book}&chapter={prev_chapter}&verse={prev_verse}'
                if next_chapter is None:
                    next_ref = f'?book={book}&chapter={chapter_num}&verse={verse_num}'
                else:
                    next_ref = f'?book={book}&chapter={next_chapter}&verse={next_verse}'
                
            # Old Testament books
            elif book in old_testament_books:
        
                # Convert references to 'Gen.1.1' format
                if book in book_abbreviations:
                    book_abbrev = book_abbreviations[book]
                    rbt_heb_ref = f'{book_abbrev}.{chapter_num}.{verse_num}'
                    rbt_heb_chapter = f'{book_abbrev}.{chapter_num}.'
                    rbt_heb_ref2 = f'{book_abbrev}.{chapter_num}.{verse_num}-'
                else:
                    rbt_heb_ref = f'{book}.{chapter_num}.{verse_num}'
                    rbt_heb_chapter = f'{book}.{chapter_num}.'
                    rbt_heb_ref2 = f'{book_abbrev}.{chapter_num}.{verse_num}-'

                # Retrieve a single OT row
                sql_query_ot = """
                    SELECT id, Ref, html, hebrew, footnote, literal
                    FROM old_testament.ot
                    WHERE Ref = %s;
                """

                row_data = execute_query(sql_query_ot, (rbt_heb_ref,), fetch='one')

                # Retrieve Hebrewdata rows matching a reference pattern
                sql_query_hebrew = """
                    SELECT id, Ref, Eng, Heb1, Heb2, Heb3, Heb4, Heb5, Heb6, Morph, uniq, Strongs, color, html, 
                        heb1_n, heb2_n, heb3_n, heb4_n, heb5_n, heb6_n, combined_heb, combined_heb_niqqud, footnote
                    FROM old_testament.hebrewdata
                    WHERE ref LIKE %s;
                """
                rows_data = execute_query(sql_query_hebrew, (f'{rbt_heb_ref2}%',), fetch='all')
  
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
                    
                strong_row, english_row, hebrew_row, morph_row, hebrew_clean = build_heb_interlinear(rows_data)
                
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

                # incomplete. need to finish get_footnote() for rest of OT books
                footnote_list = re.findall(r'\?footnote=([^&"]+)', rbt_paraphrase)

                # Create a list to store footnote contents using get_footnote function
                footnote_contents = []
                for footnote_id in footnote_list:
                    footnote_content = get_footnote(footnote_id, book) # get_footnote function
                    footnote_contents.append(footnote_content)

            elif book in new_testament_books:
                
                if book in book_abbreviations:
                    book_abbrev = book_abbreviations[book]

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
                chapters = execute_query(sql_query, (f'{book_abbrev}%',), fetch='all')

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
                    
                    if abbreviation in nt_abbrev:
                        prev_book = convert_book_name(abbreviation)

                    prev_ref = f'?book={prev_book}&chapter={prev_record[1]}&verse={prev_record[2]}'
                
                if next_record is not None:
                    
                    abbreviation = next_record[0]
                    
                    # Ensure the input is capitalized
                    if abbreviation[0].isdigit():
                        abbreviation = abbreviation[0] + abbreviation[1:].capitalize()
                    else:
                        abbreviation = abbreviation.capitalize()
                    
                    if abbreviation in nt_abbrev:
                        
                        next_book = convert_book_name(abbreviation)
                    
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
                    WHERE verse LIKE %s;
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
                        
                        interlinear += f'<a href="/greek-parsing/"><span class="morph" title="{morph_desc}" style="color: {color};">{morph}</span></a>\n'
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

# /RBT/ root home
def search(request):
    query = request.GET.get('q')  # keyword search form used
    ref_query = request.GET.get('ref')
    chapter_num = request.GET.get('chapter')
    book = request.GET.get('book')
    verse_num = request.GET.get('verse')
    footnote_id = request.GET.get('footnote')
    
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

        # if individual book is searched convert the full to the abbrev
        if book not in ['NT', 'OT', 'all']:
            book2 = convert_book_name(book)
            book = book2.lower()  
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

    
    # SINGLE VERSE return verse.html
    elif book and chapter_num and verse_num:

        try:
            
            results = get_results(book, chapter_num, verse_num)
            
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
                    'hebrew_clean': hebrew_clean
                    }
            page_title = f'{book} {chapter_num}:{verse_num}'
            return render(request, 'verse.html', {'page_title': page_title, **context})
            
        except Exception as e:   
            context = {'error': "Invalid verse" }
            return render(request, 'search_input.html', context)
        
    # SINGLE CHAPTER
    elif book and chapter_num:
        
        try:

            results = get_results(book, chapter_num)
            
            hebrew_literal = ""
            nt_literal = ""
            paraphrase = ""
            
            # Check if the Django Genesis object is returned
            if book == 'Genesis':
                
                rbt = results['rbt']
                cached_hit = results['cached_hit']
                chapter_list = results['chapter_list']

                for result in rbt:

                    if '</p><p>' in result.html:
                        # Split html into two parts using '</p><p>' as separator
                        # and add result.verse in between
                        parts = result.html.split('</p><p>')
                        hebrew_literal += f'{parts[0]}</p><p><span class="verse_ref" style="display: none;"><b><a href="?book={book}&chapter={result.chapter}&verse={result.verse}">{result.verse}</a> </b></span>{parts[1]}'
                    elif result.html.startswith('<p>'):
                        # If HTML starts with '<p>', replace it with the verse_ref link
                        hebrew_literal += f'<p><span class="verse_ref" style="display: none;"><b><a href="?book={book}&chapter={result.chapter}&verse={result.verse}">{result.verse}</a> </b></span>{result.html[3:]}'  # Remove the first '<p>'
                    else:
                        hebrew_literal += f'<span class="verse_ref" style="display: none;"><b><a href="?book={book}&chapter={result.chapter}&verse={result.verse}">{result.verse}</a> </b></span>{result.html}'

                    if result.rbt_reader.endswith('</span>'):
                        close_text = ''
                    else:
                        close_text = '<br>'


                    if '<h5>' in result.rbt_reader:
                        parts = result.rbt_reader.split('</h5>')

                        # Check if the list has at least two elements
                        if len(parts) >= 2:
                            heading = parts[0] + '</h5>'
                            paraphrase += f'{heading}<span class="verse_ref" style="display: none;"><b><a href="?book={book}&chapter={result.chapter}&verse={result.verse}">{result.verse}</a> </b></span>{parts[1]}{close_text}'
                        else:
                            paraphrase += f'{heading}<span class="verse_ref" style="display: none;"><b><a href="?book={book}&chapter={result.chapter}&verse={result.verse}">{result.verse}</a> </b></span>{result.rbt_reader}{close_text}'

                    elif result.rbt_reader == '':
                        paraphrase += ''
                    else:
                        paraphrase += f'<span class="verse_ref" style="display: none;"><b><a href="?book={book}&chapter={result.chapter}&verse={result.verse}">{result.verse}</a> </b></span>{result.rbt_reader}{close_text}'

                # Fetch commentary for a specific book and chapter
                # commentary_row = execute_query(
                #     "SELECT html FROM ai_commentary WHERE book = %s AND chapter = %s;",
                #     ('Gen', chapter_num),
                #     fetch='one'
                # )

                commentary = None
                
                # if commentary is not None:
                #     commentary = commentary[0]


                chapters = ""
                for number in chapter_list:
                    chapters += f'<a href="?book={book}&chapter={number}" style="text-decoration: none;">{number}</a> |'

                book = rbt_books.get(book, book)

                page_title = f'{book} {chapter_num}'
                context = {'chapters': chapters, 
                        'html': hebrew_literal, 
                        'paraphrase': paraphrase,
                        'commentary': commentary,
                        'book': book, 
                        'chapter_num': chapter_num, 
                        'chapter_list': chapter_list,
                        'cache_hit': cached_hit
                        }
                return render(request, 'chapter.html', {'page_title': page_title, **context})


            # parse the list for other books
            else:
                chapter_rows = results['chapter_reader']
                html_rows = results['html']
                chapter_list = results['chapter_list']
                cached_hit = results['cached_hit']
                commentary = results['commentary']
                
                if commentary is not None:
                    commentary = commentary[0]

                if book in new_testament_books:
                    
                    def query_footnote(book, sup_text):
                        footnote_id = f"{book}-{sup_text}"

                        # Determine table name
                        if book[0].isdigit():
                            table_name = f"table_{book.lower()}_footnotes"
                        else:
                            table_name = f"{book.lower()}_footnotes"

                        # Set schema for NT footnotes
                        execute_query("SET search_path TO new_testament;")

                        # Query the footnote
                        result = execute_query(
                            f"SELECT footnote_html FROM {table_name} WHERE footnote_id = %s",
                            (footnote_id,),
                            fetch='one'
                        )

                        # Return footnote text or None
                        return result[0] if result else None

                    for row in chapter_rows:
                        bk, chapter_num, vrs, html_verse = row
                        if html_verse:

                            close_text = '' if html_verse.endswith('</span>') else '<br>'

                            # sup_texts = re.findall(r'<sup>(.*?)</sup>', html_verse)
                            # for sup_text in sup_texts:
                            #     # Query the database for each book and number
                            #     data = query_footnote(bk, sup_text)
                                
                            #     # Replace the reference with a link with hover content
                            #     html_verse = html_verse.replace(f'<sup>{sup_text}</sup>', f'<div class="footnote_content"><sup>{sup_text}</sup><div class="footnote_hover">{data}</div></div>')


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
                                

                    chapters = ''
                    for number in chapter_list:
                        chapters += f'<a href="?book={book}&chapter={number}" style="text-decoration: none;">{number}</a> |'

                    # add space
                    book =  re.sub(r'(\d+)([a-zA-Z]+)', r'\1 \2', book)
                    book = rbt_books.get(book, book)
                    page_title = f'{book} {chapter_num}'
                    context = {'cache_hit': cached_hit, 'chapters': chapters, 'html': nt_literal, 'paraphrase': paraphrase, 'book': book, 'chapter_num': chapter_num, 'chapter_list': chapter_list}
                    
                    return render(request, 'nt_chapter.html', {'page_title': page_title, **context})

                # Rest of Hebrew books
                else:
                    # First, collect and sort chapter_rows by verse number
                    verse_data = []
                    for row in chapter_rows:
                        vrs = row[0].split('.')[2].split('-')[0]
                        html_verse = row[1]
                        # Convert verse number to integer for proper sorting
                        verse_num = int(vrs) if vrs.isdigit() else float('inf')
                        verse_data.append((verse_num, vrs, html_verse))
                    
                    # Sort by numeric verse number
                    verse_data.sort(key=lambda x: x[0])
                    
                    # Process sorted verses
                    for verse_num, vrs, html_verse in verse_data:
                        if html_verse:
                            close_text = '' if html_verse.endswith('</span>') else '<br>'
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

                    # Compile the Hebrew Literal
                    # Sort html_rows keys numerically instead of as strings
                    sorted_keys = sorted(html_rows.keys(), key=lambda x: int(x) if x.isdigit() else float('inf'))

                    for key in sorted_keys:
                        english_literal = html_rows[key][0]
                        words_str = english_literal if english_literal is not None else ''

                        display_key = key.lstrip('0') or '0'  # Handle case where key is all zeros
                        hebrew_literal += (
                            f'<span class="verse_ref" style="display: none;">'
                            f'<b><a href="?book={book}&chapter={chapter_num}&verse={display_key}">{display_key}</a> </b></span>'
                            f'{words_str}<br>'
                        )
                    chapters = ''
                    for number in chapter_list:
                        chapters += f'<a href="?book={book}&chapter={number}" style="text-decoration: none;">{number}</a> |'

                    # add space
                    book = re.sub(r'(\d+)([a-zA-Z]+)', r'\1 \2', book)
                    book = rbt_books.get(book, book)
                    page_title = f'{book} {chapter_num}'
                    
                    context = {
                        'chapters': chapters, 
                        'html': hebrew_literal, 
                        'paraphrase': paraphrase, 
                        'commentary': commentary, 
                        'book': book, 
                        'chapter_num': chapter_num, 
                        'chapter_list': chapter_list
                    }
                    
                    return render(request, 'chapter.html', {'page_title': page_title, **context})

        except Exception as e:   

            context = {'error': e }
            return render(request, 'search_input.html', context)
    
    # SINGLE FOOTNOTE
    elif footnote_id:
        
        if book:
            chapter_ref, verse_ref, footnote_ref = footnote_id.split('-')
            
            # Split the footnote_id by '-' and get the last slice
            footnote_parts = footnote_id.split('-')
            footnote_ref = footnote_parts[-1]
            chapter = footnote_parts[0]
            verse = footnote_parts[1]
            footnote_id = f'{book}-{footnote_ref}'

            if book in book_abbreviations:
                book_abbrev = book_abbreviations[book]
                
            else:
                book_abbrev = book.lower()
                abbrev_to_book = {abbrev: book for book, abbrev in book_abbreviations.items()}
                full_book_name = abbrev_to_book.get(book)

            if book[0].isdigit():
                table = f"table_{book_abbrev}_footnotes"
            else:
                table = f"{book_abbrev}_footnotes"

            # Fetch footnote_html from the dynamically determined table
            data = execute_query(
                f"SELECT footnote_html FROM new_testament.{table} WHERE footnote_id = %s",
                (footnote_id,),
                fetch='all'
            )

            try:
                footnote_html = data[0][0]
            except IndexError:
                footnote_html = "Footnote not found."

            # Create an HTML table with two columns
            table_html = f'<tr><td style="border-bottom: 1px solid #d2d2d2;"><a href="?footnote={chapter}-{verse}-{footnote_ref}&book={book}">{footnote_ref}</a></td><td style="border-bottom: 1px solid #d2d2d2;">{footnote_html}</td></tr>'

            footnote_html = f'<table><tbody>{table_html}</tbody></table>'
            
            page_title = f'{full_book_name} {chapter}:{verse}'
            context = {'footnote_html': footnote_html,
            'footnote': footnote_id,
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
        bookref = convert_book_name(bookref)
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
        base_url = "https://rbt.realbible.tech/"
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

        # Set schema for New Testament
        execute_query("SET search_path TO new_testament;")

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
                f"SELECT COUNT(*) FROM {table_name} WHERE footnote_id IS NOT NULL",
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
    

