from django.http import HttpResponse, JsonResponse, StreamingHttpResponse
from django.shortcuts import render, redirect
from django.contrib import messages
from search.models import Genesis, GenesisFootnotes, EngLXX, LITV, TranslationUpdates
from django.db.models import Q
from django.utils.html import escape
from django.contrib.auth.decorators import login_required
from django.core.cache import cache
import subprocess
from django.middleware.csrf import get_token
import re
from search.views import get_results
from translate.translator import *
import pythonbible as bible
from datetime import datetime
from bs4 import BeautifulSoup, NavigableString
import os
import csv
import json
import time
from google import genai
#import google.generativeai as genai
from .db_utils import get_db_connection, execute_query
import psycopg2
import requests

GEMINI_API_KEY = os.getenv('GEMINI_API_KEY')
client = genai.Client(api_key=GEMINI_API_KEY)


old_testament_books = [
        'Exodus', 'Leviticus', 'Numbers', 'Deuteronomy', 'Joshua', 'Judges', 'Ruth',
        '1Samuel', '2Samuel', '1Kings', '2Kings', '1Chronicles', '2Chronicles', 'Ezra', 'Nehemiah',
        'Esther', 'Job', 'Psalms', 'Proverbs', 'Ecclesiastes', 'Songs', 'Song of Solomon', 'Isaiah', 'Jeremiah',
        'Lamentations', 'Ezekiel', 'Daniel', 'Hosea', 'Joel', 'Amos', 'Obadiah', 'Jonah', 'Micah', 'Nahum',
        'Habakkuk', 'Zephaniah', 'Haggai', 'Zechariah', 'Malachi'
]
new_testament_books = [
'Matthew', 'Mark', 'Luke', 'John', 'Acts', 'Romans', '1Corinthians', '2Corinthians', '1 Corinthians', '2 Corinthians', 'Galatians',
'Ephesians', 'Philippians', 'Colossians', '1 Thessalonians', '2 Thessalonians', '1Thessalonians', '2Thessalonians', '1Timothy', '2Timothy', '1 Timothy', '2 Timothy',
'Titus', 'Philemon', 'Hebrews', 'James', '1 Peter', '2 Peter', '1Peter', '2Peter', '1John', '2John', '3John', '1 John', '2 John', '3 John', 'Jude', 'Revelation'
]
nt_abbrev = [
    'Mat', 'Mar', 'Luk', 'Joh', 'Act', 'Rom', '1Co', '2Co',
    'Gal', 'Eph', 'Php', 'Col', '1Th', '2Th', '1Ti', '2Ti',
    'Tit', 'Phm', 'Heb', 'Jam', '1Pe', '2Pe',
    '1Jo', '2Jo', '3Jo', 'Jud', 'Rev'
]

def get_context(book, chapter_num, verse_num):

        try:
            results = get_results(book, chapter_num, verse_num)
        except:
            results = get_results(book, chapter_num, '1')
            verse_num = '1'

        new_linear_english = None
        record_id = results['record_id']
        verse_id = results['verse_id']
        hebrew = results['hebrew']
        rbt_greek = results['rbt_greek']
        rbt = results['rbt']
        rbt_paraphrase = results['rbt_paraphrase']
        slt = results['slt']
        litv = results['litv']
        eng_lxx = results['eng_lxx']
        previous_verse = results['prev_ref']
        next_verse = results['next_ref']
        footnote_contents = results['footnote_content'] # footnote html rows
        chapter_list = results['chapter_list']
        interlinear = results['interlinear']
        linear_english = results['linear_english']
        entries = results['entries']
        replacements = results['replacements']
        previous_footnote = results['previous_footnote']
        next_footnote = results['next_footnote']
        cached_hit = results['cached_hit']

        footnotes_content = ''
        if footnote_contents is not None:
            footnotes_content = ' '.join(footnote_contents)
            footnotes_content = footnotes_content.replace('?footnote=', '../edit_footnote/?footnote=')
            footnotes_content = f'<table><tbody>{footnotes_content}</tbody></table>'

        if rbt is not None:
            rbt_display = rbt.replace('?footnote=', '../edit_footnote/?footnote=')
        else:
            rbt_display = 'No verse found.'
        edit_result = ''

        chapters = ""
        if chapter_list is not None:
            for number in chapter_list:
                chapters += f'<a href="?book={book}&chapter={number}" style="text-decoration: none;">{number}</a> |'

        # add space
        if book in book_abbreviations:
                book_abbrev = book_abbreviations[book]
        book2 = book
        book =  re.sub(r'(\d+)([a-zA-Z]+)', r'\1 \2', book)

        # swap 'then' to first word
        if linear_english:
            words = linear_english.split()
            # Check if "then" is the second word
            if len(words) >= 2 and words[1] == "then":
                # Replace "then" with the first word
                new_words = ["And"] + [words[0]] + words[2:]  
                new_linear_english = ' '.join(new_words)
            else:
                new_linear_english = linear_english

        context = {
            'replacements': replacements,
            'interlinear': interlinear,
            'linear_english': new_linear_english,
            'entries': entries,
            'book_abbrev': book_abbrev,
            'verse_id': verse_id,
            'book2': book2,
            'chapters': chapters,
            'record_id': record_id,
            'previous_verse': previous_verse,
            'next_verse': next_verse,
            'footnotes': footnotes_content,
            'previous_footnote': previous_footnote,
            'next_footnote': next_footnote,
            'book': book,
            'chapter_num': chapter_num,
            'verse_num': verse_num,
            'edit_result': edit_result,
            'slt': slt,
            'rbt_display': rbt_display,
            'rbt': rbt,
            'rbt_paraphrase': rbt_paraphrase,
            'eng_lxx': eng_lxx,
            'litv': litv,
            'hebrew': hebrew,
            'rbt_greek': rbt_greek,
            'cached_hit': cached_hit
        }

        return context

def generate_html_table(csv_data):
    if not csv_data:
        return '<p>No data available.</p>'
    
    def get_verse_info(verseID):
        
        row = execute_query(
            "SELECT book, chapter, startVerse FROM new_testament.nt WHERE verseID = %s",
            (verseID,),
            fetch='one'
        )
        
        if row:
            return row  # Returns tuple (book, chapter, startVerse)
        else:
            return None
        
        # # Fixed header row
        # headers = ['ID', 'Time', 'Verse ID', 'Old Text', 'New Text', 'Find Text', 'Replace Text']
        
        # table_html = '<table border="1">'
        # # Add header row
        # table_html += '<tr>'
        # for header in headers:
        #     table_html += f'<th>{header}</th>'
        # table_html += '</tr>'
        # # Add data rows
        # for row in csv_data:
        #     table_html += '<tr>'
        #     for i, cell in enumerate(row):
        #         # Highlight find_text in old_text and replace_text in new_text
        #         if i in [3, 4, 5, 6]:  # Indices for old_text, new_text, find_text, and replace_text
        #             find_replace = row[5], row[6]  # Extract find_text and replace_text
        #             cell = cell.replace(find_replace[0], f'<span class="highlight">{find_replace[0]}</span>')
        #             cell = cell.replace(find_replace[1], f'<span class="highlight">{find_replace[1]}</span>')
        #         if i == 2:
        #             # Fetch book, chapter, and startVerse based on verseID
        #             verse_info = get_verse_info(cell)
        #             if verse_info:
        #                 book, chapter, startVerse = verse_info
        #                 book = convert_book_name(book)

        #                 link = f'<a href="../edit/?book={book}&chapter={chapter}&verse={startVerse}">{cell}</a>'
        #                 cell = link

        #         table_html += f'<td>{cell}</td>'

        #     table_html += '</tr>'
        # table_html += '</table>'
        # return table_html

def gemini_translate(entries):
    """
    Translate Greek entries into a properly formatted English sentence using Gemini API.
    
    Args:
        entries (list): List of dictionaries containing Greek word data
        
    Returns:
        str: HTML formatted sentence or error message
    """
    try:
        # Validate input
        if not isinstance(entries, list) or not entries:
            return "Error: Invalid entries data"
        
        # Extract data from entries
        greek_words = []
        english_words = []
        morphology_data = []
        
        for entry in entries:
            # Validate each entry has required fields
            required_fields = ['lemma', 'english', 'morph_description']
            if not all(field in entry for field in required_fields):
                return f"Error: Missing required fields in entry: {entry}"
            
            greek_words.append(entry['lemma'])
            english_words.append(entry['english'])
            morphology_data.append(f"{entry['morph_description']} ({entry.get('morph', 'Unknown')})")
        
        # Create structured data strings
        greek_text = ' '.join(greek_words)
        interlinear_english = ' '.join(english_words)
        morphology_info = ' | '.join(morphology_data)
        
        # Construct improved prompt
        prompt = f"""
        You are formatting the sentence from these english words and morphology. Using the provided data, create the English sentence following these rules:

        FORMATTING RULES:
        1. Link definite articles to their respective nouns
        2. For imperfect indicative verbs, use "kept" instead of "were" if appropriate for the verb sense
        3. Capitalize words that have definite articles (but not "the" itself)
        4. Properly place conjunctions such as δὲ "and". If it is the second word, use "And" at the beginning of the sentence.
        5. Add "of" for genitive constructions, or "while/as" if genitive absolute
        6. Choose the most ideal word if multiple English options are given (separated by slashes)
        7. Wrap blue color (<span style="color: blue;">) on masculine words, pink color (<span style="color: #ff00aa;">) on feminine words
        8. Include any definite articles in the coloring.
        9. Always render participles with who/which/that (e.g., "the one who", "the ones who", "that which", "he who", "she who") 
        10. Render personal/possessive pronouns with -self or -selves (e.g., "himself", "themselves")
        11. If there are articular infinitives or substantive clause, capitalize and substantivize (e.g., "the Journeying of Himself", "the Fearing of the Water")
        12. Render any intensive pronouns with verbs as "You, yourselves are" or "I, myself am"
        13. Return ONLY the HTML sentence with proper span tags for colors


        GREEK TEXT: {greek_text}
        ENGLISH WORDS: {interlinear_english}
        MORPHOLOGY: {morphology_info}

        Example 1: he asked close beside <span style="color: blue;">himself</span> for epistles into <span style="color: #ff00aa;">Fertile Land</span> 
        ("<span style="color: #ff00aa;">Damascus</span>") toward <span style="color: #ff00aa;">the Congregations</span> in such a manner that if he found <span style="color: blue;">anyone</span> who are being of <span style="color: #ff00aa;">the Road</span>, both men and women, he might lead those who have been bound into <span style="color: #ff00aa;">Foundation of Peace</span>. 
        And <span style="color: blue;">a certain man</span>, he who is presently existing as <span style="color: blue;">a limping one</span> from out of <span style="color: #ff00aa;">a belly</span> of <span style="color: #ff00aa;">a mother</span> of <span style="color: blue;">himself</span>, kept being carried, him whom they were placing according to <span style="color: #ff00aa;">a day</span> toward <span style="color: #ff00aa;">the Doorway</span> of the Sacred Place, <span style="color: #ff00aa;">the one who is being called</span> '<span style="color: #ff00aa;">Seasonable</span>,' of the Begging for Mercy close beside the ones who were leading into the Sacred Place. 
        
        Example 2: And he is bringing to light, "<span style="color: blue;">Little Horn</span>, <span style="color: #ff00aa;">the Prayer</span> of <span style="color: blue;">yourself</span> has been heard and <span style="color: #ff00aa;">the Charities</span> of <span style="color: blue;">yourself</span> have been remembered in the eye of <span style="color: blue;">the God</span>.
        Return only the formatted HTML sentence.
        """
        
        # Make API call (assuming client is globally available)
        print("Requesting Gemini API...")  # Debugging line
        response = client.models.generate_content(
            model='gemini-2.5-flash', contents=prompt
        )
        print("Received response from Gemini API.")  # Debugging line

        if not response or not hasattr(response, 'text'):
            return "Error: Invalid response from Gemini API"
        
        content = response.text.strip()
        
        # Basic validation of returned content
        if not content:
            return "Error: Empty response from Gemini API"
        
        # Clean up common formatting issues
        content = content.replace('```html', '').replace('```', '').strip()
        
        return content

    except AttributeError as e:
        return f"Error: API client not properly configured: {e}"
    except Exception as e:
        return f"Error: Gemini API failed: {e}"

