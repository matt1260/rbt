import logging
import uuid

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
from search.views import get_results, INTERLINEAR_CACHE_VERSION, get_footnote
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
from .db_utils import get_db_connection, execute_query, table_has_column
import psycopg2
import requests
from urllib.parse import quote, unquote
from django.views.decorators.http import require_POST

GEMINI_API_KEY = os.getenv('GEMINI_API_KEY')
client = genai.Client(api_key=GEMINI_API_KEY)

DEFAULT_GEMINI_MODEL = os.getenv('GEMINI_MODEL_NAME', 'gemini-3-flash-preview')
MODEL_NAME_PATTERN = re.compile(r'^[\w\-.:+]+$')

logger = logging.getLogger(__name__)


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

DEFAULT_GREEK_GEMINI_PROMPT = """
You are formatting the sentence from these english words and morphology. Using the provided data, create the English sentence following these rules:

1. Link definite articles to their respective nouns
2. For imperfect indicative verbs, use "kept" instead of "were" if appropriate for the verb sense
3. Capitalize words that have definite articles (but not "the" itself)
4. Properly place conjunctions such as δὲ "and". If it is the second word, use "And" at the beginning of the sentence.
5. Add "of" for genitive constructions, or "while/as" if genitive absolute
6. Choose the most ideal word if multiple English options are given (separated by slashes)
7. Wrap blue color (<span style="color: blue;">) on masculine words, pink color (<span style="color: #ff00aa;">) on feminine words
8. Include any definite articles in the coloring
9. Always render participles with who/which/that (e.g., "the one who", "the ones who", "that which", "he who", "she who")
10. Render personal/possessive pronouns with -self or -selves (e.g., "himself", "themselves")
11. If there are articular infinitives or substantive clauses, capitalize and substantivize (e.g., "the Journeying of Himself", "the Fearing of the Water")
12. Render any intensive pronouns with verbs as "You, yourselves are" or "I, myself am"
13. Return ONLY the HTML sentence with proper span tags for colors

Example 1: he asked close beside <span style="color: blue;">himself</span> for epistles into <span style="color: #ff00aa;">Fertile Land</span> ("<span style="color: #ff00aa;">Damascus</span>") toward <span style="color: #ff00aa;">the Congregations</span> in such a manner that if he found <span style="color: blue;">anyone</span> who are being of <span style="color: #ff00aa;">the Road</span>, both men and women, he might lead those who have been bound into <span style="color: #ff00aa;">Foundation of Peace</span>. And <span style="color: blue;">a certain man</span>, he who is presently existing as <span style="color: blue;">a limping one</span> from out of <span style="color: #ff00aa;">a belly</span> of <span style="color: #ff00aa;">a mother</span> of <span style="color: blue;">himself</span>, kept being carried, him whom they were placing according to <span style="color: #ff00aa;">a day</span> toward <span style="color: #ff00aa;">the Doorway</span> of the Sacred Place, <span style="color: #ff00aa;">the one who is being called</span> '<span style="color: #ff00aa;">Seasonable</span>,' of the Begging for Mercy close beside the ones who were leading into the Sacred Place.

Example 2: And he is bringing to light, "<span style="color: blue;">Little Horn</span>, <span style="color: #ff00aa;">the Prayer</span> of <span style="color: blue;">yourself</span> has been heard and <span style="color: #ff00aa;">the Charities</span> of <span style="color: blue;">yourself</span> have been remembered in the eye of <span style="color: blue;">the God</span>. Return only the formatted HTML sentence.
""".strip()

DEFAULT_HEBREW_GEMINI_PROMPT = """
You are creating a polished but faithful English rendering of a Biblical Hebrew verse. Combine the supplied Hebrew text and the linear English gloss to craft one English sentence that preserves Hebrew emphasis while reading naturally.

Guidelines:
1. Maintain Hebrew word order where it clarifies emphasis, but smooth awkward phrasing.
2. Preserve divine names and key transliterations; do not replace them with generic titles.
3. When linear English shows multiple options (slashes), pick the best fit for the context and avoid repeating synonyms.
4. Keep embedded HTML (bold, spans, etc.) intact if present in the suggestion.
5. Sum up clauses with clear punctuation; avoid fragments.
6. Return only the HTML sentence (no explanations, no markdown fences).
""".strip()


def _safe_book_name(name: str | None) -> str:
    """Convert a book identifier to a display name, falling back gracefully."""
    if not name:
        return ''
    converted = convert_book_name(name)
    return converted if converted else name


def gpt_translate(hebrew_construct: str | None, morph_data: str | None, english_word_update: str | None) -> str:
    """Fallback translation builder for Hebrew updates when AI service is unavailable."""
    pieces: list[str] = []
    if english_word_update:
        pieces.append(english_word_update.strip())
    if hebrew_construct:
        pieces.append(f'({hebrew_construct.strip()})')
    if morph_data:
        pieces.append(f'[{morph_data.strip()}]')
    if not pieces:
        return ''
    return ' '.join(p for p in pieces if p)


def _invalidate_reader_cache(book: str | None, chapter: str | int | None, verse: str | int | None = None) -> list[str]:
    """Remove cached reader entries for the requested location."""
    deleted_keys: list[str] = []
    if not book or chapter in (None, ''):
        return deleted_keys

    sanitized_book = str(book).replace(':', '_').replace(' ', '')
    chapter_str = str(chapter)

    if verse not in (None, '', 'None'):
        verse_str = str(verse)
        verse_key = f'{sanitized_book}_{chapter_str}_{verse_str}_{INTERLINEAR_CACHE_VERSION}'
        cache.delete(verse_key)
        deleted_keys.append(verse_key)

    chapter_key = f'{sanitized_book}_{chapter_str}_None_{INTERLINEAR_CACHE_VERSION}'
    cache.delete(chapter_key)
    deleted_keys.append(chapter_key)

    return deleted_keys


FOOTNOTE_LINK_RE = re.compile(r'\?footnote=([^&"\n]+)')


def collect_footnote_rows(
    html_chunks: list[str] | tuple[str, ...] | None,
    book: str,
    chapter_num: str | int | None = None,
    verse_num: str | int | None = None,
) -> list[str]:
    """Extract distinct footnote table rows from blocks of HTML."""
    if not html_chunks:
        return []

    collected: list[str] = []
    seen: set[str] = set()

    for chunk in html_chunks:
        if not chunk:
            continue

        matches = FOOTNOTE_LINK_RE.findall(str(chunk))
        for footnote_id in matches:
            if footnote_id in seen:
                continue

            seen.add(footnote_id)
            try:
                footnote_html = get_footnote(footnote_id, book, chapter_num, verse_num)
            except Exception as exc:  # pragma: no cover - defensive logging
                print(f"[WARN] Unable to load footnote {footnote_id}: {exc}")
                footnote_html = ''

            if footnote_html:
                collected.append(footnote_html)

    return collected

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
        book_abbrev = book_abbreviations.get(book, book)
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
            'cached_hit': cached_hit,
            'strong_row': results.get('strong_row'),
            'english_row': results.get('english_row'),
            'hebrew_row': results.get('hebrew_row'),
            'hebrew_clean': results.get('hebrew_clean'),
            'morph_row': results.get('morph_row'),
            'hebrew_cards': results.get('hebrew_interlinear_cards', []),
            'hebrewdata_rows': results.get('hebrewdata_rows', []),
        }

        return context


def _apply_gemini_preferences(request, context):
    if context is None:
        return context

    session = getattr(request, 'session', None)
    user = getattr(request, 'user', None)
    is_nt_view = None
    if context.get('book2') or context.get('book'):
        book_key = context.get('book2') or context.get('book')
        is_nt_view = book_key in new_testament_books

    def _pref(key, default):
        if session is None:
            return default
        return session.get(key, default)

    context['default_greek_prompt'] = _pref('gemini_prompt_greek', DEFAULT_GREEK_GEMINI_PROMPT)
    context['default_hebrew_prompt'] = _pref('gemini_prompt_hebrew', DEFAULT_HEBREW_GEMINI_PROMPT)
    context['default_gemini_model'] = _pref('gemini_model', DEFAULT_GEMINI_MODEL)
    context['gemini_prompt_is_default'] = {
        'greek': context['default_greek_prompt'] == DEFAULT_GREEK_GEMINI_PROMPT,
        'hebrew': context['default_hebrew_prompt'] == DEFAULT_HEBREW_GEMINI_PROMPT,
    }
    context['gemini_user'] = user.username if user and user.is_authenticated else ''
    if is_nt_view is not None:
        context['gemini_view_translation_type'] = 'greek' if is_nt_view else 'hebrew'
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

def _resolve_prompt_text(custom_text: str | None, default_text: str) -> str:
    if custom_text:
        stripped = custom_text.strip()
        if stripped:
            return stripped
    return default_text


def _resolve_model_name(model_name: str | None) -> str:
    candidate = (model_name or '').strip()
    if not candidate:
        return DEFAULT_GEMINI_MODEL
    if not MODEL_NAME_PATTERN.match(candidate):
        raise ValueError('Model name may only include letters, numbers, dashes, periods, plus, and underscores.')
    return candidate


def _strip_html_text(value: str | None) -> str:
    if not value:
        return ''
    try:
        return BeautifulSoup(value, 'html.parser').get_text(' ', strip=True)
    except Exception:
        return value


def _request_gemini_response(prompt: str, model_name: str | None = None) -> str:
    try:
        model_to_use = _resolve_model_name(model_name)
    except ValueError as exc:
        return f"Error: {exc}"

    try:
        print("Requesting Gemini API...")
        response = client.models.generate_content(
            model=model_to_use,
            contents=prompt
        )
        print("Received response from Gemini API.")

        # Extract text portions robustly: response.text preferred, then candidates.content.parts
        def _extract_text(resp):
            # 1) direct .text attribute
            text_val = None
            if hasattr(resp, 'text') and resp.text:
                text_val = resp.text
            # 2) try dict-like access
            if not text_val and isinstance(resp, dict):
                text_val = resp.get('text')

            if text_val:
                return str(text_val).strip()

            # 3) candidates -> content -> parts
            parts_texts = []
            non_text_types = set()

            candidates = None
            # object-style
            if hasattr(resp, 'candidates'):
                candidates = getattr(resp, 'candidates')
            # dict-style fallback
            if not candidates and isinstance(resp, dict):
                candidates = resp.get('candidates')

            if candidates:
                for cand in candidates:
                    content = None
                    if hasattr(cand, 'content'):
                        content = getattr(cand, 'content')
                    elif isinstance(cand, dict):
                        content = cand.get('content')

                    parts = None
                    if content is not None:
                        if hasattr(content, 'parts'):
                            parts = getattr(content, 'parts')
                        elif isinstance(content, dict):
                            parts = content.get('parts')

                    if parts:
                        for part in parts:
                            # part may be object or dict
                            p_type = None
                            p_text = None
                            if isinstance(part, dict):
                                p_type = part.get('type')
                                p_text = part.get('text') or part.get('content')
                            else:
                                p_type = getattr(part, 'type', None)
                                p_text = getattr(part, 'text', None) or getattr(part, 'content', None)

                            if p_text:
                                parts_texts.append(str(p_text))
                            else:
                                if p_type:
                                    non_text_types.add(p_type)
                                else:
                                    # unknown non-text part
                                    non_text_types.add('unknown')

                    # fallback to candidate.text
                    if not parts and hasattr(cand, 'text') and getattr(cand, 'text'):
                        parts_texts.append(str(getattr(cand, 'text')))
                    elif not parts and isinstance(cand, dict) and cand.get('text'):
                        parts_texts.append(str(cand.get('text')))

            # If we have non-text parts and also some text parts, warn
            if non_text_types and parts_texts:
                logger.warning(f"there are non-text parts in the response: %s, returning concatenated text result from text parts. Check the full candidates.content.parts accessor to get the full model response.", list(non_text_types))

            if parts_texts:
                return '\n'.join(parts_texts).strip()

            # last resort: string representation
            try:
                return str(resp).strip()
            except Exception:
                return ''

        content = _extract_text(response)

        if not content:
            return "Error: Empty response from Gemini API"

        return content.replace('```html', '').replace('```', '').strip()

    except AttributeError as exc:
        return f"Error: API client not properly configured: {exc}"
    except Exception as exc:  # pragma: no cover - relies on external API
        message = str(exc)
        if 'not found' in message.lower() or '404' in message:
            return f"Error: Model '{model_to_use}' is unavailable."
        return f"Error: Gemini API failed: {exc}"


def gemini_translate(entries, prompt_instructions: str | None = None, model_name: str | None = None):
    """Translate Greek entries into a formatted English sentence via Gemini."""
    if not isinstance(entries, list) or not entries:
        return "Error: Invalid entries data"

    greek_words: list[str] = []
    english_words: list[str] = []
    morphology_data: list[str] = []

    for entry in entries:
        required_fields = ['lemma', 'english', 'morph_description']
        if not all(field in entry for field in required_fields):
            return f"Error: Missing required fields in entry: {entry}"

        greek_words.append(entry['lemma'])
        english_words.append(entry['english'])
        morphology_data.append(f"{entry['morph_description']} ({entry.get('morph', 'Unknown')})")

    greek_text = ' '.join(greek_words)
    interlinear_english = ' '.join(english_words)
    morphology_info = ' | '.join(morphology_data)

    instructions = _resolve_prompt_text(prompt_instructions, DEFAULT_GREEK_GEMINI_PROMPT)
    prompt = (
        f"{instructions}\n\n"
        f"GREEK TEXT: {greek_text}\n"
        f"ENGLISH WORDS: {interlinear_english}\n"
        f"MORPHOLOGY: {morphology_info}\n"
    )

    return _request_gemini_response(prompt, model_name)


def gemini_translate_hebrew(
    hebrew_text: str | None,
    linear_english: str | None,
    prompt_instructions: str | None = None,
    model_name: str | None = None,
) -> str:
    """Translate Hebrew content using Gemini with editable prompt instructions."""
    if not hebrew_text and not linear_english:
        return "Error: Missing Hebrew data for this verse"

    instructions = _resolve_prompt_text(prompt_instructions, DEFAULT_HEBREW_GEMINI_PROMPT)
    hebrew_plain = _strip_html_text(hebrew_text)
    english_plain = (linear_english or '').strip() or 'Not provided'

    prompt = (
        f"{instructions}\n\n"
        f"HEBREW TEXT: {hebrew_plain}\n"
        f"LINEAR ENGLISH: {english_plain}\n"
    )

    return _request_gemini_response(prompt, model_name)


@login_required
@require_POST
def request_gemini_translation(request):
    """Serve Gemini suggestions on-demand for both Greek and Hebrew verses."""
    try:
        payload = json.loads(request.body.decode('utf-8'))
    except (json.JSONDecodeError, UnicodeDecodeError):
        return JsonResponse({'error': 'Invalid JSON payload.'}, status=400)

    translation_type = payload.get('translation_type')
    book = payload.get('book')
    chapter = payload.get('chapter')
    verse = payload.get('verse')
    prompt_override = payload.get('prompt')
    model_override = payload.get('model')

    try:
        resolved_model = _resolve_model_name(model_override)
    except ValueError as exc:
        return JsonResponse({'error': str(exc)}, status=400)

    if not all([translation_type, book, chapter, verse]):
        return JsonResponse({'error': 'Missing required parameters.'}, status=400)

    try:
        context = _apply_gemini_preferences(request, get_context(book, chapter, verse))
    except Exception as exc:  # pragma: no cover - safety net for DB errors
        return JsonResponse({'error': f'Unable to load verse context: {exc}'}, status=500)

    if translation_type == 'greek':
        entries = context.get('entries') or []
        if not entries:
            return JsonResponse({'error': 'Interlinear entries unavailable for this verse.'}, status=404)
        suggestion = gemini_translate(entries, prompt_override, resolved_model)
    elif translation_type == 'hebrew':
        hebrew_text = context.get('hebrew')
        linear_english = context.get('linear_english')
        suggestion = gemini_translate_hebrew(hebrew_text, linear_english, prompt_override, resolved_model)
    else:
        return JsonResponse({'error': 'Invalid translation type.'}, status=400)

    if isinstance(suggestion, str) and suggestion.startswith('Error:'):
        return JsonResponse({'error': suggestion}, status=502)

    session = getattr(request, 'session', None)
    if session is not None:
        if prompt_override:
            pref_key = f'gemini_prompt_{translation_type}'
            session[pref_key] = prompt_override
        session['gemini_model'] = resolved_model
        session.modified = True

    return JsonResponse({'suggestion': suggestion})