# /edit_footnote/
@login_required
def edit_footnote(request):
    if request.method == 'GET':
        footnote_id = request.GET.get('footnote')
        book = request.GET.get('book')

        parts = footnote_id.split('-')
        chapter_num = parts[0]
        verse_num = parts[1]
        footnoteid = parts[2]

        if book in nt_abbrev:
            footnote_id = book + '-' + footnoteid
            footnote_table = book + '_footnotes'

            if footnote_table in ['1Co_footnotes', '1Jo_footnotes', '1Pe_footnotes', '1Th_footnotes', '1Ti_footnotes', '2Co_footnotes', '2Jo_footnotes', '2Pe_footnotes', '2Th_footnotes', '2Ti_footnotes', '3Jo_footnotes']:
                footnote_table = 'table_' + footnote_table
            
            footnote_table = footnote_table.lower()
            
            with get_db_connection() as conn:
                cursor = conn.cursor()
                
                sql_query = f"SELECT footnote_html FROM new_testament.{footnote_table} WHERE footnote_id = %s"
                cursor.execute(sql_query, (footnote_id,))
                results = cursor.fetchone()
                footnote_html = results[0] if results else ""

                sql_query = f"SELECT verseText, rbt, verseID FROM new_testament.nt WHERE book = %s AND chapter = %s AND startVerse = %s"
                cursor.execute(sql_query, (book, chapter_num, verse_num))
                result = cursor.fetchone()

            if result:
                verse_greek = result[0]
                verse_html = result[1]
                verse_id = result[2]
            else: 
                verse_greek = ''
                verse_html = ''

            bookref = convert_book_name(book)
            bookref = bookref.capitalize()

            context = {
                'book': bookref, 
                'verse_greek': verse_greek, 
                'verse_html': verse_html, 
                'footnote_ref': footnote_id, 
                'footnote_html': footnote_html, 
                'footnote_edit': footnote_html,
                'results': results, 
                'footnote_id': footnote_id, 
                'chapter_ref': chapter_num, 
                'verse_ref': verse_num
            }

        else:
            book = 'Genesis'
            chapter_ref, verse_ref, footnote_ref = footnote_id.split('-')
            results = GenesisFootnotes.objects.filter(footnote_id=footnote_id)

            footnote_edit = results[0].footnote_html
            footnote_html = results[0].footnote_html
            
            # Get results
            verse_results = Genesis.objects.filter(
                chapter=chapter_ref, verse=verse_ref).values('html')
            hebrew_result = Genesis.objects.filter(
                chapter=chapter_ref, verse=verse_ref).values('hebrew')

            hebrew = hebrew_result[0]['hebrew']
            verse_html = verse_results[0]['html']
            footnote_ref = footnote_id.split('-')[2]

            context = {
                'book': book, 
                'hebrew': hebrew, 
                'verse_html': verse_html, 
                'footnote_ref': footnote_ref, 
                'footnote_html': footnote_html, 
                'footnote_edit': footnote_edit,
                'results': results, 
                'footnote_id': footnote_id, 
                'chapter_ref': chapter_ref, 
                'verse_ref': verse_ref
            }

    # Update footnote with new text if posted
    elif request.method == 'POST':
        footnote_id = request.POST.get('footnote_id')
        footnote_html = request.POST.get('footnote_edit')

        book = request.POST.get('book')
        chapter_num = request.POST.get('chapter_num')
        verse_num = request.POST.get('verse_num')

        # New testament footnotes
        if footnote_id.count('-') == 1:
            book, ref_num = footnote_id.split('-')

            if book[0].isdigit():
                table = f"table_{book}_footnotes"
            else:
                table = f"{book}_footnotes"
   
            with get_db_connection() as conn:
                cursor = conn.cursor()  

                sql_query = f"UPDATE new_testament.{table} SET footnote_html = %s WHERE footnote_id = %s"
                cursor.execute(sql_query, (footnote_html, footnote_id))
                conn.commit()

            bookref = convert_book_name(book)
            bookref = bookref.capitalize()
            
            update_text = f"Updated footnote for Footnote <b>{book}-{ref_num}</b>:<br> {footnote_html}."
            update_date = datetime.now()
            update_instance = TranslationUpdates(
                date=update_date, 
                version="New Testament Footnote", 
                reference=f"{bookref} {chapter_num}:{verse_num} - {footnote_id}", 
                update_text=update_text
            )
            update_instance.save()

            if book in nt_abbrev:
                
                if book[0].isdigit():
                    table = f"table_{book}_footnotes"
                else:
                    table = f"{book}_footnotes"

                with get_db_connection() as conn:
                    cursor = conn.cursor()
                    sql_query = f"SELECT footnote_html FROM new_testament.{table} WHERE footnote_id = %s"
                    cursor.execute(sql_query, (footnote_id,))
                    results = cursor.fetchone()
                    
                    footnote_html = results[0] if results else ""

                    sql_query = f"SELECT verseText, rbt, verseID FROM new_testament.nt WHERE book = %s AND chapter = %s AND startVerse = %s"
                    cursor.execute(sql_query, (book, chapter_num, verse_num))
                    result = cursor.fetchone()

                if result:
                    verse_greek = result[0]
                    verse_html = result[1]
                    verse_id = result[2]
                else: 
                    verse_greek = ''
                    verse_html = ''

            context = {
                'book': bookref, 
                'verse_greek': verse_greek, 
                'verse_html': verse_html, 
                'footnote_ref': footnote_id, 
                'footnote_html': footnote_html, 
                'footnote_edit': footnote_html,
                'results': results, 
                'footnote_id': footnote_id, 
                'chapter_ref': chapter_num, 
                'verse_ref': verse_num
            }

        # Genesis footnotes
        else:
            chapter_ref, verse_ref, footnote_ref = footnote_id.split('-')

            results = GenesisFootnotes.objects.filter(footnote_id=footnote_id)
            results.update(footnote_html=footnote_html)
        
            update_text = f"Updated footnote for Chapter {chapter_ref}, Verse {verse_ref}, Footnote {footnote_ref}"
            update_date = datetime.now()
            update_version = "Hebrew Footnote"
            update_instance = TranslationUpdates(
                date=update_date, 
                version=update_version, 
                reference=f"Genesis {chapter_ref}:{verse_ref} - {footnote_ref}", 
                update_text=update_text
            )
            update_instance.save()
            book = 'Genesis'

            context = {
                'book': book, 
                'chapter': chapter_ref, 
                'verse': verse_ref, 
                'footnote_ref': footnote_id, 
                'footnote_html': footnote_html, 
                'footnote_edit': footnote_html
            }

    return render(request, 'edit_footnote.html', context)


# /edit/
# for editing the RBT translation in the model
@login_required
def edit(request):


    query = request.GET.get('q')
    book = request.GET.get('book')
    chapter_num = request.GET.get('chapter')
    verse_num = request.GET.get('verse')
    

    if request.method == 'POST':
        
        edited_content = request.POST.get('edited_content')
        edited_paraphrase = request.POST.get('edited_paraphrase')
        footnote_html = request.POST.get('add_footnote')
        footnote_id = request.POST.get('footnote_id')
        footnote_header = request.POST.get('footnote_header')
        verse_id = request.POST.get('verse_id') #for new testament books
        record_id = request.POST.get('record_id') 
        book = request.POST.get('book')
        chapter_num = request.POST.get('chapter')
        verse_num = request.POST.get('verse')
        verse_input = request.POST.get('verse_input')
        nt_book = request.POST.get('nt_book')
        replacements = request.POST.get('replacements')

        if replacements:
            
            with open('interlinear_english.json', 'w', encoding='utf-8') as file:
                json.dump(replacements, file, indent=4, ensure_ascii=False)
            
            context = get_context(book, chapter_num, verse_num)
            context['edit_result'] = '<div class="notice-bar"><p><span class="icon"><i class="fas fa-check-circle"></i></span>Updated replacements successfully!</p></div>'

            return render(request, 'edit_nt_verse.html', context)

        # add new footnote for NT
        if nt_book is not None:
            if nt_book in book_abbreviations:
                book_abbrev = book_abbreviations[book]

            try:
                with get_db_connection() as conn:
                    cursor = conn.cursor()
                    cursor.execute("SET search_path TO new_testament")
                    
                    # 1Jo_footnotes
                    book = book_abbrev + '_footnotes'

                    if book in ['1Co_footnotes', '1Jo_footnotes', '1Pe_footnotes', '1Th_footnotes', '1Ti_footnotes', '2Co_footnotes', '2Jo_footnotes', '2Pe_footnotes', '2Th_footnotes', '2Ti_footnotes', '3Jo_footnotes']:
                        book = 'table_' + book
                    
                    book = book.lower()

                    footnote_id = book_abbrev + '-' + footnote_id
                    footnote_html = f'<p><span class="footnote_header">{footnote_header}</span></p> <p>{footnote_html}</p>'
                    sql_query = f"INSERT INTO {book} (footnote_id, footnote_html) VALUES (%s, %s)"
                    cursor.execute(sql_query, (footnote_id, footnote_html))
                    conn.commit()

                    update_text = re.sub(r'<a\s+.*?>(.*?)</a>', r'\1', footnote_html)
                    update_version = "New Testament Footnote"
                    update_date = datetime.now()
                    update_instance = TranslationUpdates(date=update_date, version=update_version, reference=f"{book} {chapter_num}:{verse_num} - {footnote_id}", update_text=update_text)
                    update_instance.save()
                    
                    cache_key_base_verse = f'{book}_{chapter_num}_{verse_num}'

                    cache_key_base_chapter = f'{book}_{chapter_num}_None'
                    cache.delete(cache_key_base_verse)
                    cache.delete(cache_key_base_chapter)

                    cache_string = "Deleted Cache key: " + cache_key_base_verse + ', ' + cache_key_base_chapter

                    context = get_context(nt_book, chapter_num, verse_num)
                    context['edit_result'] = f'<div class="notice-bar"><p><span class="icon"><i class="fas fa-check-circle"></i></span>Added footnote successfully! {cache_string}</p></div>'

                    return render(request, 'edit_nt_verse.html', context)
            
            except psycopg2.IntegrityError as e:
                # Handle the unique constraint violation
                error_message = f"Error: Unique constraint violation occurred - {e}"
                # Note: conn.rollback() is automatically handled by the context manager
                
                # Get a list of existing footnote_ids
                existing_ids = []
                with get_db_connection() as conn:
                    cursor = conn.cursor()
                    cursor.execute("SET search_path TO new_testament")
                    cursor.execute(f"SELECT footnote_id FROM {book}")
                    existing_ids = [row[0] for row in cursor.fetchall()]
                
                context = {
                    'error_message': error_message,
                    'existing_ids': existing_ids,
                }
                
                return render(request, 'insert_footnote_error.html', context)

        elif record_id is not None:
            record = Genesis.objects.get(id=record_id)
            if edited_content is not None:
                record.html = edited_content.strip()
                version = 'Hebrew Literal'
                update_text = edited_content
            if edited_paraphrase is not None:
                record.rbt_reader = edited_paraphrase.strip()
                version = 'Hebrew Translation'
                update_text = edited_paraphrase
            record.save()
            
            update_text = re.sub(r'<a\s+.*?>(.*?)</a>', r'\1', update_text)
            update_version = version
            update_date = datetime.now()
            update_instance = TranslationUpdates(date=update_date, version=update_version, reference=f"{book} {record.chapter}:{record.verse}", update_text=update_text)
            update_instance.save()

            cache_key_base_verse = f'{book}_{chapter_num}_{verse_num}'
            cache_key_base_chapter = f'{book}_{chapter_num}_None'
            cache.delete(cache_key_base_verse)
            cache.delete(cache_key_base_chapter)

            cache_string = "Deleted Cache key: " + cache_key_base_verse + ', ' + cache_key_base_chapter

            context = get_context(book, chapter_num, verse_num)
            context['edit_result'] = f'<div class="notice-bar"><p><span class="icon"><i class="fas fa-check-circle"></i></span>Updated verse successfully! {cache_string}</p></div>'

            return render(request, 'edit_verse.html', context)
        
        # Add Genesis footnote only
        elif footnote_html is not None:
            # Add the new footnote
            record, created = GenesisFootnotes.objects.update_or_create(
                footnote_id=footnote_id,
                defaults={'footnote_id': footnote_id, 'footnote_html': footnote_html}
            )

            update_text = f"Added new footnote for {book} {chapter_num}:{verse_num}"
            update_date = datetime.now()
            update_version = "Hebrew Footnote"
            update_instance = TranslationUpdates(date=update_date, version=update_version, reference=f"{book} {chapter_num}:{verse_num} - {footnote_id}", update_text=update_text)
            update_instance.save()

            cache_key_base_verse = f'{book}_{chapter_num}_{verse_num}'
            cache_key_base_chapter = f'{book}_{chapter_num}_None'
            cache.delete(cache_key_base_verse)
            cache.delete(cache_key_base_chapter)

            cache_string = "Deleted Cache key: " + cache_key_base_verse + ', ' + cache_key_base_chapter
            

            context = get_context(book, chapter_num, verse_num)
            context['edit_result'] = f'<div class="notice-bar"><p><span class="icon"><i class="fas fa-check-circle"></i></span>Added new footnote successfully! {cache_string}</p></div>'
            return render(request, 'edit_verse.html', context)
        
        elif verse_id is not None:

            # Update the rbt column
            execute_query(
                "UPDATE new_testament.nt SET rbt = %s WHERE verseID = %s",
                (edited_content, verse_id)
            )
            
            update_text = re.sub(r'<a\s+.*?>(.*?)</a>', r'\1', edited_content)
            update_version = "New Testament"
            update_date = datetime.now()
            update_instance = TranslationUpdates(date=update_date, version=update_version, reference=f"{book} {chapter_num}:{verse_num}", update_text=update_text)
            update_instance.save()

            book = book.replace(' ', '')
            cache_key_base_verse = f'{book}_{chapter_num}_{verse_num}'
            cache_key_base_chapter = f'{book}_{chapter_num}_None'
            
            cache.delete(cache_key_base_verse)
            cache.delete(cache_key_base_chapter)

            cache_string = "Deleted Cache key: " + cache_key_base_verse + ' ' + cache_key_base_chapter

            context = get_context(book, chapter_num, verse_num)
            context['edit_result'] = f'<div class="notice-bar"><p><span class="icon"><i class="fas fa-check-circle"></i></span>Updated verse successfully! {cache_string}</p></div>'

            return render(request, 'edit_nt_verse.html', context)

        elif verse_input:
            
            context = get_context(book, chapter_num, verse_input)
            if book in new_testament_books:
                return render(request, 'edit_nt_verse.html', context)
            else:
                return render(request, 'edit_verse.html', context)
    
    elif query:

        results = Genesis.objects.filter(html__icontains=query)

        # Strip only paragraph tags from results
        for result in results:
            result.html = result.html.replace('<p>', '').replace(
                '</p>', '')  # strip the paragraph tags
            # Replace all hashtag links with query parameters
            result.html = re.sub(
                r'#(sdfootnote(\d+)sym)', rf'?footnote={result.chapter}-{result.verse}-\g<2>', result.html)
            # apply bold to search query
            result.html = re.sub(
                f'({re.escape(query)})',
                r'<strong>\1</strong>',
                result.html,
                flags=re.IGNORECASE
            )

        context = {'results': results, 'query': query}
        return render(request, 'search_results.html', context)

    
    elif book and chapter_num and verse_num:
        
        context = get_context(book, chapter_num, verse_num)

        if book in new_testament_books:
            entries = context["entries"]
            sentence_suggestion = gemini_translate(entries)
            context["sentence_suggestion"] = sentence_suggestion
            return render(request, 'edit_nt_verse.html', context)
        else:
            return render(request, 'edit_verse.html', context)
    

    # displays whole chapter
    elif chapter_num:
        results = get_results(book, chapter_num)
        html = ""
    
        rbt = results['rbt']
        chapter_list = results['chapter_list']
        results_html = results['html']
        cached_hit = results['cached_hit']

        if results['rbt']:
            for result in rbt:
                # Replace all '?footnote=xxx' references with '/edit_footnote/?footnote=xxx'
                modified_html = result.html.replace('?footnote=', '../edit_footnote/?footnote=')

                if '</p><p>' in modified_html:
                    parts = modified_html.split('</p><p>')
                    html += f'{parts[0]}</p><p>¶¶<span class="verse_ref"><b><a href="?book={book}&chapter={result.chapter}&verse={result.verse}">{result.verse}</a> </b></span>{parts[1]}'
                
                elif modified_html.startswith('<p>'):
                    html += f'<p>¶<span class="verse_ref"><b><a href="?book={book}&chapter={result.chapter}&verse={result.verse}">{result.verse}</a> </b></span>{modified_html[3:]}'
                
                else:
                    html += f'<span class="verse_ref">¶<b><a href="?book={book}&chapter={result.chapter}&verse={result.verse}">{result.verse}</a> </b></span>{modified_html}'

        else:
            # Hebrew books other than Genesis
            if isinstance(results_html, dict):
                
                for key, value in results_html.items():
                
                    # Extract verse number
                    verse_num = str(int(key))

                    # Join elements of the tuple with a space
                    combined_elements = ' '.join(str(element) if element is not None else '' for element in value)

                    # Format the HTML string
                    #modified_html = data.replace('?footnote=', '../edit_footnote/?footnote=')
                    html += f'<span class="verse_ref">¶<b><a href="../translate/?book={book}&chapter={chapter_num}&verse={verse_num}">{verse_num}</a> </b></span>{combined_elements}<br>'

            
            else:

                for result in results_html:

                    if result[3]:
                        htmldata = result[3]
                        verse_num = result[2]

                        modified_html = htmldata.replace('?footnote=', '../edit_footnote/?footnote=')

                        close_text = '' if htmldata.endswith('</span>') else '<br>'

                    
                        html += f'<span class="verse_ref">¶<b><a href="?book={book}&chapter={chapter_num}&verse={verse_num}">{verse_num}</a> </b></span>{modified_html}{close_text}'
            
        chapters = ''
        for number in chapter_list:
            chapters += f'<a href="?book={book}&chapter={number}" style="text-decoration: none;">{number}</a> |'
        # add space
        book =  re.sub(r'(\d+)([a-zA-Z]+)', r'\1 \2', book)

        context = {'html': html, 'book': book, 'chapter_num': chapter_num, 'chapters': chapters, 'cached_hit': cached_hit}
        return render(request, 'edit_chapter.html', context)

    
    else:
        return render(request, 'edit_input.html')


# /translate/
# for editing the hebrew in hebrewdata table
@login_required
def translate(request):

    # Function to return count of lexemes found
    def lexeme_search(num, lex):
        where_clause = f"{num} = %s"
        query = f"SELECT COUNT(*) FROM old_testament.hebrewdata WHERE {where_clause};"
        search_count = execute_query(query, (lex,), fetch='one')[0]
        return search_count

    # Functions to save edited content to database
    updates = []

    def save_unique_to_database(id, column, data):
        query = f"UPDATE old_testament.hebrewdata SET {column} = %s WHERE id = %s;"
        execute_query(query, (data, id))
        updates.append(f'Updated {column} for id {id} with "{data}".')

    def save_unique_edit_to_database(use_niqqud, heb, column, data, uniq_id):
        if data:
            query = f"UPDATE old_testament.hebrewdata SET Eng = %s WHERE id = %s;"
            updated_count = execute_query(query, (data, uniq_id))
            updates.append(f'Updated column {column} with unique "{data}".')

    def save_edit_to_database(use_niqqud, heb, column, data):
        if not data:
            return

        if use_niqqud == 'true':
            niq = 'with'
            query = f"UPDATE old_testament.hebrewdata SET {column} = %s WHERE combined_heb_niqqud = %s AND uniq = '0';"
            execute_query(query, (data, heb))
            excluded_rows_count = execute_query(
                "SELECT COUNT(*) FROM old_testament.hebrewdata WHERE uniq = '1' AND combined_heb_niqqud = %s;", (heb,), fetch='one'
            )[0]
        else:
            niq = 'without'
            query = f"UPDATE old_testament.hebrewdata SET {column} = %s WHERE combined_heb = %s AND uniq = '0';"
            execute_query(query, (data, heb))
            excluded_rows_count = execute_query(
                "SELECT COUNT(*) FROM old_testament.hebrewdata WHERE uniq = '1' AND combined_heb = %s;", (heb,), fetch='one'
            )[0]

        update_count = execute_query("SELECT COUNT(*) FROM old_testament.hebrewdata WHERE " +
                                    ("combined_heb_niqqud" if use_niqqud=='true' else "combined_heb") +
                                    " = %s AND uniq = '0';", (heb,), fetch='one')[0]
        updates.append(f'Updated column {column} with "{data}" for {update_count} rows where {heb} {niq} niqqud matches. Excluded {excluded_rows_count} rows.')

    def save_english_literal(english_literal, verse_id):
        verse_ref = verse_id.split('-')[0]
        execute_query("UPDATE old_testament.ot SET literal = %s WHERE Ref = %s;", (english_literal, verse_ref))
        updates.append(f'Updated ID: {verse_ref} in Literal with "{english_literal}"')

    def save_html_to_database(verse_id, html):
        verse_ref = verse_id.split('-')[0]
        execute_query("UPDATE old_testament.hebrewdata SET html = %s WHERE Ref = %s;", (html, verse_id))
        execute_query("UPDATE old_testament.ot SET html = %s WHERE Ref = %s;", (html, verse_ref))

        cache_key_base_chapter, cache_key_base_verse = get_cache_reference(verse_id)
        cache.delete(cache_key_base_verse)
        cache.delete(cache_key_base_chapter)
        updates.append(f'Updated HTML Paraphrase: {verse_id} in HTML with "{html}".')
        updates.append(f"Deleted Cache key: {cache_key_base_verse}, {cache_key_base_chapter}")

    def save_footnote_to_database(verse_id, id, key, text):
        execute_query("UPDATE old_testament.hebrewdata SET footnote = %s WHERE id = %s;", (text, id))

        verse_id = verse_id.split('-')[0]
        
        update_text = re.sub(r'<a\s+.*?>(.*?)</a>', r'\1', text)
        update_version = "Hebrew Footnote"
        update_date = datetime.now()
        update_instance = TranslationUpdates(date=update_date, version=update_version, reference=f"{verse_id} - {key}", update_text=update_text)
        update_instance.save()

        cache_key_base_chapter, cache_key_base_verse = get_cache_reference(verse_id)
        cache.delete(cache_key_base_verse)
        cache.delete(cache_key_base_chapter)
        #print("Deleted Cache key(s): ", cache_key_base_verse, cache_key_base_chapter)
        cache_string = "Deleted Cache key: " + cache_key_base_verse + ', ' + cache_key_base_chapter
        

        update = f'Updated ID: {verse_id} in footnote with "{text}".\n{cache_string}'
        
        updates.append(update)


    def save_color_to_database(color_id, color_data):
        try:

            # Get combined_heb for this color_id
            combined_heb_row = execute_query(
                "SELECT combined_heb FROM old_testament.hebrewdata WHERE id = %s;",
                (color_id,),
                fetch='one'
            )
            if not combined_heb_row:
                return
            combined_heb = combined_heb_row[0]

            # Update color column
            updated_count = execute_query(
                "UPDATE old_testament.hebrewdata SET color = %s WHERE combined_heb = %s AND uniq = '0';",
                (color_data, combined_heb)
            )

            if color_data:
                updates.append(f'Updated {combined_heb} in color with "{color_data}" for {updated_count} rows.')

        except Exception as e:
            print("Postgres error:", e)


    log_file = 'replacements.log'

    def find_replace(find_text, replace_text):
        try:

            # Perform replacement
            updated_count = execute_query(
                """
                UPDATE old_testament.hebrewdata
                SET html = REPLACE(html, %s, %s)
                WHERE html LIKE %s;
                """,
                (find_text, replace_text, f"%{find_text}%")
            )

            # Log updates
            updates.append(f'Replaced {updated_count} occurrences of "{find_text}" with "{replace_text}".')
            log_entry = f'Replaced {updated_count} occurrences of "{find_text}" with "{replace_text}".\n'
            with open(log_file, 'a', encoding='utf-8') as log:
                log.write(log_entry)

            return updated_count

        except Exception as e:
            print("Postgres error:", e)
            return 0


    def undo_replacements():
        with open(log_file, 'r') as log:
            log_entries = log.readlines()

        # Undo only the last entry
        if log_entries:
            last_entry = log_entries[-1]
            matches = re.findall(r'"([^"]+)"', last_entry)
            if len(matches) == 2:
                find_text = matches[0]
                replace_text = matches[1]
                updated_count = find_replace(replace_text, find_text)

                if updated_count > 0:
                    updates.append(f'Undid {updated_count} occurrences of "{replace_text}" with "{find_text}".')

        # Remove the last entry from the log file
        with open(log_file, 'w') as log:
            log.writelines(log_entries[:-1])


    ####### POST OLD TESTAMENT HEBREW EDIT

    if request.method == 'POST':
        # Get the list of 'id' and 'eng_data' from the form data
        #eng_id_list = request.POST.getlist('eng_id')
        eng_data_list = request.POST.getlist('eng_data')
        original_eng_data_list = request.POST.getlist('original_eng')
        unique_data_list = request.POST.getlist('unique')
        unique_id_list = request.POST.getlist('unique_id')
        color_id_list = request.POST.getlist('color_id')
        color_data_list = request.POST.getlist('color')
        color_old_list = request.POST.getlist('color_old')
        combined_heb_list = request.POST.getlist('combined_heb')
        combined_heb_niqqud_list = request.POST.getlist('combined_heb_niqqud')
        
        use_niqqud = request.POST.get('use_niqqud')
        html = request.POST.get('html')
        verse_id = request.POST.get('verse_id')
        undo = request.POST.get('undo')
        find_text = request.POST.get('find_text')
        replace_text = request.POST.get('replace_text')
        original_english_reader = request.POST.get('original_english_reader')

        eng_data_list = ['' if item == 'None' else item for item in eng_data_list]
        original_eng_data_list = ['' if item == 'None' else item for item in original_eng_data_list]

        unique_data_list = ['0' if item == 'false' else '1' for item in unique_data_list]
        unique_id_unique_data_pairs = zip(unique_id_list, unique_data_list)

        combined_eng_pairs = zip(original_eng_data_list, eng_data_list)
        combined_heb_eng_data_pairs = zip(combined_heb_list, eng_data_list, unique_data_list, unique_id_list)
        combined_heb_niqqud_eng_data_pairs = zip(combined_heb_niqqud_list, eng_data_list, unique_data_list, unique_id_list)

        color_data_list = ['f' if item == 'f' else 'm' if item == 'm' else '0' for item in color_data_list]
        combined_old_new_color_pairs = zip(color_old_list, color_data_list)
        color_id_color_data_pairs = zip(color_id_list, color_data_list)
        
        # for id, unique_data in unique_id_unique_data_pairs:
        #     save_unique_to_database(id, 'uniq', unique_data)

        color_change = []
        for old_color, new_color in combined_old_new_color_pairs:
            if old_color != new_color:
                color_change.append((new_color))

        if color_change:
            for id, color_data in color_id_color_data_pairs:
                if color_data in color_change:
                    save_color_to_database(id, color_data)

        eng_change = []
        for old, new in combined_eng_pairs:

            if old != new:
                eng_change.append((new))
        #print(eng_change)
        if eng_change:
            
            english_literal = ''

            if use_niqqud == 'true':
                
                for heb, eng_data, uniq, uniq_id in combined_heb_niqqud_eng_data_pairs:
                    english_literal += eng_data + ' '

                    if uniq == "1":
                        
                        save_unique_edit_to_database(use_niqqud, heb, 'Eng', eng_data, uniq_id)
                        verse_id = verse_id.split('-')
                        verse_id = verse_id[0]
                        reference = bible.get_references(verse_id)
                        if reference:
                            ref = reference[0]
                            book = ref.book.name
                            book = book.title()
                            chapter_num = ref.start_chapter
                            verse_num = ref.start_verse
                            reference = f'{book} {chapter_num}:{verse_num}'
                        update_text = f"Updated RBT translation for Hebrew {heb} as a uniquely defined word using '{eng_data}' in {reference}"
                        update_version = 'Hebrew Literal'
                        update_date = datetime.now()
                        update_instance = TranslationUpdates(date=update_date, version=update_version, reference=reference, update_text=update_text)
                        update_instance.save()

                    elif eng_data in eng_change:
                        save_edit_to_database(use_niqqud, heb, 'Eng', eng_data)
                        verse_id = verse_id.split('-')
                        verse_id = verse_id[0]
                        reference = bible.get_references(verse_id)
                        if reference:
                            ref = reference[0]
                            book = ref.book.name
                            book = book.title()
                            chapter_num = ref.start_chapter
                            verse_num = ref.start_verse
                            reference = f'{book} {chapter_num}:{verse_num}'
                        update_text = f"Updated RBT translation for Hebrew {heb} with {eng_data} in {reference}"
                        update_version = 'Hebrew Literal'
                        update_date = datetime.now()
                        update_instance = TranslationUpdates(date=update_date, version=update_version, reference=reference, update_text=update_text)
                        update_instance.save()
                
                save_english_literal(english_literal, verse_id)
            
            else:
                
                for heb, eng_data, uniq, uniq_id in combined_heb_eng_data_pairs:
                    
                    english_literal += eng_data + ' '

                    # if uniq == "1":
                    #     if eng_data in eng_change:
                            
                    #         save_unique_edit_to_database(use_niqqud, heb, 'Eng', eng_data, uniq_id)

                    if eng_data in eng_change:
                        save_edit_to_database(use_niqqud, heb, 'Eng', eng_data)
                        verse_id = verse_id.split('-')
                        verse_id = verse_id[0]
                        reference = bible.get_references(verse_id)
                        if reference:
                            ref = reference[0]
                            book = ref.book.name
                            book = book.title()
                            chapter_num = ref.start_chapter
                            verse_num = ref.start_verse
                            reference = f'{book} {chapter_num}:{verse_num}'
                        update_text = f"Updated RBT translation for Hebrew {heb} with {eng_data} in {reference}"
                        update_date = datetime.now()
                        update_version = 'Hebrew Literal'
                        update_instance = TranslationUpdates(date=update_date, version=update_version, reference=reference, update_text=update_text)
                        update_instance.save()
                
                save_english_literal(english_literal, verse_id)
       
        if html is not None and html != original_english_reader:

            save_html_to_database(verse_id, html)
            verse_id = verse_id.split('-')
            verse_id = verse_id[0]
            reference = bible.get_references(verse_id)
            if reference:
                ref = reference[0]
                book = ref.book.name
                book = book.title()
                chapter_num = ref.start_chapter
                verse_num = ref.start_verse
                reference = f'{book} {chapter_num}:{verse_num}'


            update_text = f"Updated RBT Paraphrase for {reference}: {html}"
            update_date = datetime.now()
            update_version = 'Paraphrase'
            update_instance = TranslationUpdates(date=update_date, version=update_version, reference=reference, update_text=update_text)
            update_instance.save()

        if replace_text:
            find_replace(find_text, replace_text)
        if undo == 'true':
            undo_replacements()

        # Handle footnotes
        footnotes_data = {}
        old_footnotes_data = {}
        updated_footnotes = {}
        for key, value in request.POST.items():
            if key.startswith('footnote-'):
                footnote_number = key.split('-')[1]
                footnotes_data[footnote_number] = value
        for key, value in request.POST.items():
            if key.startswith('old_footnote-'):
                footnote_number = key.split('-')[1]
                old_footnotes_data[footnote_number] = value
        
        for key in old_footnotes_data:
            # Check if the values don't match between old and new footnotes - only works for empty footnotes
            if old_footnotes_data[key] != footnotes_data.get(key):
                updated_footnotes[key] = footnotes_data.get(key)

        
        for key, text in updated_footnotes.items():
            num = int(key) - 1
            id = color_id_list[num]

            save_footnote_to_database(verse_id, id, key, text)

    ############### END POST EDIT

    query = request.GET.get('q')
    book = request.GET.get('book')
    chapter_num = request.GET.get('chapter')
    verse_num = request.GET.get('verse')
    page_title = f'{book} {chapter_num}:{verse_num}'
    slt_flag = False
    rbt = None
    if book == "Genesis":
        results = get_results(book, chapter_num, verse_num)

        record_id = results.get('record_id')
        hebrew = results.get('hebrew')
        rbt = results.get('rbt')
        litv = results.get('litv')
        footnote_contents = results.get('footnote_content', [])  # footnote html rows

        # Convert references to 'Gen.1.1-' format
        book_abbrev = book_abbreviations.get(book, book)
        rbt_heb_ref = f'{book_abbrev}.{chapter_num}.{verse_num}-'
        rbt_heb_chapter = f'{book_abbrev}.{chapter_num}.'
    else:
        book_abbrev = book_abbreviations.get(book, book)
        rbt_heb_ref = f'{book_abbrev}.{chapter_num}.{verse_num}-'
        rbt_heb_chapter = f'{book_abbrev}.{chapter_num}.'
        

    invalid_verse = ''
    if book is None:
        if query:
            reference = bible.get_references(query)

            if reference:
                ref = reference[0]
                book = ref.book.name
                book = book.title()
                chapter_num = ref.start_chapter
                verse_num = ref.start_verse
                book_abbrev = book_abbreviations[book]
                rbt_heb_ref = f'{book_abbrev}.{chapter_num}.{verse_num}-'
                rbt_heb_chapter = f'{book_abbrev}.{chapter_num}.'
                invalid_verse = ''
                slt_flag = True
               
            else:
                rbt_heb_ref = 'Gen.1.1-'
                rbt_heb_chapter = 'Gen.1.'
                book = 'Genesis'
                chapter_num = '1'
                verse_num = '1'
                invalid_verse = '<font style="color: red;">Invalid Verse!</font>'

        else:

            rbt_heb_ref = 'Gen.1.1-'
            rbt_heb_chapter = 'Gen.1.'
            book = 'Genesis'
            chapter_num = '1'
            verse_num = '1'
            invalid_verse = ''
    
    ## Get only Chapter html if no verse
    if verse_num is None:
        
        # Fetch rows
        html_rows = execute_query(
            "SELECT Ref, html FROM old_testament.hebrewdata WHERE Ref LIKE %s;",
            (f'{rbt_heb_chapter}%',),
            fetch='all'
        )

        chapter_reader = ""
        
        for row in html_rows:
            
            html_verse = row[1]
            if html_verse is not None:
                
                vrs = row[0].split('.')[2].split('-')[0]

                vrs = f'<a href="../translate/?book={book}&chapter={chapter_num}&verse={vrs}">{vrs}</a>'
                
                close_text = '' if html_verse.endswith('</span>') else '<br>'

                if '<p>' in html_verse:
                    html_string = html_verse.replace('<p>', '').replace('</p>', '')
                    html_string = f'<p><span class="verse_ref"><b>{vrs}</b></span> {html_string}</p>'
                    
                else:
                    html_string = f'<span class="verse_ref"><b>{vrs}</b></span>{html_verse}{close_text}'
                    
                chapter_reader += html_string


        #results = get_results(book, chapter_num)
        rbt_ref = rbt_heb_chapter[:4]
        chapter_references = execute_query(
            "SELECT Ref FROM old_testament.hebrewdata WHERE Ref LIKE %s;",
            (f'{rbt_ref}%',),
            fetch='all'
        )
        

        unique_chapters = set(int(reference[0].split('.')[1]) for reference in chapter_references)
        chapter_list = sorted(map(str, unique_chapters), key=lambda x: int(x))

        chapter_list = results['chapter_list']

        chapters = ''
        for number in chapter_list:
            chapters += f'<a href="?book={book}&chapter={number}" style="text-decoration: none;">{number}</a> |'

        page_title = f'{book} {chapter_num}'
        context = {
            'book': book,
            'chapter_reader': chapter_reader,
            'chapter_num': chapter_num,
            'chapters': chapters,
            }
        
        return render(request, 'edit_chapter.html', {'page_title': page_title, **context})



    # Get Hebrew verse from hebrewdata table
    else:
        #print(f'book: {book}, chapter: {chapter_num}, verse: {verse_num}')
        
        ##### Fetch Smith Literal Translation Verse ##############
        slt_book = book

        if not slt_flag:
            slt_reference = bible.get_references(f'{book} {chapter_num}:{verse_num}')
            if slt_reference:
                slt_ref = slt_reference[0]
                slt_book = slt_ref.book.name
                slt_book = slt_book.title()
                #print(f'sltbook: {slt_book}, chapter: {chapter_num}, verse: {verse_num}')
        
        try:

            sql_query = "SELECT content FROM smith_translation.verses WHERE book = %s AND chapter = %s AND verse = %s;"
            result = execute_query(sql_query, (slt_book, chapter_num, verse_num), fetch='one')

            smith = result[0] if result else "None"

        except Exception as e:
            smith = "None"

        ##########################################################
        # Fetch full rows data
        rows_data = execute_query(
            """
            SELECT id, Ref, Eng, Heb1, Heb2, Heb3, Heb4, Heb5, Heb6, Morph, uniq, Strongs, color, html, 
                heb1_n, heb2_n, heb3_n, heb4_n, heb5_n, heb6_n, combined_heb, combined_heb_niqqud, footnote
            FROM old_testament.hebrewdata
            WHERE Ref LIKE %s;
            """,
            (f'{rbt_heb_ref}%',),
            fetch='all'
        )

        # Fetch html rows
        html_rows = execute_query(
            "SELECT Ref, html FROM old_testament.hebrewdata WHERE Ref LIKE %s;",
            (f'{rbt_heb_chapter}%',),
            fetch='all'
        )

        if rows_data:
            id = rows_data[0][0]
            ref = rows_data[0][1]
            ref = ref[:-2]

            # Pass a function that uses db_utils for previous/next reference calculation
            prev_ref, next_ref = ot_prev_next_references(ref)

            verse_id = rbt_heb_ref + '01'

            html_row = execute_query(
                "SELECT html FROM old_testament.hebrewdata WHERE Ref = %s;",
                (verse_id,),
                fetch='one'
            )
            html = html_row[0] if html_row else ""


    
        ########## Hebrew Reader at TOP
        
        chapter_reader = ""

        for row in html_rows:
            
            html_verse = row[1]
            if html_verse is not None:
                vrs = row[0].split('.')[2].split('-')[0]
                
                close_text = '' if html_verse.endswith('</span>') else '<br>'

                if '<p>' in html_verse:
                    html_string = html_verse.replace('<p>', '').replace('</p>', '')
                    html_string = f'<p><span class="verse_ref"><b>{vrs}</b></span> {html_string}</p>'
                    
                else:
                    html_string = f'<span class="verse_ref"><b>{vrs}</b></span> {html_verse}'
                    
                chapter_reader += html_string + close_text

        # Build the Hebrew row
        strong_rows, english_rows, hebrew_rows, morph_rows, hebrew_clean = build_heb_interlinear(rows_data)
    
        # Reverse the order 
        strong_rows.reverse()
        english_rows.reverse()
        hebrew_rows.reverse()
        #morph_rows.reverse()

        strong_row = '<tr class="strongs">' + ''.join(strong_rows) + '</tr>'
        english_row = '<tr class="eng_reader">' + ''.join(english_rows) + '</tr>'
        hebrew_row = '<tr class="hebrew_reader">' + ''.join(hebrew_rows) + '</tr>'
        #morph_row = '<tr class="morph_reader" style="word-wrap: break-word;">' + ''.join(morph_rows) + '</tr>'
        hebrew_clean = '<font style="font-size: 26px;">' + ''.join(hebrew_clean) + '</font>'

        # strip niqqud from hebrew
        niqqud_pattern = '[\u0591-\u05BD\u05BF\u05C1-\u05C5\u05C7]'
        dash_pattern = '־'
        hebrew_row = re.sub(niqqud_pattern + '|' + dash_pattern, '', hebrew_row)

        ######### EDIT TABLE / ENGLISH READER
        edit_table_data = []
        english_verse = []
        footnote_num = 1

        for row_data in rows_data:
            id, ref, eng, heb1, heb2, heb3, heb4, heb5, heb6, morph, unique, strongs, color, html_list, heb1_n, heb2_n, heb3_n, heb4_n, heb5_n, heb6_n, combined_heb, combined_heb_niqqud, footnote = row_data

            english_verse.append(eng)


            # Combined pieces search and count
            # search_conditions_query1 = []
            # parameters_query1 = []
            
            # niqqud_translation = str.maketrans('', '', 'ְֱֲֳִֵֶַָֹֻּ')

            # for i, heb in enumerate([heb1, heb2, heb3, heb4, heb5, heb6], start=1):
            #     if heb:
            #         search_conditions_query1.append(f"Heb{i} = ?")
            #         parameters_query1.append(f'{heb}')
            #     else:
            #         search_conditions_query1.append(f"Heb{i} IS NULL")

            # Join the search conditions using 'AND' and build the final query
            #where_clause_query1 = " AND ".join(search_conditions_query1)
            # query1 = f"""
            #     SELECT COUNT(*) FROM hebrewdata
            #     WHERE {where_clause_query1};
            # """

            # parameters_query2 = f'{combined_heb}'
            # query2 = f"""
            #     SELECT COUNT(*) FROM hebrewdata
            #     WHERE combined_heb = ?;
            # """

            #cursor.execute(query1, parameters_query1)
            #search_count = cursor.fetchone()[0]
            search_count = f'<a href="../search/word/?word={ref}">#</a>'

            #cursor.execute(query2, (parameters_query2,))
            #search_count2 = cursor.fetchone()[0]
            search_count2 = f'<a href="../search/word/?word={ref}&niqqud=no">#</a>'

            # Search and count each individual lexeme
            #individual_counts = []
            
            # for i, heb in enumerate([heb1_n, heb2_n, heb3_n, heb4_n, heb5_n, heb6_n], start=1):
                
            #     if heb != '':
            #         # count = lexeme_search(f"heb{i}_n", heb)

            #         # if heb is not None:
            #         #     conjugations = find_verb_morph(heb)
                        
            #         #     if conjugations:
            #         #         conjugations_html = "Suggestions:<br>"
            #         #         for conjugation in conjugations:
            #         #             conjugation_details = "<div class='conjugation'>"
                                
            #         #             for key, value in conjugation.items():
            #         #                 conjugation_details += f"<strong>{key}:</strong> {value}<br>"
                                
            #         #             conjugation_details += "--------------</div>"
            #         #             conjugations_html += conjugation_details
           
            #         #         count = f"{count} <span class='heb'>{heb}</span> <div class='popup-container'>*<div class='popup-content'>{conjugations_html}</div></div>"
            #         #     else:
            #         #         count = f"{count} <span class='heb'>{heb}</span>"
            #         # if count == 0: count = ''
            #         #individual_counts.append(count if count is not None else '')
            #         individual_counts.append('')
            #     else:   
            #         individual_counts.append('')

            # Fetch 'Morph' data for the current row
            # morph_query = f"""
            #     SELECT Morph FROM hebrewdata
            #     WHERE id = ?;
            # """
            # cursor.execute(morph_query, (id,))
            # morph = cursor.fetchone()[0]
    

            parts = strongs.split('/')
            strong_refs = []
            strongs_exhaustive_list = []

            for part in parts:
                subparts = re.split(r'[=«]', part)
                for subpart in subparts:
                    if subpart.startswith('H'):
                        strong_ref = subpart
                        strong_refs.append(strong_ref)
                        strongs_exhaustive = strong_data(strong_ref)
                        strongs_exhaustive_list.append(strongs_exhaustive)

            # Format nicely for template
            if strong_refs:
                # Option A: Simple list
                formatted_refs = " • ".join(strongs_exhaustive_list)
                
                # Option B: With reference numbers
                ref_pairs = [f"H{ref}" for ref in strongs_exhaustive_list]
                formatted_refs = " | ".join(ref_pairs)
                
                # Option C: Clean format
                formatted_strongs_list = f"{strongs} → [{', '.join(strongs_exhaustive_list)}]"

            morph_color = ""
            # Determine the color based on the presence of 'f' or 'm'
            if 'f' in morph:
                morph_color = 'style="color: #FF1493;"'
            elif 'm' in morph:
                morph_color = 'style="color: blue;"'

            morph = f'<input type="hidden" id="code" value="{morph}"/><div {morph_color}>{morph}</div><div class="morph-popup" id="morph"></div>'
                
            combined_hebrew = f"{heb1 or ''} {heb2 or ''} {heb3 or ''} {heb4 or ''} {heb5 or ''} {heb6 or ''}"

            # Set true or false for unique hebrew words
            # if unique == 1:
            #     unique = f'<select name="unique" autocomplete="off"><option value="true" selected>Unique</option><option value="false">Not Unique</option></select><input type="hidden" name="unique_id" value="{id}">'
            # else:
            #     unique = f'<select name="unique" autocomplete="off"><option value="true">Unique</option><option value="false" selected>Not Unique</option></select><input type="hidden" name="unique_id" value="{id}">'
            unique = f'<input type="hidden" name="unique" value="false"><input type="hidden" name="unique_id" value="{id}">'

            # Set word color
            if color == 'm':
                color_old = 'm'
                color = f'''<td style="background-color: blue;"><select name="color" autocomplete="off">
                    <option name="color" value="m" selected>masc</option>
                    <option name="color" value="f">fem</option>
                    <option name="color" value="0">none</option>
                    </select>
                    <input type="hidden" name="color_old" value="{color_old}">
                    <input type="hidden" name="color_id" value="{id}"></td>
                '''
            elif color =='f':
                color_old = 'f'
                color = f'''<td style="background-color: #FF1493;"><select name="color" autocomplete="off">
                    <option name="color" value="m">masc</option>
                    <option name="color" value="f" selected>fem</option>
                    <option name="color" value="0">none</option>
                    </select>
                    <input type="hidden" name="color_old" value="{color_old}">
                    <input type="hidden" name="color_id" value="{id}"></td>
                    '''
            else:
                color_old = '0'
                color = f'''<td><select name="color" autocomplete="off">
                    <option name="color" value="m">masc</option>
                    <option name="color" value="f">fem</option>
                    <option name="color" value="0" selected>none</option>
                    </select>
                    <input type="hidden" name="color_old" value="{color_old}">
                    <input type="hidden" name="color_id" value="{id}"></td>
                    '''

            f = str(footnote_num)

            if footnote:
                footnote_btn = f'''
                    <button class="toggleButton" data-target="footnotes-{f}" type="button" style="
                        background-color: #5C6BC0; 
                        color: white; 
                        border: none; 
                        border-radius: 50%; 
                        padding: 8px 12px; 
                        width: 40px; 
                        height: 40px; 
                        font-size: 18px; 
                        display: inline-flex; 
                        align-items: center; 
                        justify-content: center; 
                        cursor: pointer; 
                        transition: background-color 0.3s ease, transform 0.3s ease;
                    " onclick="toggleFootnote(this)" onmouseover="this.style.backgroundColor='#3F51B5'" onmouseout="this.style.backgroundColor='#5C6BC0'" onmousedown="this.style.transform='scale(0.95)'" onmouseup="this.style.transform='scale(1)'">
                        &#9662;
                    </button>
                '''


                foot_ref = ref.replace(".", "-")
                footnote = f'''
                <td colspan="14" class="footnotes-{f}" style="display: none;">
                    {footnote}<br>
                    <textarea class="my-tinymce" name="footnote-{f}" id="footnote-{f}" autocomplete="off" style="width: 100%;" rows="6">{footnote}</textarea><br>
                    <input type="hidden" name="old_footnote-{f}" value="does not work">
                    &lt;a class=&quot;sdfootnoteanc&quot; href=&quot;?footnote={foot_ref}&quot;&gt;&lt;sup&gt;num&lt;/sup&gt;&lt;/a&gt;
                </td>
                '''

            else:
                footnote_btn = f'''
                    <button class="toggleButton" data-target="footnotes-{f}" type="button" style="
                        background-color: #BDBDBD; 
                        color: white; 
                        border: none; 
                        border-radius: 50%; 
                        padding: 8px 12px; 
                        width: 40px; 
                        height: 40px; 
                        font-size: 18px; 
                        display: inline-flex; 
                        align-items: center; 
                        justify-content: center; 
                        cursor: pointer; 
                        transition: background-color 0.3s ease, transform 0.3s ease;
                    " onclick="toggleFootnote(this)" onmouseover="this.style.backgroundColor='#3F51B5'" onmouseout="this.style.backgroundColor='#BDBDBD'" onmousedown="this.style.transform='scale(0.95)'" onmouseup="this.style.transform='scale(1)'">
                        +
                    </button>
                '''

                foot_ref = ref.replace(".", "-")
                footnote = f'''
                <td colspan="14" class="footnotes-{f}" style="display: none;">
                    No footnote<br>
                    <textarea class="my-tinymce" name="footnote-{f}" id="footnote-{f}" autocomplete="off" style="width: 100%;" rows="6"></textarea><br>
                    <input type="hidden" name="old_footnote-{f}" value="">
                </td>
                '''
            # Append all data to edit_table_data
            edit_table_data.append((id, ref, eng, unique, combined_hebrew, color, search_count, search_count2, strongs, formatted_strongs_list, morph, combined_heb_niqqud, combined_heb, footnote_btn, footnote))
            
            footnote_num += 1

        english_verse = ' '.join(filter(None, english_verse))
        english_verse = english_verse.replace("אֵת- ", "אֵת-")

    
        if html is not None:
            english_reader = html
        else:
            english_reader = english_verse

        verse = convert_to_book_chapter_verse(rbt_heb_ref)
        
        context = {'verse': verse, 
                'prev_ref': prev_ref,
                'next_ref': next_ref,
                'rbt': rbt,
                'english_reader': english_reader,
                'english_verse': english_verse,
                'strong_row': strong_row,
                'english_row': english_row, 
                'hebrew_row': hebrew_row,
                'edit_table_data': edit_table_data,
                'updates': updates,
                'verse_id': verse_id,
                'chapter_reader': chapter_reader,
                'invalid_verse': invalid_verse,
                'hebrew': hebrew_clean,
                'smith': smith
                }
        
        return render(request, 'hebrew.html', {'page_title': page_title, **context})