@login_required
@require_POST
def save_gemini_preferences(request):
    try:
        payload = json.loads(request.body.decode('utf-8'))
    except (json.JSONDecodeError, UnicodeDecodeError):
        return JsonResponse({'error': 'Invalid JSON payload.'}, status=400)

    translation_type = payload.get('translation_type')
    if translation_type not in ('greek', 'hebrew'):
        return JsonResponse({'error': 'Invalid translation type.'}, status=400)

    prompt_text = payload.get('prompt')
    model_name = payload.get('model')

    try:
        resolved_model = _resolve_model_name(model_name)
    except ValueError as exc:
        return JsonResponse({'error': str(exc)}, status=400)

    session = getattr(request, 'session', None)
    if session is None:
        return JsonResponse({'error': 'Session storage is unavailable.'}, status=500)

    pref_key = f'gemini_prompt_{translation_type}'
    if prompt_text:
        session[pref_key] = prompt_text
    else:
        session.pop(pref_key, None)

    session['gemini_model'] = resolved_model
    session.modified = True

    return JsonResponse({
        'status': 'saved',
        'model': resolved_model,
        'prompt_key': pref_key,
    })

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

            bookref = _safe_book_name(book)
            bookref = bookref.capitalize() if bookref else ''

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

        soup = BeautifulSoup(footnote_html, 'html.parser')

        # Remove data-start and data-end attributes from all tags
        for tag in soup.find_all(True):
            if 'data-start' in tag.attrs:
                del tag.attrs['data-start']
            if 'data-end' in tag.attrs:
                del tag.attrs['data-end']

        # Add rbt_footnote class to <p> and <ul> tags
        for tag in soup.find_all(['p', 'ul']):
            existing_classes = tag.get('class', [])
            if 'rbt_footnote' not in existing_classes:
                existing_classes.append('rbt_footnote')
            tag['class'] = existing_classes

        footnote_html = str(soup)
        
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

            bookref = _safe_book_name(book)
            bookref = bookref.capitalize() if bookref else ''
            
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
        nt_book = request.POST.get('nt_book')
        replacements = request.POST.get('replacements')
        edited_greek = request.POST.get('edited_greek')
        verse_input = request.POST.get('verse_input')
        hebrewdata_action = request.POST.get('hebrewdata_action')

        if hebrewdata_action == 'update_rows' and book == 'Genesis':
            hebrew_ids = request.POST.getlist('hebrew_ids')
            hebrew_refs = request.POST.getlist('hebrew_refs')
            hebrew_eng_values = request.POST.getlist('hebrew_eng')
            hebrew_eng_original = request.POST.getlist('hebrew_eng_original')
            hebrew_morph_values = request.POST.getlist('hebrew_morph')
            hebrew_morph_original = request.POST.getlist('hebrew_morph_original')

            updated_rows: list[str] = []
            for row in zip(
                hebrew_ids,
                hebrew_refs,
                hebrew_eng_values,
                hebrew_eng_original,
                hebrew_morph_values,
                hebrew_morph_original,
            ):
                (
                    row_id,
                    row_ref,
                    eng_value,
                    eng_original_value,
                    morph_value,
                    morph_original_value,
                ) = row

                try:
                    row_id_int = int(row_id)
                except (TypeError, ValueError):
                    continue

                eng_value = (eng_value or '').strip()
                eng_original_value = (eng_original_value or '').strip()
                morph_value = (morph_value or '').strip()
                morph_original_value = (morph_original_value or '').strip()

                row_updates: list[str] = []
                if eng_value != eng_original_value:
                    execute_query(
                        "UPDATE old_testament.hebrewdata SET Eng = %s WHERE id = %s;",
                        (eng_value, row_id_int),
                    )
                    row_updates.append(f'Eng="{eng_value}"')

                if morph_value != morph_original_value:
                    execute_query(
                        "UPDATE old_testament.hebrewdata SET morphology = %s WHERE id = %s;",
                        (morph_value, row_id_int),
                    )
                    row_updates.append('Morphology updated')

                if row_updates:
                    display_ref = row_ref or f'Row {row_id_int}'
                    updated_rows.append(f'{display_ref}: ' + ', '.join(row_updates))

            cache_string = 'No cache keys cleared'
            if updated_rows:
                reference_book = _safe_book_name(book)
                update_instance = TranslationUpdates(
                    date=datetime.now(),
                    version='Hebrew Data',
                    reference=f"{reference_book} {chapter_num}:{verse_num}",
                    update_text='; '.join(updated_rows)
                )
                update_instance.save()

                cleared_keys = _invalidate_reader_cache(book, chapter_num, verse_num)
                if cleared_keys:
                    cache_string = 'Deleted Cache key: ' + ', '.join(cleared_keys)

            context = _apply_gemini_preferences(request, get_context(book, chapter_num, verse_num))
            if updated_rows:
                context['edit_result'] = (
                    '<div class="notice-bar"><p><span class="icon"><i class="fas fa-check-circle"></i></span>'
                    f'Updated {len(updated_rows)} Hebrewdata entries. {cache_string}</p></div>'
                )
            else:
                context['edit_result'] = (
                    '<div class="notice-bar"><p><span class="icon"><i class="fas fa-info-circle"></i></span>'
                    'No Hebrewdata changes detected.</p></div>'
                )
            return render(request, 'edit_verse.html', context)

        if replacements:
            
            with open('interlinear_english.json', 'w', encoding='utf-8') as file:
                json.dump(replacements, file, indent=4, ensure_ascii=False)
            
            context = _apply_gemini_preferences(request, get_context(book, chapter_num, verse_num))
            context['edit_result'] = '<div class="notice-bar"><p><span class="icon"><i class="fas fa-check-circle"></i></span>Updated replacements successfully!</p></div>'

            return render(request, 'edit_nt_verse.html', context)

        # add new footnote for NT
        if nt_book is not None:
            book_abbrev = book_abbreviations.get(nt_book)
            if book_abbrev is None:
                book_abbrev = nt_book
            if book_abbrev is None:
                return HttpResponse("Invalid book selection.", status=400)

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
                    # Wrap the footnote content in rbt_footnote span
                    footnote_html = f'<p><span class="footnote_header">{footnote_header}</span></p> <p class="rbt_footnote">{footnote_html}</p>'
                    sql_query = f"INSERT INTO {book} (footnote_id, footnote_html) VALUES (%s, %s)"
                    cursor.execute(sql_query, (footnote_id, footnote_html))
                    conn.commit()

                    update_text = re.sub(r'<a\s+.*?>(.*?)</a>', r'\1', footnote_html)
                    update_version = "New Testament Footnote"
                    update_date = datetime.now()
                    update_instance = TranslationUpdates(date=update_date, version=update_version, reference=f"{book} {chapter_num}:{verse_num} - {footnote_id}", update_text=update_text)
                    update_instance.save()
                    
                    cleared_keys = _invalidate_reader_cache(nt_book, chapter_num, verse_num)
                    cache_string = "Deleted Cache key: " + ', '.join(cleared_keys) if cleared_keys else 'No cache keys cleared'

                    context = _apply_gemini_preferences(request, get_context(nt_book, chapter_num, verse_num))
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

            cleared_keys = _invalidate_reader_cache(book, chapter_num, verse_num)
            cache_string = "Deleted Cache key: " + ', '.join(cleared_keys) if cleared_keys else 'No cache keys cleared'

            context = _apply_gemini_preferences(request, get_context(book, chapter_num, verse_num))
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

            cleared_keys = _invalidate_reader_cache(book, chapter_num, verse_num)
            cache_string = "Deleted Cache key: " + ', '.join(cleared_keys) if cleared_keys else 'No cache keys cleared'
            

            context = _apply_gemini_preferences(request, get_context(book, chapter_num, verse_num))
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

            cleared_keys = _invalidate_reader_cache(book, chapter_num, verse_num)
            cache_string = "Deleted Cache key: " + ', '.join(cleared_keys) if cleared_keys else 'No cache keys cleared'

            context = _apply_gemini_preferences(request, get_context(book, chapter_num, verse_num))
            context['edit_result'] = f'<div class="notice-bar"><p><span class="icon"><i class="fas fa-check-circle"></i></span>Updated verse successfully! {cache_string}</p></div>'

            return render(request, 'edit_nt_verse.html', context)

        elif verse_input:
            context = _apply_gemini_preferences(request, get_context(book, chapter_num, verse_input))
            if book in new_testament_books:
                return render(request, 'edit_nt_verse.html', context)
            else:
                return render(request, 'edit_verse.html', context)

        # Fallback: ensure POST always returns an HttpResponse
        if book and chapter_num:
            fallback_context = _apply_gemini_preferences(request, get_context(book, chapter_num, verse_num or '1'))
            if book in new_testament_books:
                return render(request, 'edit_nt_verse.html', fallback_context)
            return render(request, 'edit_verse.html', fallback_context)

        return render(request, 'edit_input.html')
    
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
        
        context = _apply_gemini_preferences(request, get_context(book, chapter_num, verse_num))

        if book in new_testament_books:
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
        count_row = execute_query(query, (lex,), fetch='one')
        return count_row[0] if count_row else 0

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
            excluded_rows_row = execute_query(
                "SELECT COUNT(*) FROM old_testament.hebrewdata WHERE uniq = '1' AND combined_heb_niqqud = %s;", (heb,), fetch='one'
            )
            excluded_rows_count = excluded_rows_row[0] if excluded_rows_row else 0
        else:
            niq = 'without'
            query = f"UPDATE old_testament.hebrewdata SET {column} = %s WHERE combined_heb = %s AND uniq = '0';"
            execute_query(query, (data, heb))
            excluded_rows_row = execute_query(
                "SELECT COUNT(*) FROM old_testament.hebrewdata WHERE uniq = '1' AND combined_heb = %s;", (heb,), fetch='one'
            )
            excluded_rows_count = excluded_rows_row[0] if excluded_rows_row else 0

        update_count_row = execute_query(
            "SELECT COUNT(*) FROM old_testament.hebrewdata WHERE "
            + ("combined_heb_niqqud" if use_niqqud == 'true' else "combined_heb")
            + " = %s AND uniq = '0';",
            (heb,),
            fetch='one'
        )
        update_count = update_count_row[0] if update_count_row else 0
        updates.append(f'Updated column {column} with "{data}" for {update_count} rows where {heb} {niq} niqqud matches. Excluded {excluded_rows_count} rows.')

    def save_english_literal(english_literal, verse_id):
        verse_ref = verse_id.split('-')[0]
        execute_query("UPDATE old_testament.ot SET literal = %s WHERE Ref = %s;", (english_literal, verse_ref))
        updates.append(f'Updated ID: {verse_ref} in Literal with "{english_literal}"')

    def save_html_to_database(verse_id, html):
        verse_ref = verse_id.split('-')[0]
        execute_query("UPDATE old_testament.hebrewdata SET html = %s WHERE Ref = %s;", (html, verse_id))
        execute_query("UPDATE old_testament.ot SET html = %s WHERE Ref = %s;", (html, verse_ref))

        parts = verse_ref.split('.')
        if len(parts) >= 3:
            book_code, chapter_value, verse_value = parts[0], parts[1], parts[2]
        else:
            book_code, chapter_value, verse_value = verse_ref, '1', '1'

        book_name = convert_book_name(book_code) or book_code
        cleared_keys = _invalidate_reader_cache(book_name, chapter_value, verse_value)
        updates.append(f'Updated HTML Paraphrase: {verse_id} in HTML with "{html}".')
        if cleared_keys:
            updates.append(f"Deleted Cache key: {', '.join(cleared_keys)}")

    def save_footnote_to_database(verse_id, id, key, text):
        execute_query("UPDATE old_testament.hebrewdata SET footnote = %s WHERE id = %s;", (text, id))

        verse_id = verse_id.split('-')[0]
        
        update_text = re.sub(r'<a\s+.*?>(.*?)</a>', r'\1', text)
        update_version = "Hebrew Footnote"
        update_date = datetime.now()
        update_instance = TranslationUpdates(date=update_date, version=update_version, reference=f"{verse_id} - {key}", update_text=update_text)
        update_instance.save()

        book_parts = verse_id.split('.')
        if len(book_parts) >= 3:
            book_code, chapter_value, verse_value = book_parts[0], book_parts[1], book_parts[2]
        else:
            book_code, chapter_value, verse_value = verse_id, '1', '1'

        book_name = convert_book_name(book_code) or book_code
        cleared_keys = _invalidate_reader_cache(book_name, chapter_value, verse_value)
        cache_string = "Deleted Cache key: " + ', '.join(cleared_keys) if cleared_keys else 'No cache keys cleared'

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

                if isinstance(updated_count, int) and updated_count > 0:
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
        verse_id_full = verse_id  # Preserve the exact row ref for paraphrase updates
        verse_ref = verse_id.split('-')[0] if verse_id else None
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

        # Handle morphology updates
        morphology_data_list = request.POST.getlist('morphology')
        original_morphology_list = request.POST.getlist('original_morphology')
        morph_id_list = request.POST.getlist('morph_id')
        
        combined_morphology_pairs = zip(original_morphology_list, morphology_data_list)
        morph_id_morphology_pairs = zip(morph_id_list, morphology_data_list)
        
        morphology_change = []
        for old_morph, new_morph in combined_morphology_pairs:
            if old_morph != new_morph:
                morphology_change.append(new_morph)
        
        if morphology_change:
            for id, morph_data in morph_id_morphology_pairs:
                if morph_data in morphology_change:
                    # Update the 'morphology' column for this row only
                    execute_query(
                        """
                        UPDATE old_testament.hebrewdata 
                        SET morphology = %s
                        WHERE id = %s
                        """,
                        (morph_data, id),
                        fetch=None
                    )

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
                        reference = bible.get_references(verse_ref) if verse_ref else None
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
                        reference = bible.get_references(verse_ref) if verse_ref else None
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
                        reference = bible.get_references(verse_ref) if verse_ref else None
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

            save_html_to_database(verse_id_full, html)
            reference = bible.get_references(verse_ref) if verse_ref else None
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

        # Handle footnotes - field names use the actual database row ID (not sequential number)
        footnotes_data = {}  # {row_id: new_footnote_text}
        old_footnotes_data = {}  # {row_id: old_footnote_text}
        updated_footnotes = {}  # {row_id: new_footnote_text} for changed footnotes
        
        for key, value in request.POST.items():
            if key.startswith('footnote-'):
                row_id = key.split('-')[1]  # This is the database row ID
                footnotes_data[row_id] = value
        for key, value in request.POST.items():
            if key.startswith('old_footnote-'):
                row_id = key.split('-')[1]  # This is the database row ID
                old_footnotes_data[row_id] = value
        
        # Debug logging
        logger.debug(f"Footnote POST data - footnotes_data keys: {list(footnotes_data.keys())}")
        logger.debug(f"Footnote POST data - old_footnotes_data keys: {list(old_footnotes_data.keys())}")
        
        for row_id in old_footnotes_data:
            # Check if the values don't match between old and new footnotes
            if old_footnotes_data[row_id] != footnotes_data.get(row_id):
                updated_footnotes[row_id] = footnotes_data.get(row_id)
                logger.debug(f"Footnote changed for row_id={row_id}")

        for row_id, text in updated_footnotes.items():
            # row_id is already the database ID - no need to look up in color_id_list
            logger.debug(f"Saving footnote: row_id={row_id}, text preview={text[:50] if text else 'empty'}...")
            save_footnote_to_database(verse_ref or verse_id_full, row_id, row_id, text)

    ############### END POST EDIT

    query = request.GET.get('q')
    book = request.GET.get('book')
    chapter_num = request.GET.get('chapter')
    verse_num = request.GET.get('verse')
    page_title = f'{book} {chapter_num}:{verse_num}'
    slt_flag = False
    rbt = None
    footnote_contents: list[str] = []
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
        has_lxx_column = table_has_column('old_testament', 'hebrewdata', 'lxx')
        base_columns = (
            "id, Ref, Eng, Heb1, Heb2, Heb3, Heb4, Heb5, Heb6, morph, uniq, Strongs, color, html, "
            "heb1_n, heb2_n, heb3_n, heb4_n, heb5_n, heb6_n, combined_heb, combined_heb_niqqud, footnote, morphology"
        )
        select_columns = base_columns + ", lxx" if has_lxx_column else base_columns

        rows_data = execute_query(
            f"""
            SELECT {select_columns}
            FROM old_testament.hebrewdata
            WHERE Ref LIKE %s
            ORDER BY Ref ASC;
            """,
            (f'{rbt_heb_ref}%',),
            fetch='all'
        )

        # Fetch html rows - sort by verse number numerically
        html_rows = execute_query(
            """
            SELECT Ref, html 
            FROM old_testament.hebrewdata 
            WHERE Ref LIKE %s 
            ORDER BY 
                CAST(SPLIT_PART(SPLIT_PART(Ref, '.', 3), '-', 1) AS INTEGER) ASC
            """,
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
        strong_rows, english_rows, hebrew_rows, morph_rows, hebrew_clean, interlinear_cards = build_heb_interlinear(rows_data)
    
        # Reverse the order 
        strong_rows.reverse()
        english_rows.reverse()
        hebrew_rows.reverse()
        #morph_rows.reverse()

        strong_row = '<tr class="strongs">' + ''.join(strong_rows) + '</tr>'
        english_row = '<tr class="eng_reader">' + ''.join(english_rows) + '</tr>'
        hebrew_row = '<tr class="hebrew_reader">' + ''.join(hebrew_rows) + '</tr>'
        #morph_row = '<tr class="morph_reader" style="word-wrap: break-word;">' + ''.join(morph_rows) + '</tr>'
        hebrew_clean = '<p><font style="font-size: 26px;">' + ' '.join(hebrew_clean) + '</font></p><p>' + ''.join(hebrew_clean) + '</p>'

        # strip niqqud from hebrew
        niqqud_pattern = '[\u0591-\u05BD\u05BF\u05C1-\u05C5\u05C7]'
        dash_pattern = '־'
        hebrew_row = re.sub(niqqud_pattern + '|' + dash_pattern, '', hebrew_row)

        raw_cards = interlinear_cards or []
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

        ######### EDIT TABLE / ENGLISH READER
        edit_table_data = []
        english_verse = []
        footnote_num = 1

        for row_data in rows_data:
            # Handle both old (24 columns) and new (25 columns with lxx) format
            # Convert RowType to a concrete tuple to avoid structural unpacking errors
            row = tuple(row_data)
            if len(row) >= 25:
                id = row[0]
                ref = row[1]
                eng = row[2]
                heb1 = row[3]
                heb2 = row[4]
                heb3 = row[5]
                heb4 = row[6]
                heb5 = row[7]
                heb6 = row[8]
                morph = row[9]
                unique = row[10]
                strongs = row[11]
                color = row[12]
                html_list = row[13]
                heb1_n = row[14]
                heb2_n = row[15]
                heb3_n = row[16]
                heb4_n = row[17]
                heb5_n = row[18]
                heb6_n = row[19]
                combined_heb = row[20]
                combined_heb_niqqud = row[21]
                footnote = row[22]
                morphology = row[23]

            else:
                # Pad to expected size to safely index missing fields
                padded = list(row) + [None] * (24 - len(row))
                id = padded[0]
                ref = padded[1]
                eng = padded[2]
                heb1 = padded[3]
                heb2 = padded[4]
                heb3 = padded[5]
                heb4 = padded[6]
                heb5 = padded[7]
                heb6 = padded[8]
                morph = padded[9]
                unique = padded[10]
                strongs = padded[11]
                color = padded[12]
                html_list = padded[13]
                heb1_n = padded[14]
                heb2_n = padded[15]
                heb3_n = padded[16]
                heb4_n = padded[17]
                heb5_n = padded[18]
                heb6_n = padded[19]
                combined_heb = padded[20]
                combined_heb_niqqud = padded[21]
                footnote = padded[22]
                morphology = padded[23]

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
    

            strong_refs = []
            strongs_exhaustive_list = []

            # Ensure 'strongs' is a usable string before splitting to avoid AttributeError when it's None.
            if strongs:
                parts = strongs.split('/')
                for part in parts:
                    subparts = re.split(r'[=«]', part)
                    for subpart in subparts:
                        if subpart and subpart.startswith('H'):
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
            else:
                # Ensure variable is defined for templates even when there are no Strongs
                formatted_strongs_list = ''

            morph_color = ""
            # Determine the color based on the presence of 'f' or 'm'
            if isinstance(morph, str) and 'f' in morph:
                morph_color = 'style="color: #FF1493;"'
            elif isinstance(morph, str) and 'm' in morph:
                morph_color = 'style="color: blue;"'
            
            morph_display = f'<input type="hidden" id="code" value="{morph}"/><div {morph_color}>{morphology}</div>'

            
            morphology_raw = morphology or ''
                
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
                color = f"<select name=\"color\" autocomplete=\"off\">\n                    <option name=\"color\" value=\"m\" selected>masc</option>\n                    <option name=\"color\" value=\"f\">fem</option>\n                    <option name=\"color\" value=\"0\">none</option>\n                    </select>\n                    <input type=\"hidden\" name=\"color_old\" value=\"{color_old}\">\n                    <input type=\"hidden\" name=\"color_id\" value=\"{id}\">"
            elif color =='f':
                color_old = 'f'
                color = f"<select name=\"color\" autocomplete=\"off\">\n                    <option name=\"color\" value=\"m\">masc</option>\n                    <option name=\"color\" value=\"f\" selected>fem</option>\n                    <option name=\"color\" value=\"0\">none</option>\n                    </select>\n                    <input type=\"hidden\" name=\"color_old\" value=\"{color_old}\">\n                    <input type=\"hidden\" name=\"color_id\" value=\"{id}\">"
            else:
                color_old = '0'
                color = f"<select name=\"color\" autocomplete=\"off\">\n                    <option name=\"color\" value=\"m\">masc</option>\n                    <option name=\"color\" value=\"f\">fem</option>\n                    <option name=\"color\" value=\"0\" selected>none</option>\n                    </select>\n                    <input type=\"hidden\" name=\"color_old\" value=\"{color_old}\">\n                    <input type=\"hidden\" name=\"color_id\" value=\"{id}\">"

            # Use the database row ID for footnote field names (not sequential number)
            # This ensures correct mapping after edit_table_data is sorted
            row_id_str = str(id)

            if footnote:
                footnote_btn = f'''
                    <button class="toggleButton" data-target="footnotes-{row_id_str}" type="button" style="
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


                foot_ref = ref.replace(".", "-") # type: ignore
                footnote = f'''
                <td colspan="14" class="footnotes-{row_id_str}" style="display: none;">
                    {footnote}<br>
                    <textarea class="my-tinymce" name="footnote-{row_id_str}" id="footnote-{row_id_str}" autocomplete="off" style="width: 100%;" rows="6">{footnote}</textarea><br>
                    <input type="hidden" name="old_footnote-{row_id_str}" value="does not work">
                    &lt;a class=&quot;sdfootnoteanc&quot; href=&quot;?footnote={foot_ref}&quot;&gt;&lt;sup&gt;num&lt;/sup&gt;&lt;/a&gt;
                </td>
                '''

            else:
                footnote_btn = f'''
                    <button class="toggleButton" data-target="footnotes-{row_id_str}" type="button" style="
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

                foot_ref = ref.replace(".", "-") # type: ignore
                footnote = f'''
                <td colspan="14" class="footnotes-{row_id_str}" style="display: none;">
                    No footnote<br>
                    <textarea class="my-tinymce" name="footnote-{row_id_str}" id="footnote-{row_id_str}" autocomplete="off" style="width: 100%;" rows="6"></textarea><br>
                    <input type="hidden" name="old_footnote-{row_id_str}" value="">
                </td>
                '''
            # Append all data to edit_table_data
            edit_table_data.append((id, ref, eng, unique, combined_hebrew, color, search_count, search_count2, strongs, formatted_strongs_list, morph, combined_heb_niqqud, combined_heb, footnote_btn, footnote, morphology_raw, morph_display))
            
            footnote_num += 1  # Keep for display purposes if needed elsewhere

        edit_table_data.sort(
            key=lambda row: row[0] if row[0] is not None else -1
        )

        english_verse = ' '.join(filter(None, english_verse))
        english_verse = english_verse.replace("אֵת- ", "אֵת-")

    
        if html is not None:
            english_reader = html
        else:
            english_reader = english_verse

        notes_rows: list[str] = []

        if book == "Genesis" and footnote_contents:
            notes_rows = footnote_contents
        else:
            html_sources: list[str] = []
            if html:
                html_sources.append(html)

            html_sources.extend([
                row[13]
                for row in rows_data
                if len(row) > 13 and row[13]
            ])

            if english_reader:
                html_sources.append(english_reader)

            book_for_notes = book or 'Genesis'
            notes_rows = collect_footnote_rows(html_sources, book_for_notes, chapter_num, verse_num)

        notes_html = ''
        if notes_rows:
            merged_rows = ''.join(notes_rows)
            merged_rows = merged_rows.replace('?footnote=', '../edit_footnote/?footnote=')
            notes_html = f'<table class="notes-table"><tbody>{merged_rows}</tbody></table>'

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
                'smith': smith,
                'notes_html': notes_html,
                'hebrew_interlinear_cards': hebrew_cards,
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
                    SELECT id, Ref, Eng, heb6_n, heb5_n, heb4_n, heb3_n, heb2_n, heb1_n, morphology
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
                    yield f"Updated {eng} in {ref} with <b>{translation}</b> from <span style='font-size: larger; color: orange;'>{hebrew_construct}</span> for {strongs_number}.<br>".encode('utf-8')

                    #print(f"Updated {eng} in {ref} with {translation} from {hebrew_construct} for {strongs_number}.")


                # After all updates are done, yield a completion message
                yield "<b>Update process completed.</b>".encode('utf-8')
            
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
                    bookref = _safe_book_name(bookref) or bookref
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
                    bookref = _safe_book_name(bookref) or bookref
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
                    bookref = _safe_book_name(bookref) or bookref
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
                    bookref = _safe_book_name(bookref) or bookref
                    bookref = bookref.lower()
                    bookref = bookref.replace(' ', '_')
                    verse1 = verse[:-3]
                    verse = verse1[4:]
                    verse = verse.replace('.', '-')
                    link = f'<a href="https://biblehub.com/{bookref}/{verse}.htm">{verse1}</a>'
                    links.append(link)


        # if individual book is searched convert the full to the abbrev
        if book not in ['NT', 'OT', 'all']:
            book2 = _safe_book_name(book) or book
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

    if request.method == 'POST':
        find_text = request.POST.get('find_text')
        replace_text = request.POST.get('replace_text')
        exact_match = request.POST.get('exact_match')  # Get checkbox value

        # Handle approved replacements
        if 'approve_replacements' in request.POST:
            approved_replacements = request.POST.getlist('approve_replacements')
            successful_replacements = 0

            for verse_id in approved_replacements:
                new_text = request.POST.get(f'new_text_{verse_id}')
                if new_text is None:
                    continue

                execute_query(
                    "UPDATE new_testament.nt SET rbt = %s WHERE verseID = %s;",
                    (new_text, verse_id)
                )

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

            replacements: list[dict[str, str | int]] = []
            genesis_replacements: list[dict[str, str | int]] = []

            # Create regex pattern based on exact_match checkbox
            if exact_match:
                # Use word boundaries for exact matching
                search_pattern = r'\b' + re.escape(find_text) + r'\b'
            else:
                # Use simple text matching (case-sensitive)
                search_pattern = re.escape(find_text)

            for verse_id, book, chapter, startVerse, old_text in rows:
                # Check if pattern matches in the text
                if not re.search(search_pattern, old_text):
                    continue

                book_name = _safe_book_name(book)
                
                # Create the new text without replacement (for database)
                new_text_raw = re.sub(search_pattern, replace_text, old_text)
                
                # Create display version with highlighting
                # Use a function to highlight all matches properly
                def highlight_matches(match):
                    return f'<span class="highlight-find">{match.group(0)}</span>'
                
                display_old = re.sub(search_pattern, highlight_matches, old_text)
                
                # For the "after" preview, show old text with replace highlighted
                def highlight_replacement(match):
                    return f'<span class="highlight-replace">{replace_text}</span>'
                
                display_new = re.sub(search_pattern, highlight_replacement, old_text)
                
                verse_link = f'../edit/?book={book_name}&chapter={chapter}&verse={startVerse}'

                # This condition should always be true if we found a match above
                if new_text_raw != old_text:
                    replacements.append({
                        'verse_id': verse_id,
                        'old_text': display_old,
                        'new_text': display_new,
                        'new_text_raw': new_text_raw,
                        'verse_link': verse_link
                    })

            if not replacements:
                context['edit_result'] = '<div class="notice-bar"><p>No matches found for the given word.</p></div>'
                return render(request, 'find_replace.html', context)

            context['replacements'] = replacements
            return render(request, 'find_replace_review.html', context)

    return render(request, 'find_replace.html', context)

@login_required
def find_and_replace_ot(request):
    context = {}
    
    def build_search_pattern(term: str, exact: bool = False):
        if not term:
            return None
        escaped = re.escape(term)
        if exact:
            return re.compile(rf'(?<!\w){escaped}(?!\w)')
        return re.compile(escaped)

    def highlight_html(text: str, pattern: re.Pattern, css_class: str) -> str:
        if text is None:
            return ''

        def _replacer(match):
            return f'<span class="highlight-{css_class}">{match.group(0)}</span>'

        return pattern.sub(_replacer, text)

    if request.method == 'POST':
        find_text = (request.POST.get('find_text') or '').strip()
        replace_text = (request.POST.get('replace_text') or '').strip()
        exact_match = request.POST.get('exact_match') == 'on'
        skip_rbt_html = request.POST.get('skip_rbt_html') == 'on'
        target_footnotes = request.POST.get('target_footnotes') == 'on'
        genesis_find_text = (request.POST.get('genesis_find_text') or '').strip()
        genesis_replace_text = (request.POST.get('genesis_replace_text') or '').strip()
        genesis_exact_match = request.POST.get('genesis_exact_match') == 'on'

        context.update({
            'find_text': find_text,
            'replace_text': replace_text,
            'exact_match': exact_match,
            'skip_rbt_html': skip_rbt_html,
            'target_footnotes': target_footnotes,
            'genesis_find_text': genesis_find_text,
            'genesis_replace_text': genesis_replace_text,
            'genesis_exact_match': genesis_exact_match
        })

        form_type = request.POST.get('form_type', 'ot')

        logger.debug(
            "OT find/replace submission: find='%s', replace='%s', exact=%s, skip_html=%s, target_footnotes=%s",
            find_text,
            replace_text,
            exact_match,
            skip_rbt_html,
            target_footnotes
        )

        if 'approve_replacements' in request.POST:
            approved_replacements = request.POST.getlist('approve_replacements')

            if not approved_replacements:
                context['edit_result'] = '<div class="notice-bar"><p>No replacements selected.</p></div>'
                return render(request, 'find_replace_ot.html', context)

            replacements_key = request.POST.get('replacements_key')
            payload = cache.get(replacements_key) if replacements_key else None

            if not payload:
                context['edit_result'] = '<div class="notice-bar"><p>Review has expired. Please re-run the search.</p></div>'
                return render(request, 'find_replace_ot.html', context)

            replacements_data = {
                item['record_key']: item
                for item in payload.get('replacements', [])
            }

            successful_replacements = 0

            for record_key in approved_replacements:
                record_data = replacements_data.get(record_key)

                if not record_data:
                    continue

                new_text = record_data.get('new_text_raw')
                new_paraphrase = record_data.get('new_paraphrase_raw')
                new_footnote = record_data.get('new_footnote_raw')

                if new_text is None and new_paraphrase is None and new_footnote is None:
                    continue

                source, record_id = record_key.split('-', 1)

                if source == 'genesis':
                    update_kwargs = {}
                    if new_text is not None:
                        update_kwargs['html'] = new_text
                    if new_paraphrase is not None:
                        update_kwargs['rbt_reader'] = new_paraphrase

                    if update_kwargs:
                        Genesis.objects.filter(id=int(record_id)).update(**update_kwargs)
                        successful_replacements += 1
                elif source == 'footnote':
                    if new_footnote is None:
                        continue
                    execute_query("SET search_path TO old_testament;")
                    
                    # Get the ref for this hebrewdata row to clear cache
                    ref_row = execute_query(
                        "SELECT Ref FROM old_testament.hebrewdata WHERE id = %s;",
                        (int(record_id),),
                        fetch='one'
                    )
                    
                    execute_query(
                        "UPDATE old_testament.hebrewdata SET footnote = %s WHERE id = %s;",
                        (new_footnote, int(record_id))
                    )
                    
                    # Clear cache for this verse
                    if ref_row:
                        verse_ref = ref_row[0]
                        if verse_ref:
                            # Parse Gen.1.1-01 format
                            parts = verse_ref.split('.')
                            if len(parts) >= 3:
                                book_code = parts[0]
                                chapter_value = parts[1]
                                verse_value = parts[2].split('-')[0]
                                book_name = convert_book_name(book_code) or book_code
                                _invalidate_reader_cache(book_name, chapter_value, verse_value)
                    
                    successful_replacements += 1
                elif source == 'genesisfootnote':
                    if new_footnote is None:
                        continue

                    footnote_info = GenesisFootnotes.objects.filter(id=int(record_id)).values('footnote_id').first()
                    GenesisFootnotes.objects.filter(id=int(record_id)).update(footnote_html=new_footnote)

                    if footnote_info:
                        footnote_id_value = footnote_info.get('footnote_id') or ''
                        parts = footnote_id_value.split('-')
                        if len(parts) >= 2:
                            chapter_value = parts[0]
                            verse_value = parts[1]
                            _invalidate_reader_cache('Genesis', chapter_value, verse_value)

                    successful_replacements += 1
                else:
                    if new_text is None:
                        continue
                    execute_query("SET search_path TO old_testament;")
                    execute_query(
                        "UPDATE old_testament.ot SET html = %s WHERE id = %s;",
                        (new_text, int(record_id))
                    )
                    successful_replacements += 1

            if replacements_key:
                cache.delete(replacements_key)

            context['edit_result'] = (
                f'<div class="notice-bar">'
                f'<p><span class="icon"><i class="fas fa-check-circle"></i></span>'
                f'{successful_replacements} replacements successfully applied!</p>'
                f'</div>'
            )

            return render(request, 'find_replace_ot.html', context)

        elif form_type == 'genesis_footnotes':
            if not genesis_find_text or not genesis_replace_text:
                context['edit_result'] = '<div class="notice-bar"><p>Please provide both the word and the replacement.</p></div>'
                return render(request, 'find_replace_ot.html', context)

            search_pattern = build_search_pattern(genesis_find_text, genesis_exact_match)
            if not search_pattern:
                context['edit_result'] = '<div class="notice-bar"><p>Enter a valid word to search.</p></div>'
                return render(request, 'find_replace_ot.html', context)

            display_replace_pattern = re.compile(re.escape(genesis_replace_text)) if genesis_replace_text else None

            replacements = []
            footnote_rows = list(
                GenesisFootnotes.objects.filter(footnote_html__icontains=genesis_find_text)
                .values('id', 'footnote_id', 'footnote_html')
            )
            logger.debug("Genesis footnote candidates returned: %d", len(footnote_rows))

            for row in footnote_rows:
                footnote_text = row.get('footnote_html') or ''
                new_footnote_raw, replacements_count = search_pattern.subn(genesis_replace_text, footnote_text)

                if replacements_count == 0:
                    continue

                highlighted_old = highlight_html(footnote_text, search_pattern, 'find')
                if display_replace_pattern:
                    highlighted_new = highlight_html(new_footnote_raw, display_replace_pattern, 'replace')
                else:
                    highlighted_new = new_footnote_raw

                footnote_id = row.get('footnote_id') or ''
                parts = footnote_id.split('-') if footnote_id else []
                chapter_ref = parts[0] if len(parts) >= 1 and parts[0] else None
                verse_ref = parts[1] if len(parts) >= 2 and parts[1] else None
                verse_link = '../edit/?book=Genesis'
                if chapter_ref and verse_ref:
                    verse_link = f'../edit/?book=Genesis&chapter={chapter_ref}&verse={verse_ref}'

                reference_label = footnote_id or f'Genesis footnote #{row["id"]}'
                if chapter_ref and verse_ref:
                    reference_label = f'Genesis {chapter_ref}:{verse_ref} (footnote {footnote_id})'

                replacements.append({
                    'record_key': f'genesisfootnote-{row["id"]}',
                    'reference': reference_label,
                    'old_text_display': highlighted_old,
                    'new_text_display': highlighted_new,
                    'old_text_raw': '',
                    'new_text_raw': '',
                    'old_paraphrase_raw': '',
                    'new_paraphrase_raw': '',
                    'old_footnote_raw': footnote_text,
                    'new_footnote_raw': new_footnote_raw,
                    'verse_link': verse_link
                })

            if not replacements:
                context['edit_result'] = '<div class="notice-bar"><p>No Genesis footnotes matched the given word.</p></div>'
                return render(request, 'find_replace_ot.html', context)

            review_key = f"find_replace_ot_{request.user.id or 'anon'}_{uuid.uuid4().hex}"
            cache.set(review_key, {'replacements': replacements}, timeout=600)

            context['replacements'] = replacements
            context['form_type'] = 'genesis_footnotes'
            context['replacements_key'] = review_key
            logger.debug("Prepared %d Genesis footnote replacement previews", len(replacements))
            return render(request, 'find_replace_review_ot.html', context)

        elif find_text and replace_text:
            search_pattern = build_search_pattern(find_text, exact_match)
            if not search_pattern:
                context['edit_result'] = '<div class="notice-bar"><p>Enter a valid word to search.</p></div>'
                return render(request, 'find_replace_ot.html', context)

            display_replace_pattern = re.compile(re.escape(replace_text)) if replace_text else None

            execute_query("SET search_path TO old_testament;")
            
            replacements = []
            genesis_replacements = []
            
            # If targeting footnotes, query hebrewdata footnote column instead
            if target_footnotes:
                footnote_rows = execute_query(
                    "SELECT id, Ref, footnote FROM old_testament.hebrewdata WHERE footnote IS NOT NULL AND footnote LIKE %s;",
                    (f'%{find_text}%',),
                    fetch='all'
                )
                
                logger.debug("Hebrewdata footnote candidates returned: %d", len(footnote_rows))
                logger.debug("Search pattern: %s", search_pattern.pattern if search_pattern else 'None')
                
                for row_id, ref, footnote_text in footnote_rows:
                    if not footnote_text:
                        continue
                    
                    # For footnotes with HTML, use simple string replacement instead of regex
                    # to avoid issues with escaped characters in patterns
                    if exact_match:
                        # For exact match, ensure word boundaries (use regex)
                        highlighted_old = highlight_html(footnote_text, search_pattern, 'find')
                        new_footnote_raw, replacements_count = search_pattern.subn(replace_text, footnote_text)
                    else:
                        # For non-exact match with HTML content, use simple string replace
                        replacements_count = footnote_text.count(find_text)
                        if replacements_count > 0:
                            new_footnote_raw = footnote_text.replace(find_text, replace_text)
                            # Highlight using simple string patterns
                            highlighted_old = footnote_text.replace(find_text, f'<span class="highlight-find">{find_text}</span>')
                        else:
                            new_footnote_raw = footnote_text
                    
                    if replacements_count == 0:
                        logger.debug("Ref %s: LIKE matched but no replacements found", ref)
                        logger.debug("Find text: %r", find_text)
                        logger.debug("Footnote preview: %s", footnote_text[:300])
                        continue
                    
                    if display_replace_pattern and not exact_match:
                        # For non-exact match, use simple string highlighting
                        highlighted_new = new_footnote_raw.replace(replace_text, f'<span class="highlight-replace">{replace_text}</span>')
                    elif display_replace_pattern:
                        highlighted_new = highlight_html(new_footnote_raw, display_replace_pattern, 'replace')
                    else:
                        highlighted_new = new_footnote_raw
                    
                    # Parse ref to get book/chapter/verse for link
                    parts = ref.split('.')
                    if len(parts) >= 3:
                        book_code = parts[0]
                        chapter_ref = parts[1]
                        verse_ref = parts[2].split('-')[0]
                        book_display = convert_book_name(book_code) or book_code
                        
                        verse_link = f'../translate/?book={book_display}&chapter={chapter_ref}&verse={verse_ref}'
                        reference_label = f'{book_display} {chapter_ref}:{verse_ref} (footnote)'
                        record_key = f'footnote-{row_id}'
                        
                        replacements.append({
                            'record_key': record_key,
                            'reference': reference_label,
                            'old_text_display': highlighted_old,
                            'new_text_display': highlighted_new,
                            'old_footnote_raw': footnote_text,
                            'new_footnote_raw': new_footnote_raw,
                            'old_text_raw': '',
                            'new_text_raw': '',
                            'old_paraphrase_raw': '',
                            'new_paraphrase_raw': '',
                            'verse_link': verse_link
                        })
            else:
                # Original OT table query
                rows = execute_query(
                    "SELECT id, Ref, html, book, chapter, verse FROM old_testament.ot WHERE html LIKE %s;",
                    (f'%{find_text}%',),
                    fetch='all'
                )

                logger.debug("OT table candidates returned: %d", len(rows))

                file_name_pattern = r'\b\w+\.\w+\b'

                for verse_id, ref, ot_html, book, chapter, verse in rows:
                    working_html = ot_html or ''
                    source = 'ot'
                    record_key = f'ot-{verse_id}'
                    try:
                        chapter_ref = int(chapter) if chapter is not None else None
                    except (TypeError, ValueError):
                        chapter_ref = None
                    try:
                        verse_ref = int(verse) if verse is not None else None
                    except (TypeError, ValueError):
                        verse_ref = None
                    book_display = _safe_book_name(book)

                    if book_display == 'Genesis':
                        logger.debug(
                            "Skipping OT row id=%s for Genesis, will use ORM data", verse_id
                        )
                        continue

                    if re.search(file_name_pattern, working_html):
                        continue

                    if not search_pattern.search(working_html):
                        continue

                    highlighted_old = highlight_html(working_html, search_pattern, 'find')
                    new_text_raw, replacements_count = search_pattern.subn(replace_text, working_html)

                    if replacements_count == 0:
                        continue

                    if display_replace_pattern:
                        highlighted_new = highlight_html(new_text_raw, display_replace_pattern, 'replace')
                    else:
                        highlighted_new = new_text_raw

                    verse_link = (
                        f'../edit/?book=Genesis&chapter={chapter_ref}&verse={verse_ref}'
                        if source == 'genesis'
                        else f'../translate/?book={book}&chapter={chapter_ref}&verse={verse_ref}'
                    )

                    reference_label = ref or f'{book_display} {chapter_ref}:{verse_ref}'

                    replacements.append({
                        'record_key': record_key,
                        'reference': reference_label,
                        'old_text_display': highlighted_old,
                        'new_text_display': highlighted_new,
                        'old_text_raw': working_html,
                        'new_text_raw': new_text_raw,
                        'old_paraphrase_raw': '',
                        'new_paraphrase_raw': '',
                        'verse_link': verse_link
                    })

                genesis_rows = list(
                    Genesis.objects.filter(
                        Q(html__icontains=find_text) | Q(rbt_reader__icontains=find_text)
                    ).values('id', 'chapter', 'verse', 'html', 'rbt_reader')
                )
                logger.debug("Genesis candidates returned: %d", len(genesis_rows))

                for row in genesis_rows:
                    html_text = row.get('html') or ''
                    paraphrase_text = row.get('rbt_reader') or ''

                    if re.search(file_name_pattern, html_text) and not skip_rbt_html:
                        logger.debug(
                            "Skipping Genesis id=%s due to file-like pattern", row.get('id')
                        )
                        continue

                    html_new = html_text
                    html_count = 0
                    if not skip_rbt_html and html_text:
                        html_new, html_count = search_pattern.subn(replace_text, html_text)

                    paraphrase_new, paraphrase_count = search_pattern.subn(replace_text, paraphrase_text)

                    total_matches = html_count + paraphrase_count
                    if total_matches == 0:
                        logger.debug(
                            "Genesis id=%s pattern found zero replacements in html/paraphrase",
                            row.get('id')
                        )
                        continue

                    highlighted_html_old = ''
                    highlighted_html_new = ''
                    if not skip_rbt_html and html_text:
                        highlighted_html_old = highlight_html(html_text, search_pattern, 'find')
                        highlighted_html_new = (
                            highlight_html(html_new, display_replace_pattern, 'replace')
                            if display_replace_pattern else escape(html_new)
                        )

                    highlighted_para_old = ''
                    highlighted_para_new = ''
                    if paraphrase_text:
                        highlighted_para_old = highlight_html(paraphrase_text, search_pattern, 'find')
                        highlighted_para_new = (
                            highlight_html(paraphrase_new, display_replace_pattern, 'replace')
                            if display_replace_pattern else escape(paraphrase_new)
                        )

                    def format_section(label: str, content: str) -> str:
                        if not content:
                            return ''
                        return f'<div class="genesis-field"><strong>{label}:</strong><div>{content}</div></div>'

                    combined_old_display = (
                        format_section('HTML', highlighted_html_old) +
                        format_section('Paraphrase', highlighted_para_old)
                    ) or '<em>No content</em>'

                    combined_new_display = (
                        format_section('HTML', highlighted_html_new) +
                        format_section('Paraphrase', highlighted_para_new)
                    ) or '<em>No content</em>'

                    chapter_ref = row.get('chapter')
                    verse_ref = row.get('verse')

                    verse_link = f"../edit/?book=Genesis&chapter={chapter_ref}&verse={verse_ref}"
                    reference_label = f"Genesis {chapter_ref}:{verse_ref}"
                    record_key = f"genesis-{row['id']}"

                    logger.debug(
                        "Queued Genesis replacement: record_key=%s matches=%d",
                        record_key,
                        total_matches
                    )

                    genesis_replacements.append({
                        'record_key': record_key,
                        'reference': reference_label,
                        'old_text_display': combined_old_display,
                        'new_text_display': combined_new_display,
                        'old_text_raw': html_text,
                        'new_text_raw': html_new,
                        'old_paraphrase_raw': paraphrase_text,
                        'new_paraphrase_raw': paraphrase_new,
                        'verse_link': verse_link
                    })

                replacements = genesis_replacements + replacements

            if not replacements:
                context['edit_result'] = '<div class="notice-bar"><p>No matches found for the given word.</p></div>'
                logger.info("OT find/replace: no matches found for '%s'", find_text)
                return render(request, 'find_replace_ot.html', context)

            review_key = f"find_replace_ot_{request.user.id or 'anon'}_{uuid.uuid4().hex}"
            cache.set(review_key, {'replacements': replacements}, timeout=600)

            context['replacements'] = replacements
            context['form_type'] = 'ot'
            context['replacements_key'] = review_key
            logger.debug("Prepared %d replacement previews", len(replacements))

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

def get_aseneth_story():
    """Return the entire Joseph and Aseneth story ordered by chapter and verse."""
    try:
        with get_db_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SET search_path TO joseph_aseneth")
            cursor.execute(
                """
                SELECT id, book, chapter, verse, english
                FROM aseneth
                ORDER BY chapter, verse
                """
            )
            rows = cursor.fetchall()
    except psycopg2.Error as exc:
        raise

    story = []
    for row in rows:
        record_id, book, chapter, verse, english = row
        story.append({
            'id': record_id,
            'book': book or 'He Adds and Storehouse',
            'chapter': chapter,
            'verse': verse,
            'english': english or ''
        })
    return story


def build_exact_match_pattern(term):
    """Create a regex pattern that matches the exact term as a standalone word/phrase."""
    if not term:
        return None
    escaped = re.escape(term)
    return re.compile(rf'(?<!\w){escaped}(?!\w)')


def highlight_matches(text, pattern, css_class):
    """Return HTML string with matched segments wrapped in <mark> tags."""
    if not text:
        return ''
    if not pattern:
        return escape(text)

    parts = []
    last_index = 0
    for match in pattern.finditer(text):
        start, end = match.span()
        parts.append(escape(text[last_index:start]))
        parts.append(f'<mark class="{css_class}">{escape(match.group(0))}</mark>')
        last_index = end
    parts.append(escape(text[last_index:]))
    return ''.join(parts)


@login_required
def edit_aseneth(request):
    """
    Edit view for Joseph and Aseneth translation database.
    Handles viewing and editing verses from the Joseph_Aseneth schema.
    """
    book_name = "He Adds and Storehouse"
    chapter_query = request.GET.get('chapter')
    verse_query = request.GET.get('verse')

    if request.method == 'POST':
        action = request.POST.get('action')

        if action in {'preview', 'confirm', 'back'}:
            find_text = (request.POST.get('find_text') or '').strip()
            replace_text = (request.POST.get('replace_text') or '').strip()

            if action == 'back':
                try:
                    story = get_aseneth_story()
                except psycopg2.Error as exc:
                    messages.error(request, f"Unable to load Joseph and Aseneth story: {exc}")
                    story = []

                context = {
                    'book': book_name,
                    'story': story,
                    'find_text': find_text,
                    'replace_text': replace_text
                }
                return render(request, 'edit_aseneth_input.html', context)

            if action == 'preview':
                if not find_text or not replace_text:
                    messages.error(request, "Both find and replace values are required.")
                    try:
                        story = get_aseneth_story()
                    except psycopg2.Error as exc:
                        messages.error(request, f"Unable to load Joseph and Aseneth story: {exc}")
                        story = []

                    context = {
                        'book': book_name,
                        'story': story,
                        'find_text': find_text,
                        'replace_text': replace_text
                    }
                    return render(request, 'edit_aseneth_input.html', context)

                try:
                    story = get_aseneth_story()
                except psycopg2.Error as exc:
                    messages.error(request, f"Unable to load Joseph and Aseneth story: {exc}")
                    story = []
                    context = {
                        'book': book_name,
                        'story': story,
                        'find_text': find_text,
                        'replace_text': replace_text
                    }
                    return render(request, 'edit_aseneth_input.html', context)

                find_pattern = build_exact_match_pattern(find_text)
                replacement_pattern = build_exact_match_pattern(replace_text)

                if not find_pattern:
                    messages.error(request, "Enter a valid term to find.")
                    context = {
                        'book': book_name,
                        'story': story,
                        'find_text': find_text,
                        'replace_text': replace_text
                    }
                    return render(request, 'edit_aseneth_input.html', context)

                updates = []
                preview_rows = []
                total_matches = 0

                for row in story:
                    english_text = row['english'] or ''
                    updated_text, replacements = find_pattern.subn(replace_text, english_text)
                    if replacements:
                        total_matches += replacements
                        updates.append({
                            'id': row['id'],
                            'chapter': row['chapter'],
                            'verse': row['verse'],
                            'old_text': english_text,
                            'new_text': updated_text,
                            'count': replacements
                        })

                        preview_rows.append({
                            'id': row['id'],
                            'chapter': row['chapter'],
                            'verse': row['verse'],
                            'original_highlight': highlight_matches(english_text, find_pattern, 'highlight-original'),
                            'updated_highlight': highlight_matches(updated_text, replacement_pattern, 'highlight-updated') if replacement_pattern else escape(updated_text)
                        })

                if not updates:
                    messages.info(request, f"No exact matches for '{find_text}' were found in the story.")
                    context = {
                        'book': book_name,
                        'story': story,
                        'find_text': find_text,
                        'replace_text': replace_text
                    }
                    return render(request, 'edit_aseneth_input.html', context)

                updates_json = json.dumps(updates)

                context = {
                    'book': book_name,
                    'find_text': find_text,
                    'replace_text': replace_text,
                    'total_matches': total_matches,
                    'affected_count': len(updates),
                    'preview_rows': preview_rows,
                    'updates_json': quote(updates_json)
                }
                return render(request, 'edit_aseneth_review.html', context)

            if action == 'confirm':
                updates_payload = request.POST.get('updates_json', '')
                if not updates_payload:
                    messages.error(request, "Missing update payload; please run the find and replace again.")
                    try:
                        story = get_aseneth_story()
                    except psycopg2.Error as exc:
                        messages.error(request, f"Unable to load Joseph and Aseneth story: {exc}")
                        story = []
                    context = {
                        'book': book_name,
                        'story': story,
                        'find_text': find_text,
                        'replace_text': replace_text
                    }
                    return render(request, 'edit_aseneth_input.html', context)

                try:
                    updates = json.loads(unquote(updates_payload))
                except json.JSONDecodeError:
                    messages.error(request, "Could not read replacement preview; please try again.")
                    try:
                        story = get_aseneth_story()
                    except psycopg2.Error as exc:
                        messages.error(request, f"Unable to load Joseph and Aseneth story: {exc}")
                        story = []
                    context = {
                        'book': book_name,
                        'story': story,
                        'find_text': find_text,
                        'replace_text': replace_text
                    }
                    return render(request, 'edit_aseneth_input.html', context)

                if not updates:
                    messages.info(request, "No replacements to apply.")
                    try:
                        story = get_aseneth_story()
                    except psycopg2.Error as exc:
                        messages.error(request, f"Unable to load Joseph and Aseneth story: {exc}")
                        story = []
                    context = {
                        'book': book_name,
                        'story': story,
                        'find_text': find_text,
                        'replace_text': replace_text
                    }
                    return render(request, 'edit_aseneth_input.html', context)

                try:
                    with get_db_connection() as conn:
                        cursor = conn.cursor()
                        cursor.execute("SET search_path TO joseph_aseneth")
                        for item in updates:
                            cursor.execute(
                                "UPDATE aseneth SET english = %s WHERE id = %s",
                                (item['new_text'], item['id'])
                            )
                        conn.commit()
                except psycopg2.Error as exc:
                    messages.error(request, f"Database error while applying replacements: {exc}")
                    try:
                        story = get_aseneth_story()
                    except psycopg2.Error as story_exc:
                        messages.error(request, f"Unable to reload Joseph and Aseneth story: {story_exc}")
                        story = []
                    context = {
                        'book': book_name,
                        'story': story,
                        'find_text': find_text,
                        'replace_text': replace_text
                    }
                    return render(request, 'edit_aseneth_input.html', context)

                affected_chapters = set()
                for item in updates:
                    chapter_value = item.get('chapter')
                    verse_value = item.get('verse')
                    if chapter_value is not None and verse_value is not None:
                        cache.delete(f'aseneth_{chapter_value}_{verse_value}')
                        # Also invalidate the public storehouse chapter cache so the reader shows updates
                        cache.delete(f'storehouse_{chapter_value}_{INTERLINEAR_CACHE_VERSION}')
                        affected_chapters.add(chapter_value)
                for chapter_value in affected_chapters:
                    cache.delete(f'aseneth_{chapter_value}_None')
                    # Invalidate storehouse chapter cache as well
                    cache.delete(f'storehouse_{chapter_value}_{INTERLINEAR_CACHE_VERSION}')

                total_matches = sum(item.get('count', 0) for item in updates)

                try:
                    update_instance = TranslationUpdates(
                        date=datetime.now(),
                        version='Aseneth English Bulk',
                        reference=book_name,
                        update_text=f"Replaced '{find_text}' with '{replace_text}' in {len(updates)} verses ({total_matches} occurrences)."
                    )
                    update_instance.save()
                except Exception:
                    pass

                messages.success(
                    request,
                    f"Replaced '{find_text}' with '{replace_text}' in {len(updates)} verses ({total_matches} occurrences)."
                )

                try:
                    story = get_aseneth_story()
                except psycopg2.Error as exc:
                    messages.error(request, f"Unable to reload Joseph and Aseneth story: {exc}")
                    story = []

                context = {
                    'book': book_name,
                    'story': story,
                    'find_text': '',
                    'replace_text': ''
                }
                return render(request, 'edit_aseneth_input.html', context)

        edited_greek = request.POST.get('edited_greek')
        edited_english = request.POST.get('edited_english')
        record_id = request.POST.get('record_id')
        chapter_num = request.POST.get('chapter') or chapter_query
        verse_num = request.POST.get('verse') or verse_query
        verse_input = request.POST.get('verse_input')

        if verse_input:
            context = get_aseneth_context(chapter_num, verse_input)
            return render(request, 'edit_aseneth_verse.html', context)

        if record_id and (edited_greek or edited_english):
            try:
                with get_db_connection() as conn:
                    cursor = conn.cursor()
                    cursor.execute("SET search_path TO joseph_aseneth")

                    if edited_greek is not None:
                        cursor.execute("UPDATE aseneth SET greek = %s WHERE id = %s", (edited_greek.strip(), record_id))
                        version = 'Aseneth Greek'
                        update_text = edited_greek
                    elif edited_english is not None:
                        cursor.execute("UPDATE aseneth SET english = %s WHERE id = %s", (edited_english.strip(), record_id))
                        version = 'Aseneth English'
                        update_text = edited_english

                    conn.commit()

                    update_text = re.sub(r'<a\s+.*?>(.*?)</a>', r'\1', update_text)
                    update_instance = TranslationUpdates(
                        date=datetime.now(),
                        version=version,
                        reference=f"{book_name} {chapter_num}:{verse_num}",
                        update_text=update_text
                    )
                    update_instance.save()

                    cache_key_base_verse = f'aseneth_{chapter_num}_{verse_num}'
                    cache_key_base_chapter = f'aseneth_{chapter_num}_None'
                    cache.delete(cache_key_base_verse)
                    cache.delete(cache_key_base_chapter)
                    # Also clear the public reader cache for this chapter
                    cache.delete(f'storehouse_{chapter_num}_{INTERLINEAR_CACHE_VERSION}')

                    cache_string = f"Deleted Cache key: {cache_key_base_verse}, {cache_key_base_chapter}"

                    context = get_aseneth_context(chapter_num, verse_num)
                    context['edit_result'] = (
                        '<div class="notice-bar"><p><span class="icon"><i class="fas fa-check-circle"></i>'
                        '</span>Updated verse successfully! ' + cache_string + '</p></div>'
                    )

                    return render(request, 'edit_aseneth_verse.html', context)

            except psycopg2.Error as e:
                context = {
                    'error_message': f"Database error: {e}",
                    'chapter': chapter_num,
                    'verse': verse_num
                }
                return render(request, 'edit_aseneth_verse.html', context)

    if chapter_query and verse_query:
        context = get_aseneth_context(chapter_query, verse_query)
        return render(request, 'edit_aseneth_verse.html', context)

    if chapter_query:
        context = get_aseneth_chapter(chapter_query)
        return render(request, 'edit_aseneth_chapter.html', context)

    try:
        story = get_aseneth_story()
    except psycopg2.Error as exc:
        messages.error(request, f"Unable to load Joseph and Aseneth story: {exc}")
        story = []

    context = {
        'book': book_name,
        'story': story,
        'find_text': request.GET.get('find_text', ''),
        'replace_text': request.GET.get('replace_text', '')
    }
    return render(request, 'edit_aseneth_input.html', context)

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
            max_row = cursor.fetchone()
            max_verse = max_row[0] if max_row else None

            context = {
                'verse_data': verse_data,
                'book': 'He Adds and Storehouse',
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
                'book': 'He Adds and Storehouse',
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


def lexicon_viewer(request, lexicon_type, page):
    """
    Enhanced viewer for Fürst and Gesenius lexicon page images.
    Provides zoom, navigation, and keyboard shortcuts.
    """
    from translate.translator import (
        FUERST_IMAGE_BASE_URL, 
        GESENIUS_IMAGE_BASE_URL,
        format_fuerst_page_label,
        format_gesenius_page_label
    )
    
    # Validate lexicon type
    if lexicon_type not in ['fuerst', 'gesenius']:
        return render(request, 'lexicon_viewer.html', {
            'error_message': 'Invalid lexicon type. Must be "fuerst" or "gesenius".',
            'lexicon_name': lexicon_type.title(),
            'page_number': page,
            'image_url': None,
            'has_prev': False,
            'has_next': False,
            'prev_url': '#',
            'next_url': '#',
        })
    
    # Determine base URL and lexicon name
    if lexicon_type == 'fuerst':
        base_url = FUERST_IMAGE_BASE_URL
        lexicon_name = 'Fürst'
    else:
        base_url = GESENIUS_IMAGE_BASE_URL
        lexicon_name = 'Gesenius'
    
    # Construct image URL
    image_url = f"{base_url}/{page}" if base_url else None
    
    # Extract page number from filename (e.g., "fuerst_lex_0717.jpg" -> 717)
    # Handle different formats: "0123.png", "fuerst_lex_0717.jpg", "gesenius_lexicon_0507.jpg"
    import re
    page_match = re.search(r'(\d+)', page)
    if not page_match:
        return render(request, 'lexicon_viewer.html', {
            'error_message': f'Invalid page format: {page}',
            'lexicon_name': lexicon_name,
            'page_number': page,
            'image_url': None,
            'has_prev': False,
            'has_next': False,
            'prev_url': '#',
            'next_url': '#',
        })
    
    current_page_num = int(page_match.group(1))
    
    # Determine the filename pattern based on the input
    if page.startswith('fuerst_lex_'):
        # Fürst format: fuerst_lex_0717.jpg
        prev_page = f"fuerst_lex_{current_page_num - 1:04d}.jpg"
        next_page = f"fuerst_lex_{current_page_num + 1:04d}.jpg"
    elif page.startswith('gesenius_lexicon_'):
        # Gesenius format: gesenius_lexicon_0507.jpg
        prev_page = f"gesenius_lexicon_{current_page_num - 1:04d}.jpg"
        next_page = f"gesenius_lexicon_{current_page_num + 1:04d}.jpg"
    else:
        # Simple format: 0123.png
        file_ext = page.split('.')[-1] if '.' in page else 'png'
        prev_page = f"{current_page_num - 1:04d}.{file_ext}"
        next_page = f"{current_page_num + 1:04d}.{file_ext}"
    
    prev_url = f"/lexicon/{lexicon_type}/{prev_page}" if current_page_num > 1 else "#"
    next_url = f"/lexicon/{lexicon_type}/{next_page}"
    
    # Format page label for display
    if lexicon_type == 'fuerst':
        page_label = format_fuerst_page_label(page)
    else:
        page_label = format_gesenius_page_label(page)
    
    context = {
        'lexicon_name': lexicon_name,
        'lexicon_type': lexicon_type,
        'page_number': page_label,
        'page_number_numeric': current_page_num,  # For the input field
        'page_raw': page,
        'image_url': image_url,
        'has_prev': current_page_num > 1,
        'has_next': True,  # Always allow next (let browser handle 404 if doesn't exist)
        'prev_url': prev_url,
        'next_url': next_url,
    }
    
    return render(request, 'lexicon_viewer.html', context)


@login_required
@require_POST
def add_manual_lexicon_mapping(request):
    """
    Add a manual mapping from a Hebrew word to Fürst/Gesenius lexicon entries.
    Useful for shin/sin distinctions and other cases where Strong's is insufficient.
    """
    import json
    import re
    
    try:
        data = json.loads(request.body)
        
        hebrew_word = data.get('hebrew_word', '').strip()
        strong_number = data.get('strong_number', '').strip()
        lexicon_type = data.get('lexicon_type', 'both')  # 'fuerst', 'gesenius', or 'both'
        fuerst_id = data.get('fuerst_id')
        gesenius_id = data.get('gesenius_id')
        book = data.get('book')
        chapter = data.get('chapter')
        verse = data.get('verse')
        notes = data.get('notes', '').strip()
        
        if not hebrew_word:
            return JsonResponse({'success': False, 'error': 'Hebrew word is required'}, status=400)
        
        if lexicon_type not in ['fuerst', 'gesenius', 'both']:
            return JsonResponse({'success': False, 'error': 'Invalid lexicon type'}, status=400)
        
        # Strip vowel points to get consonantal form
        vowel_pattern = r'[\u0591-\u05AF\u05B0-\u05BD\u05BF\u05C1-\u05C2\u05C4-\u05C5\u05C7]'
        hebrew_consonantal = re.sub(vowel_pattern, '', hebrew_word)
        
        with get_db_connection() as conn:
            cursor = conn.cursor()

            # Ensure the unique index exists so ON CONFLICT works across environments
            cursor.execute("""
                CREATE UNIQUE INDEX IF NOT EXISTS manual_lexicon_mappings_conflict_idx
                ON old_testament.manual_lexicon_mappings
                (hebrew_word, strong_number, lexicon_type, book, chapter, verse);
            """)
            
            # Insert or update the mapping
            cursor.execute("""
                INSERT INTO old_testament.manual_lexicon_mappings 
                (hebrew_word, hebrew_consonantal, strong_number, lexicon_type, 
                 fuerst_id, gesenius_id, book, chapter, verse, notes, updated_at)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, CURRENT_TIMESTAMP)
                ON CONFLICT (hebrew_word, strong_number, lexicon_type, book, chapter, verse)
                DO UPDATE SET
                    fuerst_id = EXCLUDED.fuerst_id,
                    gesenius_id = EXCLUDED.gesenius_id,
                    notes = EXCLUDED.notes,
                    updated_at = CURRENT_TIMESTAMP
                RETURNING mapping_id
            """, (hebrew_word, hebrew_consonantal, strong_number or None, lexicon_type,
                  fuerst_id, gesenius_id, book, chapter, verse, notes))
            
            mapping_id = cursor.fetchone()[0] # type: ignore
            conn.commit()
        
        return JsonResponse({
            'success': True,
            'mapping_id': mapping_id,
            'message': f'Manual mapping added for {hebrew_word}'
        })
        
    except json.JSONDecodeError:
        return JsonResponse({'success': False, 'error': 'Invalid JSON'}, status=400)
    except Exception as e:
        logger.error(f"Error adding manual lexicon mapping: {e}")
        return JsonResponse({'success': False, 'error': str(e)}, status=500)


@login_required
def get_lexicon_search_results(request):
    """
    Search Fürst and Gesenius lexicons to find entries for manual mapping.
    Supports flexible search modes: exact, contains (partial), root, id, strong, and definition.
    """
    hebrew_word = request.GET.get('hebrew', '').strip()
    strong_number = request.GET.get('strong', '').strip()
    lexicon_type = request.GET.get('lexicon', 'both')  # 'fuerst', 'gesenius', or 'both'
    match = request.GET.get('match', 'exact')  # 'exact', 'contains', 'root', 'id', 'strong', 'definition'
    search_term = request.GET.get('search', '').strip()

    if not any([hebrew_word, strong_number, search_term]):
        return JsonResponse({'error': 'Hebrew word, Strong number, or search term required'}, status=400)

    results = {'fuerst': [], 'gesenius': []}

    import re
    vowel_pattern = r'[\u0591-\u05AF\u05B0-\u05BD\u05BF\u05C1-\u05C2\u05C4-\u05C5\u05C7]'
    hebrew_consonantal = re.sub(vowel_pattern, '', hebrew_word) if hebrew_word else ''

    def _like_pattern(val):
        return f"%{val}%"

    try:
        with get_db_connection() as conn:
            cursor = conn.cursor()

            # Build Fürst query
            if lexicon_type in ['fuerst', 'both']:
                params = []
                where_clauses = []

                if match == 'exact':
                    if hebrew_consonantal:
                        where_clauses.append('hebrew_consonantal = %s')
                        params.append(hebrew_consonantal)
                    elif search_term:
                        # try exact match on consonantal or full field
                        st_cons = re.sub(vowel_pattern, '', search_term)
                        where_clauses.append('(hebrew_consonantal = %s OR hebrew_word = %s)')
                        params.extend([st_cons, search_term])

                elif match == 'contains':
                    term = search_term or hebrew_consonantal
                    if term:
                        where_clauses.append('(hebrew_word ILIKE %s OR hebrew_consonantal ILIKE %s)')
                        p = _like_pattern(term)
                        params.extend([p, p])

                elif match == 'root':
                    if search_term:
                        where_clauses.append('root ILIKE %s')
                        params.append(_like_pattern(search_term))

                elif match == 'id':
                    try:
                        numeric_id = int(search_term)
                        where_clauses.append('id = %s')
                        params.append(numeric_id)
                    except Exception:
                        # invalid id, no results
                        where_clauses.append('false')

                elif match == 'definition':
                    if search_term:
                        where_clauses.append('definition ILIKE %s')
                        params.append(_like_pattern(search_term))

                # strong lookup
                if match == 'strong' or (strong_number and match == 'exact'):
                    if strong_number:
                        where_clauses.append('id IN (SELECT fuerst_id FROM old_testament.lexeme_fuerst WHERE lexeme_id IN (SELECT lexeme_id FROM old_testament.lexemes WHERE strongs = %s))')
                        params.append(strong_number)

                if not where_clauses:
                    # fallback to searching consonantal equality if we have it
                    if hebrew_consonantal:
                        where_clauses.append('hebrew_consonantal = %s')
                        params.append(hebrew_consonantal)

                query = f"SELECT id, hebrew_word, hebrew_consonantal, definition, part_of_speech, root, source_page FROM old_testament.fuerst_lexicon WHERE {' OR '.join(where_clauses)} LIMIT 100"
                cursor.execute(query, tuple(params))

                for row in cursor.fetchall():
                    results['fuerst'].append({
                        'id': row[0],
                        'hebrew_word': row[1],
                        'hebrew_consonantal': row[2],
                        'definition': row[3][:200] if row[3] else '',
                        'part_of_speech': row[4],
                        'root': row[5],
                        'source_page': row[6]
                    })

            # Build Gesenius query
            if lexicon_type in ['gesenius', 'both']:
                params = []
                where_clauses = []

                if match == 'exact':
                    if hebrew_consonantal:
                        where_clauses.append('"hebrewConsonantal" = %s')
                        params.append(hebrew_consonantal)
                    elif search_term:
                        st_cons = re.sub(vowel_pattern, '', search_term)
                        where_clauses.append('("hebrewConsonantal" = %s OR "hebrewWord" = %s)')
                        params.extend([st_cons, search_term])

                elif match == 'contains':
                    term = search_term or hebrew_consonantal
                    if term:
                        where_clauses.append('("hebrewWord" ILIKE %s OR "hebrewConsonantal" ILIKE %s)')
                        p = _like_pattern(term)
                        params.extend([p, p])

                elif match == 'root':
                    if search_term:
                        where_clauses.append('root ILIKE %s')
                        params.append(_like_pattern(search_term))

                elif match == 'id':
                    try:
                        numeric_id = int(search_term)
                        where_clauses.append('id = %s')
                        params.append(numeric_id)
                    except Exception:
                        where_clauses.append('false')

                elif match == 'definition':
                    if search_term:
                        where_clauses.append('definition ILIKE %s')
                        params.append(_like_pattern(search_term))

                if match == 'strong' or (strong_number and match == 'exact'):
                    if strong_number:
                        where_clauses.append('%s = ANY(string_to_array("strongsNumbers", ","))')
                        params.append(strong_number)

                if not where_clauses:
                    if hebrew_consonantal:
                        where_clauses.append('"hebrewConsonantal" = %s')
                        params.append(hebrew_consonantal)

                query = f"SELECT id, \"hebrewWord\", \"hebrewConsonantal\", definition, \"partOfSpeech\", root, \"sourcePage\" FROM old_testament.gesenius_lexicon WHERE {' OR '.join(where_clauses)} LIMIT 100"
                cursor.execute(query, tuple(params))

                for row in cursor.fetchall():
                    results['gesenius'].append({
                        'id': row[0],
                        'hebrew_word': row[1],
                        'hebrew_consonantal': row[2],
                        'definition': row[3][:200] if row[3] else '',
                        'part_of_speech': row[4],
                        'root': row[5],
                        'source_page': row[6]
                    })

        return JsonResponse(results)

    except Exception as e:
        logger.error(f"Error searching lexicons: {e}")
        return JsonResponse({'error': str(e)}, status=500)