def search_footnotes(request):
    if request.headers.get('x-requested-with') == 'XMLHttpRequest':
        query = request.GET.get("query", "")
        results = []

        # Perform the search in your database
        footnotes_genesis = GenesisFootnotes.objects.filter(footnote_html__icontains=query)

        footnotes_nt = execute_query(
            """
            SELECT footnote_id, footnote_html
            FROM new_testament.joh_footnotes
            WHERE footnote_html ILIKE %s;
            """,
            (f'%{query}%',),
            fetch='all'
        )
        
        # Initialize a counter for results
        result_count = 0

        # Create an empty list to store the table rows
        table_rows = []

        for footnote in footnotes_nt:
            # Increment the result count for each footnote
            result_count += 1

            # Split the footnote_id by dashes and get the last slice as the anchor text
            footnote_id = footnote[0]
            footnote_html = footnote[1]

            footnote_id_parts = footnote_id.split('-')
            book = footnote_id_parts[0]
            ref_num = footnote_id_parts[1]
            
            # Parse the HTML content and highlight the matching search term
            soup = BeautifulSoup(footnote_html, 'html.parser')
            
            # Function to replace text between tags
            def replace_text_between_tags(tag):
                for content in tag.contents:
                    if isinstance(content, NavigableString):
                        # Replace text only if we are between tags

                        modified_content = re.sub(re.escape(query), f'<span class="highlighted-search-term">{escape(query)}</span>', str(content), flags=re.IGNORECASE)
                        content.replace_with(BeautifulSoup(modified_content, 'html.parser'))



            # Iterate over all tags and perform the replacement
            for tag in soup.find_all():
                replace_text_between_tags(tag)

            # Get the modified HTML content
            highlighted_footnote = str(soup)

            # Create a table row for the current result
            table_row = f'<tr><td style="vertical-align: top;"><span class="result_verse_header"></span><p><a href="../edit_footnote/?book={book}&footnote={ref_num}">#{book}-{ref_num}</a></p></td><td>{highlighted_footnote}</td></tr>'

            # Append the table row to the list
            table_rows.append(table_row)

        # Iterate through footnotes
        for footnote in footnotes_genesis:
            # Increment the result count for each footnote
            result_count += 1

            # Split the footnote_id by dashes and get the last slice as the anchor text
            footnote_id_parts = footnote.footnote_id.split('-')
            chapter = footnote_id_parts[0]
            verse = footnote_id_parts[1]
            ref_num = footnote_id_parts[-1]
            
            # Parse the HTML content and highlight the matching search term
            soup = BeautifulSoup(footnote.footnote_html, 'html.parser')
            
            # Function to replace text between tags
            def replace_text_between_tags(tag):
                for content in tag.contents:
                    if isinstance(content, NavigableString):
                        # Replace text only if we are between tags

                        modified_content = re.sub(re.escape(query), f'<span class="highlighted-search-term">{escape(query)}</span>', str(content), flags=re.IGNORECASE)
                        content.replace_with(BeautifulSoup(modified_content, 'html.parser'))



            # Iterate over all tags and perform the replacement
            for tag in soup.find_all():
                replace_text_between_tags(tag)

            # Get the modified HTML content
            highlighted_footnote = str(soup)

            # Create a table row for the current result
            table_row = f'<tr><td style="vertical-align: top;"><span class="result_verse_header"><a href="../edit/?book=Genesis&chapter={chapter}&verse={verse}">Gen {chapter}:{verse}</a></span><p><a href="../edit_footnote/?footnote={chapter}-{verse}-{ref_num}">#{ref_num}</a></p></td><td>{highlighted_footnote}</td></tr>'

            # Append the table row to the list
            table_rows.append(table_row)

        # Add the result count at the top
        results.append(f"Total results: {result_count}")

        # Create the HTML table
        result_table = f'<table>{"".join(table_rows)}</table>'

        # Add the table to the results
        results.append(result_table)

        return JsonResponse({"results": results})

    return JsonResponse({}, status=400)

@login_required
def update_hebrew_data(request):
    if request.method == 'POST':
        strongs_number = request.POST.get('strongs_number')
        english_word_update = request.POST.get('english_word_update')

        # Ensure strongs_number is formatted correctly with leading 'H' and padded with '0' if necessary
        if strongs_number:
            if len(strongs_number) == 3:
                strongs_number = f"0{strongs_number}"
            strongs_number = f"H{strongs_number}="

        if english_word_update and strongs_number:
            def stream_updates():

                # Query to find matching entries where Strongs contains the substring
                rows = execute_query(
                    """
                    SELECT id, Ref, Eng, heb6_n, heb5_n, heb4_n, heb3_n, heb2_n, heb1_n, Morph
                    FROM old_testament.hebrewdata
                    WHERE Strongs LIKE %s;
                    """,
                    (f'%{strongs_number}%',),
                    fetch='all'
                )

                # Iterate over the fetched rows
                for row in rows:
                    # Combine non-null parts into a single string
                    heb_parts = [part for part in row[3:9] if part is not None and part not in (':', '־', 'ס')]
                    hebrew_construct = ' '.join(heb_parts)
                    
                    ref = row[1]
                    eng = row[2]
                    morph_data = row[9]

                    # Process the combined string, Morph data, and updated English word
                    translation = gpt_translate(hebrew_construct, morph_data, english_word_update)

                    # Update the 'Eng' column in the table (commented out for testing)
                    # update_query = "UPDATE hebrewdata SET Eng = ? WHERE id = ?"
                    # cursor.execute(update_query, (translation, row[0]))
                    # conn.commit()

                    # Stream the update to the client immediately
                    yield f"Updated {eng} in {ref} with <b>{translation}</b> from <span style='font-size: larger; color: orange;'>{hebrew_construct}</span> for {strongs_number}.<br>"

                    #print(f"Updated {eng} in {ref} with {translation} from {hebrew_construct} for {strongs_number}.")


                # After all updates are done, yield a completion message
                yield "<b>Update process completed.</b>"
            
            # Return the streaming response
            return StreamingHttpResponse(stream_updates(), content_type='text/html')
        
    return render(request, 'update_hebrew_data.html')


@login_required
def find_replace_genesis(request):
    '''Find and replace for the book of Genesis only'''
    if request.method == 'POST':

        find_footnote_text = request.POST.get('find_footnote_text')
        replace_footnote_text = request.POST.get('replace_footnote_text')

        if find_footnote_text:
            # Query GenesisFootnotes records
            footnotes = GenesisFootnotes.objects.all()
            genesis_footnote_replacement_count = 0
            for footnote in footnotes:
                original_content = footnote.footnote_html

                # Save the original content into original_footnotes_html
                footnote.original_footnotes_html = original_content
                updated_content = original_content.replace(find_footnote_text, replace_footnote_text)

                # Update the database with the modified content
                footnote.footnote_html = updated_content
                footnote.save()
                genesis_footnote_replacement_count += original_content.count(find_footnote_text)

        return render(request, 'find_replace_result.html', {'genesis_footnote_replacement_count': genesis_footnote_replacement_count})

    return render(request, 'find_replace.html')

@login_required
def undo_replacements_view(request):

    if request.method == 'POST':
        # Revert the changes by reloading the original content
        footnotes = GenesisFootnotes.objects.all()
        for footnote in footnotes:
            footnote.footnote_html = footnote.original_footnotes_html  # Assuming you have an 'original_footnotes_html' field
            footnote.save()

        # Redirect back to the find and replace page
        return redirect('find_replace')

    return render(request, 'undo_replacements.html')


@login_required
def edit_search(request):
    query = request.GET.get('q')  # keyword search form used
    book = request.GET.get('book')
    footnote_id = request.GET.get('footnote')

    #  KEYWORD SEARCH
    if query:
        
        results = Genesis.objects.filter(html__icontains=query)
        # Strip only paragraph tags from results
        for result in results:
            result.html = result.html.replace('<p>', '').replace('</p>', '')  # strip the paragraph tags

            
            # Apply bold to search query
            result.html = re.sub(
                f'({re.escape(query)})',
                r'<strong>\1</strong>',
                result.html,
                flags=re.IGNORECASE
            )

        # Count the number of results
        rbt_result_count = len(results)

       # Search the hebrew or greek databases
        nt_books = [
            'Mat', 'Mar', 'Luk', 'Joh', 'Act', 'Rom', '1Co', '2Co', 'Gal', 'Eph',
            'Phi', 'Col', '1Th', '2Th', '1Ti', '2Ti', 'Tit', 'Phm', 'Heb', 'Jam',
            '1Pe', '2Pe', '1Jo', '2Jo', '3Jo', 'Jud', 'Rev'
        ]
        ot_books = [
                'Gen', 'Exo', 'Lev', 'Num', 'Deu', 'Jos', 'Jdg', 'Rut', '1Sa', '2Sa',
                '1Ki', '2Ki', '1Ch', '2Ch', 'Ezr', 'Neh', 'Est', 'Job', 'Psa', 'Pro',
                'Ecc', 'Sng', 'Isa', 'Jer', 'Lam', 'Eze', 'Dan', 'Hos', 'Joe', 'Amo',
                'Oba', 'Jon', 'Mic', 'Nah', 'Hab', 'Zep', 'Hag', 'Zec', 'Mal'
            ]
        

        if book == 'all':
            # Construct OR conditions for OT and NT
            ot_conditions = " OR ".join([f"Ref LIKE %s" for _ in ot_books])
            nt_conditions = " OR ".join([f"verse LIKE %s" for _ in nt_books])

            # OT rows
            ot_rows = execute_query(
                f"SELECT * FROM old_testament.hebrewdata WHERE {ot_conditions};",
                tuple(f"%{bookref}%" for bookref in ot_books),
                fetch='all'
            )
            ot_column_names = [desc[0] for desc in execute_query(
                "SELECT * FROM old_testament.hebrewdata LIMIT 0;", fetch='all')]

            # NT rows
            nt_rows = execute_query(
                f"SELECT * FROM rbt_greek.strongs_greek WHERE {nt_conditions};",
                tuple(f"%{bookref}%" for bookref in nt_books),
                fetch='all'
            )
            nt_column_names = [desc[0] for desc in execute_query(
                "SELECT * FROM rbt_greek.strongs_greek LIMIT 0;", fetch='all')]

        elif book == 'NT':
            nt_conditions = " OR ".join([f"verse LIKE %s" for _ in nt_books])
            book_rows = execute_query(
                f"SELECT * FROM rbt_greek.strongs_greek WHERE {nt_conditions};",
                tuple(f"%{bookref}%" for bookref in nt_books),
                fetch='all'
            )
            column_names = [desc[0] for desc in execute_query(
                "SELECT * FROM rbt_greek.strongs_greek LIMIT 0;", fetch='all')]

        elif book == 'OT':
            ot_conditions = " OR ".join([f"Ref LIKE %s" for _ in ot_books])
            book_rows = execute_query(
                f"SELECT * FROM old_testament.hebrewdata WHERE {ot_conditions};",
                tuple(f"%{bookref}%" for bookref in ot_books),
                fetch='all'
            )
            column_names = [desc[0] for desc in execute_query(
                "SELECT * FROM old_testament.hebrewdata LIMIT 0;", fetch='all')]

        elif book in ot_books:
            book_rows = execute_query(
                "SELECT * FROM old_testament.hebrewdata WHERE Ref LIKE %s;",
                (f"%{book}%",),
                fetch='all'
            )
            column_names = [desc[0] for desc in execute_query(
                "SELECT * FROM old_testament.hebrewdata LIMIT 0;", fetch='all')]

        else:
            book_rows = execute_query(
                "SELECT * FROM rbt_greek.strongs_greek WHERE verse LIKE %s;",
                (f"%{book}%",),
                fetch='all'
            )
            column_names = [desc[0] for desc in execute_query(
                "SELECT * FROM rbt_greek.strongs_greek LIMIT 0;", fetch='all')]


        query_count = 0
        links = []

        if book == 'NT' or book in nt_books:
            index = column_names.index('english')
            for row in book_rows:
            # Check if index is not None and 'query' exists in the column (case-insensitive)
                if row[index] and query.lower() in row[index].lower():
                    query_count += 1
                    verse = row[1]
                    bookref = verse[:3]
                    bookref = convert_book_name(bookref)
                    bookref = bookref.lower()
                    bookref = bookref.replace(' ', '_')
                    verse1 = verse[:-3]
                    verse = verse1[4:]
                    verse = verse.replace('.', '-')
                    
                    link = f'<a href="https://biblehub.com/{bookref}/{verse}.htm">{verse1}</a>'
                    links.append(link)


        elif book == 'OT' or book in ot_books:
            index = column_names.index('Strongs')
            for row in book_rows:
            # Check if index is not None and 'query' exists in the column (case-insensitive)
                if row[index] and query.lower() in row[index].lower():
                    query_count += 1
                    verse = row[1]
                    bookref = verse[:3]
                    bookref = convert_book_name(bookref)
                    bookref = bookref.lower()
                    bookref = bookref.replace(' ', '_')
                    verse1 = verse[:-3]
                    verse = verse1[4:]
                    verse = verse.replace('.', '-')
                    link = f'<a href="https://biblehub.com/{bookref}/{verse}.htm">{verse1}</a>'
                    links.append(link)

        elif ot_rows is not None:
            index_ot = ot_column_names.index('Strongs')
            index_nt = nt_column_names.index('english')

            for row in ot_rows:
                # Check if index is not None and 'query' exists in the column (case-insensitive)
                if row[index_ot] and query.lower() in row[index_ot].lower():
                    query_count += 1
                    verse = row[1]
                    bookref = verse[:3]
                    bookref = convert_book_name(bookref)
                    bookref = bookref.lower()
                    bookref = bookref.replace(' ', '_')
                    verse1 = verse[:-3]
                    verse = verse1[4:]
                    verse = verse.replace('.', '-')
                    link = f'<a href="https://biblehub.com/{bookref}/{verse}.htm">{verse1}</a>'
                    links.append(link)

            for row in nt_rows:
                # Check if index is not None and 'query' exists in the column (case-insensitive)
                if row[index_nt] and query.lower() in row[index_nt].lower():
                    query_count += 1
                    verse = row[1]
                    bookref = verse[:3]
                    bookref = convert_book_name(bookref)
                    bookref = bookref.lower()
                    bookref = bookref.replace(' ', '_')
                    verse1 = verse[:-3]
                    verse = verse1[4:]
                    verse = verse.replace('.', '-')
                    link = f'<a href="https://biblehub.com/{bookref}/{verse}.htm">{verse1}</a>'
                    links.append(link)


        # if individual book is searched convert the full to the abbrev
        if book not in ['NT', 'OT', 'all']:
            book2 = convert_book_name(book)
            book = book2.lower()  
        else:
            book2 = book

        page_title = f'Search results for "{query}"'
        context = {'results': results, 
                   'query': query, 
                   'rbt_result_count': rbt_result_count, 
                   'links': links, 
                   'query_count': query_count,
                   'book2': book2, 
                   'book': book }
        return render(request, 'edit_search_results.html', {'page_title': page_title, **context})

    if footnote_id:

        redirect_url = f'../edit_footnote/?footnote={footnote_id}'
        context = {'redirect_url': redirect_url, }
        return render(request, 'footnote_redirect.html', context)
        
    else:
        return render(request, 'edit_input.html')

@login_required
def chapter_editor(request):
    book = request.GET.get('book')
    chapter_num = request.GET.get('chapter_num')

    # Fetch all unique books from NT
    unique_books = [row[0] for row in execute_query(
        "SELECT DISTINCT book FROM new_testament.nt;",
        fetch='all'
    )]

    if request.method == 'GET':
        # Fetch all verses in the requested chapter
        rbt_chapter_data = execute_query(
            "SELECT verseID, rbt FROM new_testament.nt WHERE book = %s AND chapter = %s ORDER BY startVerse;",
            (book, chapter_num),
            fetch='all'
        )

        return render(
            request,
            'edit_chapter.html',
            {
                'rbt_chapter_data': rbt_chapter_data,
                'unique_books': unique_books
            }
        )

    elif request.method == 'POST':
        # Update edited verses
        for verse_id_str, edited_text in request.POST.items():
            if verse_id_str.isdigit():
                verse_id = int(verse_id_str)
                execute_query(
                    "UPDATE new_testament.nt SET rbt = %s WHERE verseID = %s;",
                    (edited_text, verse_id)
                )

        messages.success(request, 'Changes saved successfully.')
        return redirect('edit_chapter', book=book, chapter=chapter_num)

    else:
        # Fallback GET/other method
        return render(request, 'edit_chapter.html', {'unique_books': unique_books})
    
@login_required
def find_and_replace_nt(request):
    context = {}

    def new_replacement_id():
        csv_file_path = 'word_replacement_log.csv'
        if not os.path.exists(csv_file_path):
            return 1
        with open(csv_file_path, 'r', newline='', encoding='utf-8') as csvfile:
            csv_reader = csv.reader(csvfile)
            last_id = 0
            for row in csv_reader:
                try:
                    last_id = int(row[0])
                except ValueError:
                    continue
            return last_id + 1

    if request.method == 'POST':
        find_text = request.POST.get('find_text')
        replace_text = request.POST.get('replace_text')

        # Handle approved replacements
        if 'approve_replacements' in request.POST:
            approved_replacements = request.POST.getlist('approve_replacements')
            csv_file_path = 'word_replacement_log.csv'
            replacement_id = int(request.POST.get('replacement_id'))
            timestamp = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
            successful_replacements = 0

            with open(csv_file_path, 'a', newline='', encoding='utf-8') as csvfile:
                csv_writer = csv.writer(csvfile)

                for verse_id in approved_replacements:
                    old_text = request.POST.get(f'old_text_{verse_id}')
                    new_text = request.POST.get(f'new_text_{verse_id}')

                    # Update in PostgreSQL
                    execute_query(
                        "UPDATE new_testament.nt SET rbt = %s WHERE verseID = %s;",
                        (new_text, verse_id)
                    )

                    # Log to CSV
                    csv_writer.writerow([replacement_id, timestamp, verse_id, old_text, new_text])
                    successful_replacements += 1

            context['edit_result'] = (
                f'<div class="notice-bar">'
                f'<p><span class="icon"><i class="fas fa-check-circle"></i></span>'
                f'{successful_replacements} replacements successfully applied!</p>'
                f'</div>'
            )
            return render(request, 'find_replace.html', context)

        # Find text and display for approval
        elif find_text and replace_text:

            rows = execute_query(
                "SELECT verseID, book, chapter, startVerse, rbt FROM new_testament.nt WHERE rbt LIKE %s;",
                (f'%{find_text}%',),
                fetch='all'
            )

            file_name_pattern = r'\b\w+\.\w+\b'
            replacements = []

            for verse_id, book, chapter, startVerse, old_text in rows:
                if re.search(file_name_pattern, old_text):
                    continue

                book_name = convert_book_name(book)
                new_text = re.sub(find_text, f'<span class="highlight-find">{find_text}</span>', old_text)
                updated_text = re.sub(find_text, f'<span class="highlight-replace">{replace_text}</span>', new_text)
                new_text_raw = re.sub(find_text, replace_text, old_text)
                verse_link = f'../edit/?book={book_name}&chapter={chapter}&verse={startVerse}'

                if new_text != old_text:
                    replacements.append({
                        'verse_id': verse_id,
                        'old_text': new_text,
                        'new_text': updated_text,
                        'new_text_raw': new_text_raw,
                        'verse_link': verse_link
                    })

            if not replacements:
                context['edit_result'] = '<div class="notice-bar"><p>No matches found for the given word.</p></div>'
                return render(request, 'find_replace.html', context)

            context['replacements'] = replacements
            context['replacement_id'] = new_replacement_id()
            return render(request, 'find_replace_review.html', context)

    return render(request, 'find_replace.html', context)

@login_required
def find_and_replace_ot(request):
    context = {}

    def new_replacement_id():
        csv_file_path = 'word_replacement_log_ot.csv'
        if not os.path.exists(csv_file_path):
            return 1
        with open(csv_file_path, 'r', newline='', encoding='utf-8') as csvfile:
            csv_reader = csv.reader(csvfile)
            last_id = 0
            for row in csv_reader:
                try:
                    last_id = int(row[0])
                except ValueError:
                    continue
            return last_id + 1
    
    if request.method == 'POST':
        find_text = request.POST.get('find_text')
        replace_text = request.POST.get('replace_text')

        if 'approve_replacements' in request.POST:
            approved_replacements = request.POST.getlist('approve_replacements')

            csv_file_path = 'word_replacement_log_ot.csv'
            replacement_id = int(request.POST.get('replacement_id'))
            timestamp = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
            successful_replacements = 0

            with open(csv_file_path, 'a', newline='', encoding='utf-8') as csvfile:
                csv_writer = csv.writer(csvfile)

                for verse_id in approved_replacements:
                    old_text = request.POST.get(f'old_text_{verse_id}')
                    new_text = request.POST.get(f'new_text_{verse_id}')

                    # Update the PostgreSQL database
                    execute_query("SET search_path TO old_testament;")
                    execute_query(
                        "UPDATE ot SET html = %s WHERE id = %s;",
                        (new_text, verse_id)
                    )

                    # Log the replacement
                    csv_writer.writerow([replacement_id, timestamp, verse_id, old_text, new_text])
                    successful_replacements += 1

                # Display a success message with the number of replacements
                context['edit_result'] = (
                    f'<div class="notice-bar">'
                    f'<p><span class="icon"><i class="fas fa-check-circle"></i></span>'
                    f'{successful_replacements} replacements successfully applied!</p>'
                    f'</div>'
                )

                return render(request, 'find_replace.html', context)

        # Step 2: Find text and display for approval
        elif find_text and replace_text:

            # Ensure we are using the correct schema
            execute_query("SET search_path TO old_testament;")

            # Search for the find_text in the OT table
            rows = execute_query(
                "SELECT id, Ref, html, book, chapter, verse FROM ot WHERE html LIKE %s;",
                (f'%{find_text}%',),
                fetch='all'
            )

            # Regular expression to detect file names (e.g., xxxxxxx.xxx)
            file_name_pattern = r'\b\w+\.\w+\b'

            # Prepare replacement data for user review
            replacements = []
            for verse_id, ref, old_text, book, chapter, verse in rows:

                # Skip file names
                if re.search(file_name_pattern, old_text):
                    continue

                new_text = re.sub(find_text, f'<span class="highlight-find">{find_text}</span>', old_text)
                updated_text = re.sub(find_text, f'<span class="highlight-replace">{replace_text}</span>', new_text)
                new_text_raw = re.sub(find_text, replace_text, old_text)
                verse_link = f'../translate/?book={book}&chapter={chapter}&verse={verse}'

                if new_text != old_text:
                    replacements.append({
                        'verse_id': verse_id,
                        'reference': ref,
                        'old_text': re.sub(find_text, f'<span class="highlight-find">{find_text}</span>', old_text),
                        'new_text': updated_text,
                        'new_text_raw': new_text_raw,
                        'verse_link': verse_link
                    })


            # If no replacements were found
            if not replacements:
                context['edit_result'] = '<div class="notice-bar"><p>No matches found for the given word.</p></div>'
                return render(request, 'find_replace.html', context)

            # Store the replacements in the context for the user to review
            context['replacements'] = replacements
            context['replacement_id'] = new_replacement_id()

            return render(request, 'find_replace_review_ot.html', context)

    return render(request, 'find_replace_ot.html', context)


@login_required
def edit_nt_chapter(request):
    """
    View to edit an entire New Testament chapter with WYSIWYG and HTML editors.
    """
    book = request.GET.get('book')
    chapter_num = request.GET.get('chapter')

    # # Validate input
    # if not book or not chapter_num:
    #     return render(request, 'edit_nt_chapter.html', {
    #         'error': 'Please provide both book and chapter.',
    #         'unique_books': nt_abbrev
    #     })

    #     # Fetch all unique books for the dropdown
    #     unique_books = execute_query('SELECT DISTINCT book FROM new_testament.nt')
    #     unique_books = [row[0] for row in unique_books]

    #     if request.method == 'GET':   
    #         # Fetch all verses for the given book and chapter
    #         verses = execute_query('SELECT verseID, rbt, startVerse FROM new_testament.nt WHERE book = %s AND chapter = %s', (book, chapter_num))
    #         if not verses:
    #             return render(request, 'edit_nt_chapter.html', {
    #                 'error': f'No verses found for {book} {chapter_num}.',
    #                 'unique_books': unique_books,
    #                 'book': book,
    #                 'chapter_num': chapter_num
    #             })

    #         # Fetch chapter list for navigation
    #         chapter_list = execute_query('SELECT DISTINCT chapter FROM new_testament.nt WHERE book = %s', (book,))
    #         chapter_list = sorted([row[0] for row in chapter_list])
    #         chapters = ''.join([f'<a href="?book={book}&chapter={number}" style="text-decoration: none;">{number}</a> |' for number in chapter_list])

    #         context = {
    #             'book': book,
    #             'chapter_num': chapter_num,
    #             'verses': verses,
    #             'chapters': chapters,
    #             'unique_books': unique_books,
    #             'cached_hit': cache.get(f'{book}_{chapter_num}_None') is not None
    #         }
    #         return render(request, 'edit_nt_chapter.html', context)

    #     elif request.method == 'POST':
    #         # Process updates for each verse
    #         updates = []
    #         for verse_id, edited_text in request.POST.items():
    #             if verse_id.startswith('verse_') and edited_text:
    #                 verse_id = verse_id.replace('verse_', '')
                    # execute_query(
                    #                 "UPDATE new_testament.nt SET rbt = %s WHERE verseID = %s;",
                    #                 (edited_text.strip(), verse_id)
                    #             )
    #                 updates.append(f'Updated verse {verse_id}')

    #         conn.commit()

    #         # Clear cache
    #         cache_key_base_chapter = f'{book}_{chapter_num}_None'
    #         cache.delete(cache_key_base_chapter)
    #         updates.append(f'Deleted cache key: {cache_key_base_chapter}')

    #         # Save update log
    #         update_text = f"Updated {len(updates)} verses in {book} {chapter_num}"
    #         update_instance = TranslationUpdates(
    #             date=datetime.now(),
    #             version='New Testament',
    #             reference=f'{book} {chapter_num}',
    #             update_text=update_text
    #         )
    #         update_instance.save()

    #         messages.success(request, f'Successfully updated {len(updates)} verses.')
    #         return redirect(f'/edit_nt_chapter/?book={book}&chapter={chapter_num}')

    return render(request, 'edit_nt_chapter.html')

@login_required
def edit_aseneth(request):
    """
    Edit view for Joseph and Aseneth translation database.
    Handles viewing and editing verses from the Joseph_Aseneth schema.
    """
    
    book = "He is Adding and Storehouse"  # Default book name
    chapter_num = request.GET.get('chapter')
    verse_num = request.GET.get('verse')
    
    # Handle POST requests (editing verses)
    if request.method == 'POST':
        edited_greek = request.POST.get('edited_greek')
        edited_english = request.POST.get('edited_english')
        record_id = request.POST.get('record_id')
        chapter_num = request.POST.get('chapter')
        verse_num = request.POST.get('verse')
        verse_input = request.POST.get('verse_input')
        
        # Handle verse navigation
        if verse_input:
            context = get_aseneth_context(chapter_num, verse_input)
            return render(request, 'edit_aseneth_verse.html', context)
        
        # Handle verse update
        if record_id and (edited_greek or edited_english):
            try:
                with get_db_connection() as conn:
                    cursor = conn.cursor()
                    cursor.execute("SET search_path TO joseph_aseneth")
                    
                    # Determine which field was edited
                    if edited_greek is not None:
                        sql_query = "UPDATE aseneth SET greek = %s WHERE id = %s"
                        cursor.execute(sql_query, (edited_greek.strip(), record_id))
                        version = 'Aseneth Greek'
                        update_text = edited_greek
                    elif edited_english is not None:
                        sql_query = "UPDATE aseneth SET english = %s WHERE id = %s"
                        cursor.execute(sql_query, (edited_english.strip(), record_id))
                        version = 'Aseneth English'
                        update_text = edited_english
                    
                    conn.commit()
                    
                    # Log the update
                    update_text = re.sub(r'<a\s+.*?>(.*?)</a>', r'\1', update_text)
                    update_version = version
                    update_date = datetime.now()
                    update_instance = TranslationUpdates(
                        date=update_date, 
                        version=update_version, 
                        reference=f"{book} {chapter_num}:{verse_num}", 
                        update_text=update_text
                    )
                    update_instance.save()
                    
                    # Clear cache
                    cache_key_base_verse = f'aseneth_{chapter_num}_{verse_num}'
                    cache_key_base_chapter = f'aseneth_{chapter_num}_None'
                    cache.delete(cache_key_base_verse)
                    cache.delete(cache_key_base_chapter)
                    
                    cache_string = f"Deleted Cache key: {cache_key_base_verse}, {cache_key_base_chapter}"
                    
                    context = get_aseneth_context(chapter_num, verse_num)
                    context['edit_result'] = f'<div class="notice-bar"><p><span class="icon"><i class="fas fa-check-circle"></i></span>Updated verse successfully! {cache_string}</p></div>'
                    
                    return render(request, 'edit_aseneth_verse.html', context)
                    
            except psycopg2.Error as e:
                context = {
                    'error_message': f"Database error: {e}",
                    'chapter': chapter_num,
                    'verse': verse_num
                }
                return render(request, 'edit_aseneth_verse.html', context)
    
    # Handle GET requests
    elif chapter_num and verse_num:
        # Display single verse for editing
        context = get_aseneth_context(chapter_num, verse_num)
        return render(request, 'edit_aseneth_verse.html', context)
    
    elif chapter_num:
        # Display entire chapter
        context = get_aseneth_chapter(chapter_num)
        return render(request, 'edit_aseneth_chapter.html', context)
    
    else:
        # Display input form
        return render(request, 'edit_aseneth_input.html')

def get_word_entries(words, conn):
    """
    Given a list of words, return a dict of lemma → {english, morph_desc}.
    """
    with conn.cursor() as cur:
        # Use parameterized IN query
        sql = """
        SELECT lemma, english, morph_desc
        FROM rbt_greek.strongs_greek
        WHERE lemma = ANY(%s)
        """
        cur.execute(sql, (words,))
        rows = cur.fetchall()
    return {lemma: {"english": eng, "morph_desc": morph} for lemma, eng, morph in rows}


def get_gpt_translation(greek_text, conn):

    words = re.findall(r"[Α-Ωα-ωἀ-῟́ῇῆ]+", greek_text)
    lemmas = [w.lower() for w in words]
    lexicon = get_word_entries(lemmas, conn)
    lexicon_str = "\n".join(
        f"{lemma}: {entry['english']} ({entry['morph_desc']})"
        for lemma, entry in lexicon.items()
    )
    # print(f"Lexicon entries found: {lexicon}")
    api_url = "https://api.openai.com/v1/chat/completions"
    headers = {
        "Authorization": "Bearer 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",
        "Content-Type": "application/json"
    }
    
    prompt = f"""
        Use the following lexicon entries as your primary glosses when translating.

        LEXICON:
        {lexicon_str}

        FORMATTING RULES:
        1. Link definite articles to their respective nouns
        2. For imperfect indicative verbs, use "kept" instead of "were" if appropriate for the verb sense
        3. Capitalize words that have definite articles (but not "the" itself)
        4. Properly place conjunctions such as δὲ "and". If it is the second word, use "And" at the beginning of the sentence.
        5. Add "of" for genitive constructions, or "while/as" if genitive absolute
        6. Wrap blue color (<span style="color: blue;">) on masculine nouns and participles, pink color (<span style="color: #ff00aa;">) on feminine nouns and participles
        7. Include any definite articles in the coloring.
        8. Always render participles with who/which/that (e.g., "the one who", "the ones who", "that which", "he who", "she who") 
        9. Render personal/possessive pronouns with -self or -selves (e.g., "himself", "themselves")
        10. If there are articular infinitives or a substantive clause, capitalize and substantivize (e.g., "the Journeying of Himself", "the Fearing of the Water")
        11. Render any intensive pronouns with verbs as "You, yourselves are" or "I, myself am"
        12. Return ONLY the HTML sentence with proper span tags for colors

        GREEK TEXT: {greek_text}

        Example 1: he asked close beside <span style="color: blue;">himself</span> for epistles into <span style="color: #ff00aa;">Fertile Land</span> 
        ("<span style="color: #ff00aa;">Damascus</span>") toward <span style="color: #ff00aa;">the Congregations</span> in such a manner that if he found <span style="color: blue;">anyone</span> who are being of <span style="color: #ff00aa;">the Road</span>, both men and women, he might lead those who have been bound into <span style="color: #ff00aa;">Foundation of Peace</span>. 
        And <span style="color: blue;">a certain man</span>, he who is presently existing as <span style="color: blue;">a limping one</span> from out of <span style="color: #ff00aa;">a belly</span> of <span style="color: #ff00aa;">a mother</span> of <span style="color: blue;">himself</span>, kept being carried, him whom they were placing according to <span style="color: #ff00aa;">a day</span> toward <span style="color: #ff00aa;">the Doorway</span> of the Sacred Place, <span style="color: #ff00aa;">the one who is being called</span> '<span style="color: #ff00aa;">Seasonable</span>,' of the Begging for Mercy close beside the ones who were leading into the Sacred Place. 
        
        Example 2: And he is bringing to light, "<span style="color: blue;">Little Horn</span>, <span style="color: #ff00aa;">the Prayer</span> of <span style="color: blue;">yourself</span> has been heard and <span style="color: #ff00aa;">the Charities</span> of <span style="color: blue;">yourself</span> have been remembered in the eye of <span style="color: blue;">the God</span>.
        Return only the formatted HTML sentence.
        """
    
    payload = {
        "model": "gpt-4.1",
        "messages": [
            {"role": "system", "content": "Translate the following Greek text to English using RBT method."},
            {"role": "user", "content": prompt}
        ],
        "max_tokens": 512
    }
    # response = requests.post(api_url, headers=headers, json=payload)
    # if response.status_code == 200:
    #     result = response.json()
    #     return result['choices'][0]['message']['content'].strip()
    # else:
    #     return "Translation error"
    
def get_aseneth_context(chapter_num, verse_num):
    """
    Get context data for a specific verse in Joseph and Aseneth,
    with each Greek word linked to its Logeion entry.
    """
    def link_greek_words(greek_text):
        for punct in ['.', ',', ';', ':', '!', '?']:
            greek_text = greek_text.replace(punct, f' {punct} ')

            # Split by whitespace
            tokens = greek_text.split()
            linked_tokens = []

        for tok in tokens:
            # Check if it's a word (not just punctuation)
            if tok not in ['.', ',', ';', ':', '!', '?']:
                linked_tok = f'''
                <span class="tooltip-container">{tok}
                    <span class="tooltip-text">
                        <a href="https://logeion.uchicago.edu/{tok}" target="_blank">Logeion</a> | 
                        <a href="https://www.perseus.tufts.edu/hopper/morph?l={tok}&la=greek" target="_blank">Perseus</a>
                    </span>
                </span>
                '''
                linked_tokens.append(linked_tok)
            else:
                # Keep punctuation as-is
                linked_tokens.append(tok)

        # Join back with spaces
        return " ".join(linked_tokens)

    try:
        with get_db_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SET search_path TO joseph_aseneth")
            
            # Get the specific verse
            sql_query = """
                SELECT id, book, chapter, verse, greek, english
                FROM aseneth
                WHERE chapter = %s AND verse = %s
            """
            cursor.execute(sql_query, (chapter_num, verse_num))
            result = cursor.fetchone()
            
            if result:
                greek_text = result[4] or ""
                # Split Greek text into words, wrap each in a link
   
                greek_with_links = link_greek_words(greek_text)
                gpt_translation = get_gpt_translation(greek_text, conn)
                
                verse_data = {
                    'id': result[0],
                    'book': result[1],
                    'chapter': result[2],
                    'verse': result[3],
                    'greek_with_links': greek_with_links,
                    'english': result[5],
                    'gpt_translation': gpt_translation
                }
            else:
                verse_data = None

            # Chapter list for navigation
            cursor.execute("SELECT DISTINCT chapter FROM aseneth ORDER BY chapter")
            chapter_list = [row[0] for row in cursor.fetchall()]

            # Max verse in chapter
            cursor.execute("SELECT MAX(verse) FROM aseneth WHERE chapter = %s", (chapter_num,))
            max_verse = cursor.fetchone()[0]

            context = {
                'verse_data': verse_data,
                'book': 'He is Adding and Storehouse',
                'chapter': chapter_num,
                'verse': verse_num,
                'chapter_list': chapter_list,
                'max_verse': max_verse
            }

            return context

    except psycopg2.Error as e:
        return {
            'error_message': f"Database error: {e}",
            'chapter': chapter_num,
            'verse': verse_num
        }


def get_aseneth_chapter(chapter_num):
    """
    Get all verses for a chapter in Joseph and Aseneth.
    """
    # Check cache first
    cache_key = f'aseneth_{chapter_num}_None'
    cached_data = cache.get(cache_key)
    
    if cached_data:
        return {
            **cached_data,
            'cached_hit': True
        }
    
    try:
        with get_db_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SET search_path TO joseph_aseneth")
            
            # Get all verses in the chapter
            sql_query = """
                SELECT id, book, chapter, verse, greek, english
                FROM aseneth
                WHERE chapter = %s
                ORDER BY verse
            """
            cursor.execute(sql_query, (chapter_num,))
            results = cursor.fetchall()
            
            # Build HTML for chapter display
            html = ""
            for result in results:
                verse_id, book, chapter, verse, greek, english = result
                
                html += f'''
                <div class="verse-container">
                    <span class="verse_ref">¶<b><a href="?chapter={chapter}&verse={verse}">{verse}</a></b></span>
                    <div class="verse-content">
                        <div class="greek-text">{greek}</div>
                        <div class="english-text">{english}</div>
                    </div>
                </div>
                '''
            
            # Get chapter list for navigation
            cursor.execute("SELECT DISTINCT chapter FROM aseneth ORDER BY chapter")
            chapter_list = [row[0] for row in cursor.fetchall()]
            
            # Build chapter navigation links
            chapters = ''
            for number in chapter_list:
                chapters += f'<a href="?chapter={number}" style="text-decoration: none;">{number}</a> | '
            
            context = {
                'html': html,
                'book': 'He is Adding and Storehouse',
                'chapter_num': chapter_num,
                'chapters': chapters,
                'chapter_list': chapter_list,
                'cached_hit': False
            }
            
            # Cache the result
            cache.set(cache_key, context, 60 * 60 * 24)  # Cache for 24 hours
            
            return context
            
    except psycopg2.Error as e:
        return {
            'error_message': f"Database error: {e}",
            'chapter_num': chapter_num,
            'html': '',
            'chapters': ''
        }

