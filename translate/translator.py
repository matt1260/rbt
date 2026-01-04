import os
import html
import json
import re
import logging
from functools import lru_cache
from typing import Optional
import unicodedata

try:
    from django.conf import settings
except Exception:  # pragma: no cover - settings may be unavailable in some scripts
    settings = None

from .db_utils import get_db_connection, execute_query, table_has_column

DEFAULT_FUERST_IMAGE_BASE_URL = "http://www.realbible.tech/fuerst_lexicon"
DEFAULT_GESENIUS_IMAGE_BASE_URL = "http://www.realbible.tech/gesenius_lexicon"

logger = logging.getLogger(__name__)

def _debug_filtered_rows(label: str, before_rows: list[tuple], after_rows: list[tuple]) -> None:
    if not settings or not getattr(settings, 'DEBUG', False):
        return
    before_len = len(before_rows)
    after_len = len(after_rows)
    removed = [row for row in before_rows if row not in after_rows]
    info = f"{label} filter before={before_len} after={after_len}"
    def summarize(row: tuple) -> str:
        return f"id={row[0]} strongs={row[9]} word={row[1]} consonantal={row[2]}"
    if removed:
        snippet = [summarize(row) for row in removed]
        logger.debug("%s filter removed %d rows: %s", label, len(removed), snippet)
        print(f"{label} removed rows: {snippet}")
    logger.debug(info)
    if settings.DEBUG:
        print(info)


def get_manual_lexicon_mappings(hebrew_word: str, strong_number: Optional[str] = None,
                                   book: Optional[str] = None, chapter: Optional[int] = None, verse: Optional[int] = None):
    """
    Retrieve manual lexicon mappings for a Hebrew word.
    Checks most specific to least specific (verse-level → chapter-level → book-level → global).
    Returns dict with 'fuerst_ids' and 'gesenius_ids' lists.
    """
    if not hebrew_word:
        return {'fuerst_ids': [], 'gesenius_ids': []}
    
    # Normalize Hebrew text to NFD form (decomposed) for consistent comparison
    # This ensures diacritical marks are in consistent order
    hebrew_word_normalized = unicodedata.normalize('NFD', hebrew_word)
    
    # For global-only mappings, simplify the query
    results = execute_query("""
        SELECT lexicon_type, fuerst_id, gesenius_id
        FROM old_testament.manual_lexicon_mappings
        WHERE NORMALIZE(hebrew_word, NFD) = %s
          AND (strong_number = %s OR strong_number IS NULL)
          AND book IS NULL
          AND chapter IS NULL
          AND verse IS NULL
        ORDER BY mapping_id
    """, (hebrew_word_normalized, strong_number), fetch='all')
    
    fuerst_ids = []
    gesenius_ids = []
    
    if results:
        # Collect all matching entries (may have separate fuerst and gesenius rows)
        for result in results:
            lexicon_type, fuerst_id, gesenius_id = result
            if fuerst_id and lexicon_type in ('fuerst', 'both'):
                fuerst_ids.append(fuerst_id)
            if gesenius_id and lexicon_type in ('gesenius', 'both'):
                gesenius_ids.append(gesenius_id)
        
        return {
            'fuerst_ids': fuerst_ids,
            'gesenius_ids': gesenius_ids
        }
    
    return {'fuerst_ids': [], 'gesenius_ids': []}


# Small HTML sanitizer: allows a small whitelist of tags and safe <a href="..."> links
def sanitize_allowed_html(raw_html: str) -> str:
    """Return a sanitized HTML fragment allowing a small set of tags.

    - Escapes everything first, then un-escapes a safe subset of tags: p, br, strong, em, b, i, ul, ol, li, a.
    - For <a>, only preserves href attributes that start with http(s) or mailto.
    This is intentionally conservative and avoids adding dependencies like 'bleach'.
    """
    if not raw_html:
        return ''

    # Escape everything first
    esc = html.escape(raw_html)

    # Simple tags to unescape (no attributes)
    simple_tags = ['p', 'br', 'strong', 'em', 'b', 'i', 'ul', 'ol', 'li']
    for tag in simple_tags:
        esc = esc.replace(f'&lt;{tag}&gt;', f'<{tag}>')
        esc = esc.replace(f'&lt;/{tag}&gt;', f'</{tag}>')
        esc = esc.replace(f'&lt;{tag} /&gt;', f'<{tag} />')
        esc = esc.replace(f'&lt;{tag}/&gt;', f'<{tag}/>' )

    # Handle <br> variants
    esc = esc.replace('&lt;br&gt;', '<br>').replace('&lt;br /&gt;', '<br />').replace('&lt;br/&gt;', '<br/>')

    # Unescape safe <a href="..."> links, preserving only http(s) and mailto
    # Find patterns like &lt;a href=&quot;URL&quot;&gt;
    def _unescape_anchor(match):
        href = match.group(1)
        # Decode HTML entities in href
        href = href.replace('&amp;', '&').replace('&quot;', '"')
        # Allow only http, https or mailto
        if re.match(r'^(https?:|mailto:)', href, re.I):
            return f'<a href="{href}" target="_blank" rel="noopener noreferrer">'
        # otherwise do not render the href attribute
        return '<a>'

    esc = re.sub(r'&lt;a\s+href=&quot;([^&]*)&quot;&gt;', _unescape_anchor, esc)
    esc = esc.replace('&lt;/a&gt;', '</a>')

    return esc


book_abbreviations = {
    'Genesis': 'Gen',
    'Exodus': 'Exo',
    'Leviticus': 'Lev',
    'Numbers': 'Num',
    'Deuteronomy': 'Deu',
    'Joshua': 'Jos',
    'Judges': 'Jdg',
    'Ruth': 'Rut',
    '1 Samuel': '1Sa',
    '2 Samuel': '2Sa',
    '1Samuel': '1Sa',
    '2Samuel': '2Sa',
    'Samuel_1': '1Sa',
    'Samuel_2': '2Sa',
    '1 Kings': '1Ki',
    '2 Kings': '2Ki',
    '1Kings': '1Ki',
    '2Kings': '2Ki',
    'Kings_1': '1Ki',
    'Kings_2': '2Ki',
    '1 Chronicles': '1Ch',
    '2 Chronicles': '2Ch',
    '1Chronicles': '1Ch',
    '2Chronicles': '2Ch',
    'Chronicles_1': '1Ch',
    'Chronicles_2': '2Ch',
    'Ezra': 'Ezr',
    'Nehemiah': 'Neh',
    'Esther': 'Est',
    'Job': 'Job',
    'Psalms': 'Psa',
    'Proverbs': 'Pro',
    'Ecclesiastes': 'Ecc',
    'Song of Solomon': 'Sng',
    'Song_Of_Songs': 'Sng',
    'Songs': 'Sng',
    'Isaiah': 'Isa',
    'Jeremiah': 'Jer',
    'Lamentations': 'Lam',
    'Ezekiel': 'Eze',
    'Daniel': 'Dan',
    'Hosea': 'Hos',
    'Joel': 'Joe',
    'Amos': 'Amo',
    'Obadiah': 'Oba',
    'Jonah': 'Jon',
    'Micah': 'Mic',
    'Nahum': 'Nah',
    'Habakkuk': 'Hab',
    'Zephaniah': 'Zep',
    'Haggai': 'Hag',
    'Zechariah': 'Zec',
    'Malachi': 'Mal',
    'Matthew': 'Mat',
    'Mark': 'Mar',
    'Luke': 'Luk',
    'John': 'Joh',
    'Acts': 'Act',
    'Romans': 'Rom',
    '1 Corinthians': '1Co',
    '2 Corinthians': '2Co',
    '1Corinthians': '1Co',
    '2Corinthians': '2Co',
    'Galatians': 'Gal',
    'Ephesians': 'Eph',
    'Philippians': 'Php',
    'Colossians': 'Col',
    '1 Thessalonians': '1Th',
    '2 Thessalonians': '2Th',
    '1Thessalonians': '1Th',
    '2Thessalonians': '2Th',
    '1 Timothy': '1Ti',
    '2 Timothy': '2Ti',
    '1Timothy': '1Ti',
    '2Timothy': '2Ti',
    'Titus': 'Tit',
    'Philemon': 'Phm',
    'Hebrews': 'Heb',
    'James': 'Jam',
    '1 Peter': '1Pe',
    '2 Peter': '2Pe',
    '1Peter': '1Pe',
    '2Peter': '2Pe',
    '1 John': '1Jo',
    '2 John': '2Jo',
    '3 John': '3Jo',
    '1John': '1Jo',
    '2John': '2Jo',
    '3John': '3Jo',
    'Jude': 'Jud',
    'Revelation': 'Rev'
}
old_testament_books = [
        'Exodus', 'Leviticus', 'Numbers', 'Deuteronomy', 'Joshua', 'Judges', 'Ruth',
        '1Samuel', '2Samuel', '1 Samuel', '2 Samuel', '1Kings', '2Kings', '1 Kings', '2 Kings', '1Chronicles', '2Chronicles', '1 Chronicles', '2 Chronicles', 'Ezra', 'Nehemiah',
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

# For re-casting the titles on the front-end
rbt_books = {
    'Genesis': 'In the Head',
    'Exodus': 'A Mighty One of Names',
    'Leviticus': 'He is Reading',
    'Numbers': 'He is Arranging Words',
    'Deuteronomy': 'A Mighty One of Words',
    'Esther': 'Star',
    'Song of Solomon': 'Song of Singers',
    'Job': 'Adversary',
    'Isaiah': 'He is Liberator',
    'Ezekiel': 'God Holds Strong',
    'John': 'He is Favored',
    'Matthew': 'He is a Gift',
    'Mark': 'Hammer',
    'Luke': 'Light Giver',
    'Acts': 'Acts of Sent Away Ones',
    'Revelation': 'Unveiling',
    'Hebrews': 'Beyond Ones',
    'Jonah': 'Dove',
    '1 John': '1 Favored',
    '2 John': '2 Favored',
    '3 John': '3 Favored',
    'James': 'Heel Chaser',
    'Galatians': 'People of the Land of Milk',
    'Philippians': 'People of the Horse',
    'Ephesians': 'People of the Land of Bees',
    'Colossians': 'People of Colossal Ones',
    'Titus': 'Avenged',
    '1 Timothy': 'First Honor of God',
    '2 Timothy': 'Second Honor of God'
}


def _resolve_fuerst_base_url() -> str:
    """Determine the base URL used for Fuerst page image links."""
    candidate = None
    if settings is not None:
        try:
            candidate = getattr(settings, 'FUERST_IMAGE_BASE_URL', None)
        except Exception:
            candidate = None
    if candidate:
        return candidate.rstrip('/')

    env_value = os.environ.get('FUERST_IMAGE_BASE_URL', '')
    if env_value:
        return env_value.rstrip('/')

    if DEFAULT_FUERST_IMAGE_BASE_URL:
        return DEFAULT_FUERST_IMAGE_BASE_URL.rstrip('/')

    return ''

def _resolve_gesenius_base_url() -> str:
    """Determine the base URL used for Gesenius page image links."""
    candidate = None
    if settings is not None:
        try:
            candidate = getattr(settings, 'GESENIUS_IMAGE_BASE_URL', None)
        except Exception:
            candidate = None
    if candidate:
        return candidate.rstrip('/')

    env_value = os.environ.get('GESENIUS_IMAGE_BASE_URL', '')
    if env_value:
        return env_value.rstrip('/')

    if DEFAULT_GESENIUS_IMAGE_BASE_URL:
        return DEFAULT_GESENIUS_IMAGE_BASE_URL.rstrip('/')

    return ''


FUERST_IMAGE_BASE_URL = _resolve_fuerst_base_url()

GESENIUS_IMAGE_BASE_URL = _resolve_gesenius_base_url()


def build_gesenius_page_url(source_page: str) -> str:
    """Return a URL to the enhanced lexicon viewer for a Gesenius page."""
    if not source_page:
        return ''
    # Link to the viewer instead of raw image
    return f"/lexicon/gesenius/{source_page}"


def format_gesenius_page_label(source_page: str) -> str:
    if not source_page:
        return 'View scan'
    match = re.search(r'(\d+)', source_page)
    if match:
        try:
            return f"Page {int(match.group(1))}"
        except ValueError:
            pass
    return 'View scan'


def build_fuerst_page_url(source_page: str) -> str:
    """Return a URL to the enhanced lexicon viewer for a Fürst page."""
    if not source_page:
        return ''
    # Link to the viewer instead of raw image
    return f"/lexicon/fuerst/{source_page}"


def format_fuerst_page_label(source_page: str) -> str:
    if not source_page:
        return 'View scan'
    match = re.search(r'(\d+)', source_page)
    if match:
        try:
            return f"Page {int(match.group(1))}"
        except ValueError:
            pass
    return 'View scan'


@lru_cache(maxsize=2048)
def get_fuerst_entries_for_strong(strong_number: str):
    """Fetch cached Fuerst lexicon links for a canonical Strong's number (e.g., 'H7225')."""
    # Strip suffix (a-z letters) from Strong's number for lexeme lookup
    # hebrewdata stores H5921a, but lexemes table stores H5921
    import re
    base_strong = re.sub(r'[a-z]+$', '', strong_number, flags=re.IGNORECASE)
    
    # Primary lookup: lexemes mapped to Fuerst entries
    rows = execute_query(
        """
        SELECT lf.fuerst_id,
               lf.confidence,
               lf.mapping_basis,
               COALESCE(l.lexeme, l.consonantal) AS lexeme_form,
               fl.hebrew_word,
               fl.hebrew_consonantal,
               fl.definition,
               fl.part_of_speech,
               fl.root,
               fl.source_page,
               lf.notes
        FROM old_testament.lexemes l
        JOIN old_testament.lexeme_fuerst lf ON lf.lexeme_id = l.lexeme_id
        JOIN old_testament.fuerst_lexicon fl ON fl.id = lf.fuerst_id
        WHERE l.strongs = %s
        ORDER BY
            CASE lf.confidence
                WHEN 'high' THEN 1
                WHEN 'medium' THEN 2
                ELSE 3
            END,
            fl.hebrew_word NULLS LAST,
            fl.id
        """,
        (base_strong,),
        fetch='all'
    ) or []

    entries = []
    for row in rows:
        (
            fuerst_id,
            confidence,
            mapping_basis,
            lexeme_form,
            hebrew_word,
            hebrew_consonantal,
            definition,
            part_of_speech,
            root,
            source_page,
            notes
        ) = row
        entries.append({
            'fuerst_id': fuerst_id,
            'confidence': confidence or '',
            'mapping_basis': mapping_basis or '',
            'lexeme_form': lexeme_form or '',
            'hebrew_word': hebrew_word or '',
            'hebrew_consonantal': hebrew_consonantal or '',
            'definition': definition or '',
            'part_of_speech': part_of_speech or '',
            'root': root or '',
            'source_page': source_page or '',
            'notes': notes or '',
        })

    if entries:
        # If the Strong's lemma is a very short form (1-2 chars) prefer exact matches only
        lemma_row = execute_query(
            "SELECT lemma FROM old_testament.strongs_hebrew_dictionary WHERE strong_number = %s",
            (strong_number,),
            fetch='one'
        )
        short_lemma = False
        if lemma_row and lemma_row[0]:
            lemma_val = lemma_row[0]
            lemma_clean = re.sub(r'[\u0591-\u05C7\s]', '', lemma_val or '')
            if len(lemma_clean) <= 2:
                short_lemma = True
                filtered = []
                for e in entries:
                    hw = re.sub(r'[\u0591-\u05C7\s]', '', (e.get('hebrew_consonantal') or ''))
                    hww = re.sub(r'[\u0591-\u05C7\s]', '', (e.get('hebrew_word') or ''))
                    lexf = re.sub(r'[\u0591-\u05C7\s]', '', (e.get('lexeme_form') or ''))
                    if hw == lemma_clean or hww == lemma_clean or lexf == lemma_clean:
                        filtered.append(e)
                if filtered:
                    return tuple(filtered)
                # No exact-match entries found for a short lemma — do NOT return broad lexeme mappings; fall through to other fallbacks
        # For non-short lemmas (or missing lemma), return the lexeme-derived entries
        if not short_lemma:
            return tuple(entries)

    # Fallback 1: look up Fuerst entries via the automated mapping table (fuerst_strongs_map)
    fb_rows = execute_query(
        """
        SELECT m.fuerst_id,
               m.method AS confidence,
               'fuerst_strongs_map' AS mapping_basis,
               '' AS lexeme_form,
               fl.hebrew_word,
               fl.hebrew_consonantal,
               fl.definition,
               fl.part_of_speech,
               fl.root,
               fl.source_page,
               NULL AS notes
        FROM old_testament.fuerst_strongs_map m
        JOIN old_testament.fuerst_lexicon fl ON fl.id = m.fuerst_id
        WHERE m.strongs_id ILIKE %s OR m.strongs_id ILIKE %s
        ORDER BY m.score DESC NULLS LAST, fl.hebrew_word NULLS LAST, fl.id
        """,
        (f"%{strong_number}%", f"%{strong_number[1:] if strong_number.upper().startswith('H') else strong_number}%"),
        fetch='all'
    ) or []

    if fb_rows:
        fb_entries = []
        for row in fb_rows:
            (fuerst_id, confidence, mapping_basis, lexeme_form, hebrew_word, hebrew_consonantal, definition, part_of_speech, root, source_page, notes) = row
            fb_entries.append({
                'fuerst_id': fuerst_id,
                'confidence': confidence or '',
                'mapping_basis': mapping_basis or '',
                'lexeme_form': lexeme_form or '',
                'hebrew_word': hebrew_word or '',
                'hebrew_consonantal': hebrew_consonantal or '',
                'definition': definition or '',
                'part_of_speech': part_of_speech or '',
                'root': root or '',
                'source_page': source_page or '',
                'notes': notes or '',
            })
        return tuple(fb_entries)

    # Fallback 2: look up Fuerst entries directly by their strongs_numbers field
    # Some Fuerst entries aren't mapped via lexemes; include both H-prefixed and bare forms
    fallback_strong = strong_number
    bare_strong = strong_number[1:] if strong_number.upper().startswith('H') else ('H'+strong_number)

    fb_rows = execute_query(
        """
        SELECT fl.id AS fuerst_id,
               NULL AS confidence,
               'strongs_numbers' AS mapping_basis,
               '' AS lexeme_form,
               fl.hebrew_word,
               fl.hebrew_consonantal,
               fl.definition,
               fl.part_of_speech,
               fl.root,
               fl.source_page,
               NULL AS notes
        FROM old_testament.fuerst_lexicon fl
        WHERE %s = ANY (string_to_array(COALESCE(fl.strongs_numbers, ''), '/'))
        ORDER BY fl.hebrew_word NULLS LAST, fl.id
        """,
        (fallback_strong,),
        fetch='all'
    ) or []

    fb_entries = []
    for row in fb_rows:
        (fuerst_id, confidence, mapping_basis, lexeme_form, hebrew_word, hebrew_consonantal, definition, part_of_speech, root, source_page, notes) = row
        fb_entries.append({
            'fuerst_id': fuerst_id,
            'confidence': confidence or '',
            'mapping_basis': mapping_basis or '',
            'lexeme_form': lexeme_form or '',
            'hebrew_word': hebrew_word or '',
            'hebrew_consonantal': hebrew_consonantal or '',
            'definition': definition or '',
            'part_of_speech': part_of_speech or '',
            'root': root or '',
            'source_page': source_page or '',
            'notes': notes or '',
        })

    if fb_entries:
        return tuple(fb_entries)

    # Final fallback: try matching by Strong's lemma in the Strongs Hebrew dictionary
    lemma_row = execute_query(
        "SELECT lemma FROM old_testament.strongs_hebrew_dictionary WHERE strong_number = %s",
        (strong_number,),
        fetch='one'
    )
    if lemma_row and lemma_row[0]:
        lemma = lemma_row[0]
        # Normalize lemma by stripping niqqud and whitespace to avoid accidental substring matches
        def _strip_niqqud(s: str) -> str:
            return re.sub(r'[\u0591-\u05C7\s]', '', s or '')

        lemma_clean = _strip_niqqud(lemma)

        # If lemma is very short (1-2 chars) prefer exact equality on hebrew_consonantal/hebrew_word
        if len(lemma_clean) <= 2:
            fb_rows = execute_query(
                """
                SELECT fl.id AS fuerst_id,
                       NULL AS confidence,
                       'lemma_lookup' AS mapping_basis,
                       '' AS lexeme_form,
                       fl.hebrew_word,
                       fl.hebrew_consonantal,
                       fl.definition,
                       fl.part_of_speech,
                       fl.root,
                       fl.source_page,
                       NULL AS notes
                FROM old_testament.fuerst_lexicon fl
                WHERE COALESCE(fl.hebrew_consonantal, '') = %s OR COALESCE(fl.hebrew_word, '') = %s
                ORDER BY fl.hebrew_word NULLS LAST, fl.id
                """,
                (lemma_clean, lemma_clean),
                fetch='all'
            ) or []
        else:
            fb_rows = execute_query(
                """
                SELECT fl.id AS fuerst_id,
                       NULL AS confidence,
                       'lemma_lookup' AS mapping_basis,
                       '' AS lexeme_form,
                       fl.hebrew_word,
                       fl.hebrew_consonantal,
                       fl.definition,
                       fl.part_of_speech,
                       fl.root,
                       fl.source_page,
                       NULL AS notes
                FROM old_testament.fuerst_lexicon fl
                WHERE fl.hebrew_consonantal ILIKE %s OR fl.hebrew_word ILIKE %s
                ORDER BY fl.hebrew_word NULLS LAST, fl.id
                """,
                (f"%{lemma_clean}%", f"%{lemma_clean}%"),
                fetch='all'
            ) or []

        if fb_rows:
            fb_entries = []
            for row in fb_rows:
                (fuerst_id, confidence, mapping_basis, lexeme_form, hebrew_word, hebrew_consonantal, definition, part_of_speech, root, source_page, notes) = row
                fb_entries.append({
                    'fuerst_id': fuerst_id,
                    'confidence': confidence or '',
                    'mapping_basis': mapping_basis or '',
                    'lexeme_form': lexeme_form or '',
                    'hebrew_word': hebrew_word or '',
                    'hebrew_consonantal': hebrew_consonantal or '',
                    'definition': definition or '',
                    'part_of_speech': part_of_speech or '',
                    'root': root or '',
                    'source_page': source_page or '',
                    'notes': notes or '',
                })
            return tuple(fb_entries)

    return tuple(fb_entries)


def clear_fuerst_cache() -> None:
    """Clear the Fuerst entries cache (useful after updating mapping tables)."""
    get_fuerst_entries_for_strong.cache_clear()


def convert_to_book_chapter_verse(input_verse):
            
    # Split the input string at the '.' character
    parts = input_verse.split('.')

    # Extract the book, chapter, and verse parts
    book = parts[0]
    chapter = parts[1]
    verse = parts[2]
    verse = verse[:-1] # Remove the dash

    # Format the output as 'Book Chapter:Verse'
    formatted_output = f"{book} {chapter}:{verse}"

    return formatted_output

def get_cache_reference(verse_id):
    #print(verse_id)
    ref = verse_id.split('.')
    book = ref[0]
    chapter_num = ref[1]
    verse_num = ref[2].split('-')[0]
    #print(book)
    book = convert_book_name(book)

    #print(book)
    sanitized_book = book.replace(' ', '_') if book else '' 

    cache_key_base_verse = f'{sanitized_book}_{chapter_num}_{verse_num}'
    cache_key_base_chapter = f'{sanitized_book}_{chapter_num}_None'

    return cache_key_base_chapter, cache_key_base_verse

# take abbreviation (i.e. 'Gen') and return the next book (not used)
def get_next_book(abbreviation):
    for book, abbrev in book_abbreviations.items():
        if abbrev == abbreviation:
            books = list(book_abbreviations.keys())

            current_index = list(book_abbreviations.values()).index(abbrev)

            if current_index < len(books) - 1:
                next_book = books[current_index + 1]
                return next_book
            else:
                return None 
    return None 


def get_previous_book(abbreviation):
    for book, abbrev in book_abbreviations.items():
        if abbrev == abbreviation:
            # Get the list of book abbreviations
            abbrevs = list(book_abbreviations.values())
            
            # Find the index of the current abbreviation
            current_index = abbrevs.index(abbrev)
            
            # Get the previous abbreviation using the index
            if current_index > 0:
                previous_abbrev = abbrevs[current_index - 1]
                return previous_abbrev
            else:
                return None  # No previous abbreviation for the first one
    return None  # Abbreviation not found

# Convert book between abbreviation and full name
def convert_book_name(input_str):
    # Check if the input is an abbreviation

    if input_str in book_abbreviations.values():
        # Convert abbreviation to full name
        for book, abbrev in book_abbreviations.items():
            if abbrev == input_str:
                return book
    elif input_str in book_abbreviations.keys():
        # Convert full name to abbreviation
        return book_abbreviations[input_str]
    else:
        # Return None for unknown input
        return None

# Get the previous and next row verse reference for OT
def ot_prev_next_references(ref):
    """
    Get the previous and next verse references for OT (Old Testament) 
    using PostgreSQL.
    """

    if ref.endswith('-'):
        ref = ref[:-1]

    # Get current row id
    row = execute_query(
        "SELECT id FROM old_testament.ot WHERE Ref = %s;",
        (ref,),
        fetch='one'
    )
    if not row:
        return None, None

    ref_id = row[0]

    # Fetch previous reference
    prev_row = execute_query(
        "SELECT Ref FROM old_testament.ot WHERE id = %s - 1;",
        (ref_id,),
        fetch='one'
    )
    prev_reference = prev_row[0] if prev_row else ref
    prev_parts = prev_reference.split('.')
    prev_book = convert_book_name(prev_parts[0])
    prev_ref = f'?book={prev_book}&chapter={prev_parts[1]}&verse={prev_parts[2]}'

    # Fetch next reference
    next_row = execute_query(
        "SELECT Ref FROM old_testament.ot WHERE id = %s + 1;",
        (ref_id,),
        fetch='one'
    )
    if next_row:
        next_reference = next_row[0]
        next_parts = next_reference.split('.')
        next_book = convert_book_name(next_parts[0])
        next_ref = f'?book={next_book}&chapter={next_parts[1]}&verse={next_parts[2]}'
    else:
        # If next reference does not exist (e.g., last verse of Malachi)
        next_ref = f'?book=Matthew&chapter=1&verse=1'

    return prev_ref, next_ref

def extract_footnote_references(verses):
    footnote_references = []
    for rbt in verses:
        rbt_strings = ' '.join(filter(None, rbt))
        numbers = re.findall(r'<sup>(.*?)</sup>', rbt_strings)
        footnote_references.extend(numbers)
    return footnote_references

# For loading interlinear replacement json
def load_json(filename):
    # Return a mapping (dict) of replacements; the consumer expects a dict-like object
    replacements = {}

    if not os.path.exists(filename):
        print(f"[DEBUG] JSON file not found: {filename}")
        return replacements

    try:
        with open(filename, 'r', encoding='utf-8') as file:
            json_string = file.read()

        if not json_string.strip():
            print(f"[DEBUG] JSON file is empty: {filename}")
            return replacements

        # Normalize quotes and remove escape characters
        json_string = json_string.replace("'", '"')
        if json_string and json_string[0] == '"' and json_string[-1] == '"':
            json_string = json_string[1:-1]
        json_string = json_string.replace("\\", "")

        parsed = json.loads(json_string)

        # Ensure we return a dict; if the file contains a list, try to convert it
        if isinstance(parsed, dict):
            replacements = parsed
        elif isinstance(parsed, list):
            # If a list of two-element lists or pairs, convert to dict
            try:
                replacements = dict(parsed)
            except Exception:
                # Fallback: leave replacements empty and log a debug message
                print(f"[DEBUG] JSON parsed to list but could not convert to dict: {filename}")
                replacements = {}
        else:
            # Unexpected JSON type; keep empty mapping
            print(f"[DEBUG] JSON parsed to unsupported type ({type(parsed).__name__}): {filename}")
            replacements = {}

    except json.JSONDecodeError as e:
        print(f"[ERROR] Failed to parse JSON file {filename}: {e}")

    return replacements

# function for replacing words in the interlinear greek
def replace_words(strongs, lemma, english):

    replacements = load_json('interlinear_english.json')

    # Check if any of the conditions match and replace english if so
    for condition, replacement in replacements.items():
        if strongs == condition or lemma == condition:
            english = replacement
            break  # Exit loop after first match
    
    return strongs, lemma, english

def strong_data(strong_ref):
    # Normalize the reference: keep any single trailing letter (e.g., '5869a') for display
    # but use the numeric portion for lookups
    if len(strong_ref) == 6:
        last_character = strong_ref[-1]
    else:
        last_character = '' 

    # Extract numeric part for canonical lookups
    strong_number = re.sub(r'[^0-9]', '', strong_ref)
    strong_number = int(strong_number)
    strong_number = str(strong_number)
    # display ref preserves the trailing letter (if present)
    display_ref = strong_number + last_character

    # Special handling (historical)
    if display_ref == '1961':
        hayah = True

    # Build a concise link to BibleHub (no icon to save space)
    strong_link = (
        f'<a href="https://biblehub.com/hebrew/{display_ref}.htm" target="_blank" '
        f'rel="noopener noreferrer" class="strong-link">{display_ref}</a>'
    )

    # Look up the dictionary entry using canonical 'H' prefixed number
    strong_number = 'H' + strong_number

    result = execute_query(
        """
        SELECT lemma, xlit, derivation, strongs_def, description
        FROM old_testament.strongs_hebrew_dictionary
        WHERE strong_number = %s;
        """,
        (strong_number,),
        fetch='one'
    )

    if result is not None:
        lemma = result[0] or ''
        xlit = result[1] or ''
        derivation = result[2] or ''
        definition = result[3] or ''
        description = result[4] or ''
    else:
        lemma = ''
        xlit = ''
        derivation = ''
        definition = 'Definition not found'
        description = ''

    # Escape text to avoid accidental HTML injection for most fields
    lemma_esc = html.escape(lemma)
    xlit_esc = html.escape(xlit)
    derivation_esc = html.escape(derivation)
    definition_esc = html.escape(definition)
    # Description may contain safe HTML (paragraphs, links) — sanitize and allow certain tags
    description_html = sanitize_allowed_html(description)

    # Use a special citation for the H9000-H9009 range
    if strong_number in {f'H{n}' for n in range(9000, 9010)}:
        citation_html = (
            '<div class="strong-citation"><small>Source: '
            '<a href="https://www.realbible.tech/%d7%95-%d7%91-%d7%9b-%d7%9c-%d7%9e-the-aonic-nature-of-biblical-hebrew-prepositions/" '
            'target="_blank" rel="noopener noreferrer">The Aonic Nature of Biblical Hebrew Prepositions</a>'
            '</small></div>'
        )
    else:
        citation_html = (
            f'<div class="strong-citation"><small>Source: '
            f'<a href="https://biblehub.com/hebrew/{display_ref}.htm" target="_blank" rel="noopener noreferrer">'
            f"Strong&#39;s Exhaustive Concordance — {strong_number}</a></small></div>"
        )

    single_ref = f"""
<div class="popup-container strong-popup">
  {strong_link}
  <div class="popup-content strong-popup-content" role="tooltip" aria-hidden="true">
    <div class="strong-header">
      <div class="strongs-headword">{lemma_esc}</div>
      <div class="strong-xlit">{xlit_esc}</div>
    </div>
    <dl class="strong-details">
      <dt>Definition</dt><dd>{definition_esc}</dd>
      <dt>Root</dt><dd>{derivation_esc}</dd>
      <dt>Exhaustive</dt><dd>{description_html}</dd>
    </dl>
    {citation_html}
  </div>
</div>
"""

    return single_ref


def build_strongs_popup(strong_refs: list[str]) -> str:
    """Render a dedicated Strong's popup trigger that combines multiple Strong's numbers."""
    if not strong_refs:
        return ''
    
    # Filter out H9014-H9018 range
    filtered_refs = []
    for ref in strong_refs:
        num = get_strongs_numeric_value(ref)
        if num is not None and 9014 <= num <= 9018:
            continue
        filtered_refs.append(ref)
    
    if not filtered_refs:
        return ''
    
    entry_blocks: list[str] = []
    entry_blocks.append("<div class='strongs-title'>Strong's Lexicon</div>")
    for strong_ref in filtered_refs:
        # Normalize the reference
        if len(strong_ref) == 6:
            last_character = strong_ref[-1]
        else:
            last_character = ''
        
        strong_number = re.sub(r'[^0-9]', '', strong_ref)
        strong_number = int(strong_number)
        strong_number = str(strong_number)
        display_ref = strong_number + last_character
        
        # Look up the dictionary entry
        strong_number_h = 'H' + strong_number
        result = execute_query(
            """
            SELECT lemma, xlit, derivation, strongs_def, description
            FROM old_testament.strongs_hebrew_dictionary
            WHERE strong_number = %s;
            """,
            (strong_number_h,),
            fetch='one'
        )
        
        if result is not None:
            lemma = result[0] or ''
            xlit = result[1] or ''
            derivation = result[2] or ''
            definition = result[3] or ''
            description = result[4] or ''
        else:
            lemma = ''
            xlit = ''
            derivation = ''
            definition = 'Definition not found'
            description = ''
        
        lemma_html = html.escape(lemma)
        xlit_html = html.escape(xlit)
        derivation_html = html.escape(derivation)
        definition_html = html.escape(definition)
        description_html = sanitize_allowed_html(description)
        
        # Build citation
        if strong_number_h in {f'H{n}' for n in range(9000, 9010)}:
            citation_html = (
                '<div class="strong-citation"><small>Source: '
                '<a href="https://www.realbible.tech/%d7%95-%d7%91-%d7%9b-%d7%9c-%d7%9e-the-aonic-nature-of-biblical-hebrew-prepositions/" '
                'target="_blank" rel="noopener noreferrer">The Aonic Nature of Biblical Hebrew Prepositions</a>'
                '</small></div>'
            )
        else:
            citation_html = (
                f'<div class="strong-citation"><small>Source: '
                f'<a href="https://biblehub.com/hebrew/{display_ref}.htm" target="_blank" rel="noopener noreferrer">'
                f"Strong&#39;s Exhaustive Concordance &mdash; {strong_number_h}</a></small></div>"
            )
        
        # Build entry using exact same structure as old strong-popup
        entry_html = f'''
            <div class="strongs-entry">
            <div class="strong-header">
                <div class="strongs-headword">{lemma_html}</div>
                <div class="strong-xlit">{xlit_html}</div>
            </div>
            <dl class="strong-details">
                <dt>Definition</dt><dd>{definition_html}</dd>
                <dt>Root</dt><dd>{derivation_html}</dd>
                <dt>Exhaustive</dt><dd>{description_html}</dd>
            </dl>
            {citation_html}
            </div>
            '''
        entry_blocks.append(entry_html)
    
    if not entry_blocks:
        return ''
    
    popup_html = (
        '<span class="popup-container strongs-popup">'
        '<span class="strongs-trigger">STRONGS</span>'
        '<div class="popup-content strongs-popup-content" role="tooltip" aria-hidden="true">'
        + ''.join(entry_blocks) +
        '</div>'
        '</span>'
    )
    return popup_html


def build_fuerst_popup(strong_ref: str, hebrew_word: str = '', book: Optional[str] = None, chapter: Optional[int] = None, verse: Optional[int] = None) -> str:
    """Render a dedicated Fuerst popup trigger next to a Strong's reference."""
    
    num = get_strongs_numeric_value(strong_ref)
    if num is None or num >= 9000:
        return ''

    strong_number = f'H{num}'
    
    # First check for manual mappings
    manual_mappings = get_manual_lexicon_mappings(hebrew_word, strong_number, book, chapter, verse)
    fuerst_entries = []
    
    # Get manual entries if they exist
    if manual_mappings.get('fuerst_ids'):
        try:
            with get_db_connection() as conn:
                cursor = conn.cursor()
                cursor.execute("SET search_path TO old_testament")
                # Fürst IDs in database have "F" prefix (e.g., "F14745")
                # but manual_lexicon_mappings stores integers (e.g., 14745)
                fuerst_id_strings = [f'F{id}' for id in manual_mappings['fuerst_ids']]
                placeholders = ','.join(['%s'] * len(fuerst_id_strings))
                cursor.execute(
                    f"""
                    SELECT id, hebrew_word, hebrew_consonantal, part_of_speech, 
                           definition, source_page, root
                    FROM fuerst_lexicon 
                    WHERE id IN ({placeholders})
                    """,
                    fuerst_id_strings
                )
                manual_rows = cursor.fetchall()
                for row in manual_rows:
                    fuerst_entries.append({
                        'fuerst_id': row[0],
                        'hebrew_word': row[1],
                        'hebrew_consonantal': row[2],
                        'part_of_speech': row[3],
                        'definition': row[4],
                        'notes': None,
                        'source_page': row[5],
                        'root': row[6],
                        'lexeme_form': None,
                        'mapping_basis': None,
                        'confidence': None
                    })
        except Exception as e:
            print(f"Error fetching manual Fuerst entries: {e}")
    
    # Also get automatic Strong's-based lookup and merge
    auto_entries = get_fuerst_entries_for_strong(strong_number)
    if auto_entries:
        # Add automatic entries, avoiding duplicates
        seen_ids = {e.get('fuerst_id') for e in fuerst_entries}
        for entry in auto_entries:
            if entry.get('fuerst_id') not in seen_ids:
                fuerst_entries.append(entry)
    
    if not fuerst_entries:
        return ''

    entry_blocks: list[str] = []
    for entry in fuerst_entries:
        headword = (
            entry['hebrew_word']
            or entry['hebrew_consonantal']
            or entry['lexeme_form']
            or strong_ref
        )
        headword_html = html.escape(headword)
        definition_html = html.escape(entry['definition']) if entry['definition'] else ''

        meta_parts = []
        if entry['part_of_speech']:
            meta_parts.append(html.escape(entry['part_of_speech']))
        if entry['root']:
            meta_parts.append(f"Root {html.escape(entry['root'])}")

        mapping = entry['mapping_basis'].title() if entry['mapping_basis'] else ''
        confidence = entry['confidence'].title() if entry['confidence'] else ''
        match_label = ' / '.join(filter(None, [mapping, confidence]))
        if match_label:
            meta_parts.append(match_label)

        page_url = build_fuerst_page_url(entry['source_page'])
        link_label = format_fuerst_page_label(entry['source_page']) if entry['source_page'] else ''
        link_html = ''
        if page_url:
            link_html = (
                f'<a href="{page_url}" target="_blank" rel="noopener noreferrer" '
                f'class="fuerst-link">{html.escape(link_label)}</a>'
            )
        elif entry['source_page']:
            # Ensure we pass a str to html.escape to avoid type-checker errors when entry['source_page'] is None/unknown
            link_html = html.escape(str(entry['source_page'] or ''))

        meta_html = ''
        meta_segments = meta_parts[:]
        if link_html:
            meta_segments.append(link_html)
        if meta_segments:
            meta_html = '<div class="fuerst-meta">' + ' &bull; '.join(meta_segments) + '</div>'

        note_html = ''
        if entry['notes']:
            note_text = html.escape(entry['notes'])
            note_html = f'<div class="fuerst-note">{note_text}</div>'

        # Add edit button with data attributes
        fuerst_id = str(entry['fuerst_id'] or '')
        edit_button_html = f'''<button type="button" class="edit-lexicon-btn" 
            data-lexicon-id="{html.escape(fuerst_id)}" 
            data-lexicon-type="fuerst"
            data-hebrew-word="{html.escape(entry['hebrew_word'] or '')}"
            data-hebrew-consonantal="{html.escape(entry['hebrew_consonantal'] or '')}"
            data-part-of-speech="{html.escape(entry['part_of_speech'] or '')}"
            data-definition="{html.escape(entry['definition'] or '')}"
            data-root="{html.escape(entry['root'] or '')}"
            data-source-page="{html.escape(entry['source_page'] or '')}"
            title="Edit this lexicon entry">
            <i class="fas fa-edit"></i>
        </button>'''

        body_parts = [f'<div class="fuerst-headword">{headword_html} {edit_button_html}</div>']
        if meta_html:
            body_parts.append(meta_html)
        if definition_html:
            body_parts.append(f'<div class="fuerst-definition">{definition_html}</div>')
        if note_html:
            body_parts.append(note_html)

        entry_blocks.append('<div class="fuerst-entry">' + ''.join(body_parts) + '</div>')

    if not entry_blocks:
        return ''

    popup_html = (
        '<span class="popup-container fuerst-popup">'
        '<span class="fuerst-trigger">F&uuml;rst</span>'
        '<div class="popup-content fuerst-popup-content" role="tooltip" aria-hidden="true">'
        '<div class="fuerst-title">F&uuml;rst Lexicon</div>'
        + ''.join(entry_blocks) +
        '</div>'
        '</span>'
    )
    return popup_html


def get_gesenius_entries_for_token(token_id: int, strongs_list: list[str] | None = None, hebrew_word: str = '', book: Optional[str] = None, chapter: Optional[int] = None, verse: Optional[int] = None):
    """Return cached Gesenius lexicon matches for a token id.

    Strategy:
    - First check for manual mappings if hebrew_word is provided
    - Search gesenius_lexicon.strongsNumbers field directly (only 56.5% coverage but accurate)
    
    """
    import re
    rows = []
    seen_gesenius_ids = set()
    manual_row_ids = set()
    # Strip suffix letters from strongs_list (be defensive if None or contains non-strings)
    strongs_list = [re.sub(r'[A-Za-z]$', '', str(s)) for s in (strongs_list or []) if s is not None]  
    #print(f"Getting Gesenius entries for token {token_id} with strongs_list={strongs_list} and hebrew_word='{hebrew_word}'")

    # First check for manual mappings
    if hebrew_word and strongs_list:
        for strong in strongs_list:
            manual_mappings = get_manual_lexicon_mappings(hebrew_word, strong, book, chapter, verse)
            if manual_mappings.get('gesenius_ids'):
                try:
                    with get_db_connection() as conn:
                        cursor = conn.cursor()
                        cursor.execute("SET search_path TO old_testament")
                        # Gesenius IDs in database have "G" prefix (e.g., "G7059")
                        # but manual_lexicon_mappings stores integers (e.g., 7059)
                        gesenius_id_strings = [f'G{id}' for id in manual_mappings['gesenius_ids']]
                        placeholders = ','.join(['%s'] * len(gesenius_id_strings))
                        cursor.execute(
                            f"""
                            SELECT "id", "hebrewWord", "hebrewConsonantal", "transliteration", 
                                   "partOfSpeech", "definition", "root", "sourcePage", "sourceUrl", "strongsNumbers",
                                   NULL AS confidence, NULL AS mapping_basis, NULL AS notes
                            FROM gesenius_lexicon 
                            WHERE "id" IN ({placeholders})
                            """,
                            gesenius_id_strings
                        )
                        manual_rows = cursor.fetchall()
                        if manual_rows:
                            rows.extend(manual_rows)
                            seen_gesenius_ids.update(manual_mappings['gesenius_ids'])
                            manual_row_ids.update(manual_rows and [row[0] for row in manual_rows])
                            #print(f"Fetched {len(manual_rows)} manual Gesenius entries for hebrew_word='{hebrew_word}', strong='{strong}'")
                except Exception as e:
                    print(f"Error fetching manual Gesenius entries: {e}")
    
    # Also search gesenius_lexicon.strongsNumbers field directly (merge with manual)
    if strongs_list:
        like_clauses = []
        params = []
        import re
        for s in strongs_list:
            # Strip suffix (a-z letters)
            base_strong = re.sub(r'[a-z]+$', '', s, flags=re.IGNORECASE)
            # Extract numeric value
            num = get_strongs_numeric_value(base_strong)
            if num is not None:
                # Match with word boundaries, handling both with/without leading zeros
                # Gesenius may have H834 or H0834, so we try both
                like_clauses.append(f'("strongsNumbers" ~ %s OR "strongsNumbers" ~ %s)')
                # Pattern without leading zeros
                params.append(f'(^|[^0-9])H{num}([^0-9]|$)')
                # Pattern with leading zeros (pad to 4 digits)
                params.append(f'(^|[^0-9])H{num:04d}([^0-9]|$)')
        
        if like_clauses:
            where_clause = ' OR '.join(like_clauses)
            sql = f"SELECT \"id\", \"hebrewWord\", \"hebrewConsonantal\", \"transliteration\", \"partOfSpeech\", \"definition\", \"root\", \"sourcePage\", \"sourceUrl\", \"strongsNumbers\", NULL AS confidence, NULL AS mapping_basis, NULL AS notes FROM old_testament.gesenius_lexicon WHERE {where_clause} ORDER BY \"strongsNumbers\" NULLS LAST, \"hebrewWord\" NULLS LAST;"
            automatic_rows = execute_query(sql, tuple(params), fetch='all') or []
            # Merge automatic rows with manual rows, avoiding duplicates
            for auto_row in automatic_rows:
                # Extract numeric ID from "G7059" format
                gid_str = str(auto_row[0])
                if gid_str.startswith('G'):
                    gid_num = int(gid_str[1:])
                    if gid_num not in seen_gesenius_ids:
                        rows.append(auto_row)
                        seen_gesenius_ids.add(gid_num)
                elif auto_row[0] not in seen_gesenius_ids:
                    rows.append(auto_row)
                    seen_gesenius_ids.add(auto_row[0])

    # If token strongs were provided, prefer rows that match a non-prefix (root) strongs number
    try:
        if strongs_list:
            before_root_filter = rows[:]
            import re
            def extract_nums_from_strongs_field(s: str) -> set:
                if not s:
                    return set()
                return set(int(n) for n in re.findall(r'H(\d{1,4})', s))

            token_nums = set()
            for s in strongs_list:
                num = get_strongs_numeric_value(s)
                if num is not None:
                    token_nums.add(num)

            # Consider root strongs as those < 9000 (function words are in the 9000s)
            token_root_nums = {n for n in token_nums if n < 9000}
            if token_root_nums:
                print(f"root strongs filter tokens={sorted(token_root_nums)}")
                preferred_rows = [r for r in rows if r[0] in manual_row_ids or extract_nums_from_strongs_field(r[9]) & token_root_nums]
                if preferred_rows:
                    print("root strongs matched rows:", [f"id={row[0]} strongs={row[9]}" for row in preferred_rows])
                    rows = preferred_rows
            _debug_filtered_rows('root strongs', before_root_filter, rows)
    except Exception:
        pass

    # Filter out short single-letter matches when there are longer matches available
    try:
        import re
        niqqud_pattern = r'[\u0591-\u05BD\u05BF\u05C1-\u05C5\u05C7]'
        def visible_len(s: str) -> int:
            if not s:
                return 0
            t = re.sub(niqqud_pattern, '', s)
            t = re.sub(r'[^\u05D0-\u05EA]', '', t)  # keep only Hebrew letters
            return len(t)

        before_visible_filter = rows[:]
        # If any row has a visible length >= 2, drop rows where both hebrewWord and hebrewConsonantal are < 2
        if any((visible_len(r[1]) >= 2 or visible_len(r[2]) >= 2) for r in rows):
            before_visible = rows[:]
            rows = [r for r in rows if r[0] in manual_row_ids or (visible_len(r[1]) >= 2 or visible_len(r[2]) >= 2)]
            filtered_out = [r for r in before_visible if r not in rows]
            if filtered_out:
                print("visible length filtered rows:", [f"id={r[0]} len_word={visible_len(r[1])} len_consonantal={visible_len(r[2])} strongs={r[9]}" for r in filtered_out])
        _debug_filtered_rows('visible length', before_visible_filter, rows)
    except Exception:
        # Be conservative if anything goes wrong - don't filter
        pass

    entries = []
    for row in rows:
        (
            gid,
            hebrewWord,
            hebrewConsonantal,
            transliteration,
            partOfSpeech,
            definition,
            root,
            sourcePage,
            sourceUrl,
            strongsNumbers,
            confidence,
            mapping_basis,
            notes,
        ) = row
        entries.append({
            'id': gid,
            'hebrew_word': hebrewWord or '',
            'hebrew_consonantal': hebrewConsonantal or '',
            'transliteration': transliteration or '',
            'part_of_speech': partOfSpeech or '',
            'definition': definition or '',
            'root': root or '',
            'source_page': sourcePage or '',
            'source_url': sourceUrl or '',
            'confidence': confidence or '',
            'mapping_basis': mapping_basis or '',
            'notes': notes or '',
        })

    return tuple(entries)


def build_gesenius_popup(entries: list[dict] | tuple[dict, ...]) -> str:
    """Render a Gesenius popup that mirrors Fürst styling and includes page image links."""
    if not entries:
        return ''

    entry_blocks: list[str] = []
    for entry in entries[:6]:  # limit popup to top 6 matches to avoid overly long popups
        headword = entry['hebrew_word'] or entry['hebrew_consonantal'] or entry['transliteration'] or ''
        headword_html = html.escape(headword)
        definition_html = html.escape(entry['definition']) if entry['definition'] else ''

        meta_parts = []
        if entry.get('part_of_speech'):
            meta_parts.append(html.escape(entry['part_of_speech']))
        if entry.get('root'):
            meta_parts.append(f"Root {html.escape(entry['root'])}")

        mapping = entry.get('mapping_basis') or ''
        confidence = entry.get('confidence') or ''
        match_label = ' / '.join(filter(None, [mapping.title() if mapping else '', confidence.title() if confidence else '']))
        if match_label:
            meta_parts.append(match_label)

        page_url = build_gesenius_page_url(entry.get('source_page', ''))
        link_label = format_gesenius_page_label(entry.get('source_page', '')) if entry.get('source_page') else ''
        link_html = ''
        if page_url:
            link_html = (
                f'<a href="{page_url}" target="_blank" rel="noopener noreferrer" class="gesenius-link">{html.escape(link_label)}</a>'
            )
        elif entry.get('source_page'):
            # Ensure we pass a str to html.escape to avoid type-checker errors when entry.get('source_page') is None/unknown
            link_html = html.escape(str(entry.get('source_page') or ''))

        meta_html = ''
        meta_segments = meta_parts[:]
        if link_html:
            meta_segments.append(link_html)
        if meta_segments:
            meta_html = '<div class="gesenius-meta">' + ' &bull; '.join(meta_segments) + '</div>'

        note_html = ''
        if entry.get('notes'):
            note_text = html.escape(entry['notes'])
            note_html = f'<div class="gesenius-note">{note_text}</div>'

        body_parts = [f'<div class="gesenius-headword">{headword_html}</div>']
        if meta_html:
            body_parts.append(meta_html)
        if definition_html:
            body_parts.append(f'<div class="gesenius-definition">{definition_html}</div>')
        if note_html:
            body_parts.append(note_html)

        entry_blocks.append('<div class="gesenius-entry">' + ''.join(body_parts) + '</div>')

    popup_html = (
        '<span class="popup-container gesenius-popup">'
        '<span class="gesenius-trigger">Gesenius</span>'
        '<div class="popup-content gesenius-popup-content" role="tooltip" aria-hidden="true">'
        '<div class="gesenius-title">Gesenius Lexicon</div>'
        + ''.join(entry_blocks) +
        '</div>'
        '</span>'
    )
    return popup_html


def get_strongs_numeric_value(strongs):
    digits = re.sub(r"\D", "", strongs)
    return int(digits) if digits else None


def get_lxx_stats_for_strongs(strong_refs):
    """
    Fetch LXX translation statistics for a list of Strong's numbers.
    Returns a dict mapping strongs -> list of (greek_lemma, frequency, proportion_pct)

    This function strips any trailing letters (e.g., '5869a' -> '5869') before
    constructing the canonical H-number used in `catss.strongs_lxx_profile`.
    """
    from .db_utils import execute_query
    
    stats = {}
    for strongs in strong_refs:
        # Strip any non-digit characters to get the numeric part (handles '5869a', '| 5869a', etc.)
        num = get_strongs_numeric_value(strongs)
        if num is None:
            stats[strongs] = []
            continue
        # canonical key in DB is like 'H5869'
        s = f'H{num}'
        result = execute_query("""
            SELECT greek_lemma, frequency, proportion_pct
            FROM catss.strongs_lxx_profile
            WHERE strongs = %s AND frequency >= 2
            ORDER BY frequency DESC
            LIMIT 10;
        """, (s,), fetch='all') or []
        stats[strongs] = result
    return stats


def build_heb_interlinear(rows_data):
    # Initialize rows for English and Hebrew
    english_rows = []
    hebrew_rows = []
    morph_rows = []
    strong_rows = []
    hebrew_clean = []
    interlinear_cards = []

    for index, row_data in enumerate(rows_data):
        # Handle both old (24 columns) and new (25 columns with lxx) format
        if len(row_data) >= 25:
            (
                id,
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
                strong,
                color,
                html_list,
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
                legacy_lxx,
            ) = row_data
        else:
            (
                id,
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
                strong,
                color,
                html_list,
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
            ) = row_data
            legacy_lxx = None

        parts = re.split(r'[\/|]', strong)

        strong_refs = []
        for part in parts:
            part = part.strip()
            if not part:
                continue

            subparts = [segment.strip() for segment in re.split(r'[=«]', part) if segment.strip()]

            for subpart in subparts:
                if subpart.startswith('H'):
                    strong_refs.append(subpart)

            # special numbers for particles
            if subparts and (subparts[0] == 'H9005' or subparts[0] == 'H9001' or subparts[0] == 'H9002' or subparts[0] == 'H9003' or subparts[0] == 'H9004' or subparts[0] == 'H9006'):
                    heb1 = f'<span style="color: blue;">{heb1}</span>'
                    
        # Build Strong's popup trigger
        strongs_popup = build_strongs_popup(strong_refs)
        
        # Track Fuerst IDs we've already shown for this token to avoid duplicate Fuerst popups
        seen_fuerst_ids: set = set()
        fuerst_popups = []
        for strong_ref in strong_refs:
            # Skip H9014..H9018 per site policy
            num = get_strongs_numeric_value(strong_ref)
            if num is not None and 9014 <= num <= 9018:
                continue

            # Only add a Fuerst popup if it introduces at least one new Fuerst entry
            try:
                fuerst_entries = get_fuerst_entries_for_strong(strong_ref) or ()
            except Exception:
                fuerst_entries = ()

            # Collect IDs and see if any are new
            fuerst_ids_this_ref = set()
            add_fuerst = False
            for e in fuerst_entries:
                fid = e.get('fuerst_id') if isinstance(e, dict) else None
                if fid is not None:
                    fuerst_ids_this_ref.add(fid)
                    if fid not in seen_fuerst_ids:
                        add_fuerst = True

            if add_fuerst:
                # Parse ref to extract book, chapter, verse for manual mapping lookup
                book_name = None
                chapter_num = None
                verse_num = None
                if ref:
                    ref_parts = ref.split(':')
                    if len(ref_parts) >= 2:
                        book_name = ref_parts[0].strip()
                        try:
                            chapter_num = int(ref_parts[1])
                        except (ValueError, IndexError):
                            pass
                        if len(ref_parts) >= 3:
                            try:
                                verse_num = int(ref_parts[2])
                            except (ValueError, IndexError):
                                pass
                
                fuerst_popup_html = build_fuerst_popup(
                    strong_ref, 
                    hebrew_word=combined_heb_niqqud, 
                    book=book_name, 
                    chapter=chapter_num, 
                    verse=verse_num
                )
                if fuerst_popup_html:
                    fuerst_popups.append(fuerst_popup_html)
                    seen_fuerst_ids.update(fuerst_ids_this_ref)

        # Add Gesenius popup for the token
        # Parse ref for manual mapping lookup if not already parsed
        if ref and ('book_name' not in locals() or book_name is None):
            ref_parts = ref.split(':')
            if len(ref_parts) >= 2:
                book_name = ref_parts[0].strip()
                try:
                    chapter_num = int(ref_parts[1])
                except (ValueError, IndexError):
                    chapter_num = None
                if len(ref_parts) >= 3:
                    try:
                        verse_num = int(ref_parts[2])
                    except (ValueError, IndexError):
                        verse_num = None
            else:
                book_name = None
                chapter_num = None
                verse_num = None
        
        try:
            ges_entries = get_gesenius_entries_for_token(
                id, 
                strongs_list=strong_refs,
                hebrew_word=combined_heb_niqqud,
                book=book_name if 'book_name' in locals() else None,
                chapter=chapter_num if 'chapter_num' in locals() else None,
                verse=verse_num if 'verse_num' in locals() else None
            )
        except Exception as e:
            import traceback
            print(f"Error fetching Gesenius entries: {e}")
            traceback.print_exc()
            ges_entries = ()

        ges_popup = ''
        if ges_entries:
            ges_popup = build_gesenius_popup(ges_entries)
        
        # Combine all popups with consistent spacing
        strongs_references = strongs_popup
        if fuerst_popups:
            strongs_references = f"{strongs_references} {''.join(fuerst_popups)}"
        if ges_popup:
            strongs_references = f"{strongs_references} {ges_popup}"

        # Join parts without injecting extra spaces so prefixes stay attached to the word
        hebrew_parts = [heb1, heb2, heb3, heb4, heb5, heb6]
        combined_hebrew = ''.join(part or '' for part in hebrew_parts)
        if not combined_hebrew.strip():
            combined_hebrew = combined_heb_niqqud or ''

        hebrew_parts_clean = [heb1_n, heb2_n, heb3_n, heb4_n, heb5_n, heb6_n]
        combined_hebrew_clean = ''.join(part or '' for part in hebrew_parts_clean)
        if not combined_hebrew_clean.strip():
            combined_hebrew_clean = combined_heb or ''

        at_list = [
            'אָתֶ', 'אֹתִ', 'אתֹ', 'אֹתֵ', 'אֶתֶּ', 'אֵתֻ', 'אַתֵ', 'אתִ', 'אֵתֵ', 'אָתֻ', 'אֵתֶּ', 'אַתִ', 'אֻתֵ', 'אַתּ',
            'את', 'אַת', 'אָתֶּ', 'אתֶ', 'אֵת', 'אֻתַ', 'אתֵ', 'אֹתֻ', 'אִתּ', 'אֵתָ', 'אתֻ', 'אתֶּ', 'אֻתֶּ', 'אֶת', 'אּתֹ',
            'אתּ', 'אּתֻ', 'אֶתֻ', 'אֹת', 'אֹתֶ', 'אֶתָ', 'אּת', 'אָתִ', 'אִתֹ', 'אֹתָ', 'אֻתּ', 'אַתֶּ', 'אָת', 'אֶתּ',
            'אַתֻ', 'את', 'אֹתּ', 'אָתָ', 'אַתָ', 'אַתַ', 'אָתּ', 'אֶתֵ', 'אּתֶּ', 'אּתֵ', 'אִתֶּ', 'אּתִ', 'אֻתָ', 'אֵתִ',
            'אִתֵ', 'אּתָ', 'אֻתֻ', 'אֻת', 'אֻתִ', 'אּתּ', 'אֶתֹ', 'אָתֹ', 'אֵתֶ', 'אֶתִ', 'אִתִ', 'אַתֶ', 'אִתֶ', 'אֵתֹ',
            'אּתַ', 'אֵתּ', 'אָתַ', 'אֶתַ', 'אֶתֶ', 'אָתֵ', 'אִתַ', 'אֹתֶּ', 'אֻתֶ', 'אִתֻ', 'אֻתֹ', 'אַתֹ', 'אֵתַ', 'אתָ',
            'אתַ', 'אֹתֹ', 'אֹתַ', 'אִת', 'אּתֶ', 'אִתָ'
        ]

        # Iterate through the words in the at_list
        for at in at_list:
            # Check if the word exists in the Hebrew text
            if at in combined_hebrew:
                # Replace the word with the same word wrapped in HTML tags for highlighting
                combined_hebrew = combined_hebrew.replace(at, f'<span style="color: #f00;">{at}</span>')

        strong_cell = f'<td class="strong-cell">{strongs_references}</td>'
        display_english = eng
        # Check if H1961 is in strong_refs for hayah highlighting
        if 'H1961' in strong_refs:
            display_english = f'<span class="hayah">{eng}</span>'
        english_cell = f'<td>{display_english}</td>'
        hebrew_cell = f'<td>{combined_hebrew}</td>'

        morph_color = ""

        # Determine the color based on the presence of 'f' or 'm'
        if 'f' in morph:
            morph_color = 'style="color: #FF1493;"'
        elif 'm' in morph:
            morph_color = 'style="color: blue;"'
        
        if 'feminine' in morphology:
            morphology = f'<font style="color: #FF1493;">{morphology}</font>'
        elif 'masculine' in morphology:
            morphology = f'<font style="color: blue;">{morphology}</font>'

        morph_cell = f'<td style="font-size: 12px;" class="morph-cell"><input type="hidden" id="code" value="{morph}"/><div {morph_color}>{morph}</div><div class="morph-popup" id="morph"></div></td>'

        #morph_cell = f'<td style="font-size: 12px;" class="morph-cell"><input type="hidden" id="code" value="{morph}"/>{morph}<div class="morph-popup" id="morph"></div></td>'

        # Append cells to current row
        strong_rows.append(strong_cell)
        english_rows.append(english_cell)
        hebrew_rows.append(hebrew_cell)
        morph_rows.append(morph_cell)
        hebrew_clean.append(combined_hebrew_clean)

        # Process LXX data and fetch stats for each Strong's number (skip 9000+)
        lxx_words: list[str] = []
        lxx_data: list[dict[str, object]] = []
        strongs_for_lxx = [
            strong for strong in strong_refs
            if (num := get_strongs_numeric_value(strong)) is not None and num < 9000
        ]

        if strongs_for_lxx:
            lxx_stats = get_lxx_stats_for_strongs(strongs_for_lxx)
            seen_greek: set[str] = set()
            for strongs in strongs_for_lxx:
                stats_list = lxx_stats.get(strongs, [])
                if stats_list:
                    for grk, _, _ in stats_list[:5]:
                        if grk not in seen_greek:
                            lxx_words.append(grk)
                            seen_greek.add(grk)

                lxx_data.append({
                    'strongs': strongs,
                    'words': lxx_words[:],
                    'stats': stats_list,
                })

        if not lxx_words and legacy_lxx:
            parsed_words = re.split(r'[\s,]+', legacy_lxx.strip())
            lxx_words = [w.strip() for w in parsed_words if w.strip()]

        interlinear_cards.append({
            'id': id,
            'hebrew': combined_hebrew,
            'english': display_english,
            'strongs': strongs_references,
            'strongs_list': strong_refs,
            'morph': morphology,
            'lxx': ' '.join(lxx_words) if lxx_words else '',
            'lxx_words': lxx_words,
            'lxx_data': lxx_data,
        })

    return strong_rows, english_rows, hebrew_rows, morph_rows, hebrew_clean, interlinear_cards

def find_verb_morph(input_verb):
    """
    Find and print all individual Hebrew form matches for the input_verb in table_data.
    
    Args:
    input_verb (str): The Hebrew verb to match.
    table_data (list of dict): The table data containing patterns to match against.
    """

    ### Function to detects possible verb forms
    table_data = [
        # Complete forms
        {'Form': 'Complete', 'Person': '3rd masculine singular', 'Qal': '׳׳׳', 'Niphal': 'נ׳׳׳', 'Piel': '׳׳׳', 'Pual': '׳׳׳', 'Hiphil': 'ה׳׳י׳', 'Hophal': 'ה׳׳׳', 'Hithpael': 'הת׳׳׳'},
        {'Form': 'Complete', 'Person': '3rd feminine singular', 'Qal': '׳׳׳ה', 'Niphal': 'נ׳׳׳ה', 'Piel': '׳׳׳ה', 'Pual': '׳׳׳ה', 'Hiphil': 'ה׳׳י׳ה', 'Hophal': 'ה׳׳׳ה', 'Hithpael': 'הת׳׳׳ה'},
        {'Form': 'Complete', 'Person': '2nd masculine singular', 'Qal': '׳׳׳ת', 'Niphal': 'נ׳׳׳ת', 'Piel': '׳׳׳ת', 'Pual': '׳׳׳ת', 'Hiphil': 'ה׳׳׳ת', 'Hophal': 'ה׳׳׳ת', 'Hithpael': 'הת׳׳׳ת'},
        {'Form': 'Complete', 'Person': '2nd feminine singular', 'Qal': '׳׳׳ת', 'Niphal': 'נ׳׳׳ת', 'Piel': '׳׳׳ת', 'Pual': '׳׳׳ת', 'Hiphil': 'ה׳׳׳ת', 'Hophal': 'ה׳׳׳ת', 'Hithpael': 'הת׳׳׳ת'},
        {'Form': 'Complete', 'Person': '1st common singular', 'Qal': '׳׳׳תי', 'Niphal': 'נ׳׳׳תי', 'Piel': '׳׳׳תי', 'Pual': '׳׳׳תי', 'Hiphil': 'ה׳׳׳תי', 'Hophal': 'ה׳׳׳תי', 'Hithpael': 'הת׳׳׳תי'},
        {'Form': 'Complete', 'Person': '3rd common plural', 'Qal': '׳׳׳ו', 'Niphal': 'נ׳׳׳ו', 'Piel': '׳׳׳ו', 'Pual': '׳׳׳ו', 'Hiphil': 'ה׳׳י׳ו', 'Hophal': 'ה׳׳׳ו', 'Hithpael': 'הת׳׳׳ו'},
        {'Form': 'Complete', 'Person': '2nd masculine plural', 'Qal': '׳׳׳תם', 'Niphal': 'נ׳׳׳תם', 'Piel': '׳׳׳תם', 'Pual': '׳׳׳תם', 'Hiphil': 'ה׳׳׳תם', 'Hophal': 'ה׳׳׳תם', 'Hithpael': 'הת׳׳׳תם'},
        {'Form': 'Complete', 'Person': '1st common plural', 'Qal': '׳׳׳תן', 'Niphal': 'נ׳׳׳תן', 'Piel': '׳׳׳תן', 'Pual': '׳׳׳תן', 'Hiphil': 'ה׳׳׳תן', 'Hophal': 'ה׳׳׳תן', 'Hithpael': 'הת׳׳׳תן'},
        {'Form': 'Complete', 'Person': '1st common plural', 'Qal': '׳׳׳נו', 'Niphal': 'נ׳׳׳נו', 'Piel': '׳׳׳נו', 'Pual': '׳׳׳נו', 'Hiphil': 'ה׳׳׳נו', 'Hophal': 'ה׳׳׳נו', 'Hithpael': 'הת׳׳׳נו'},
        
        # Incomplete forms
        {'Form': 'Incomplete', 'Person': '3rd masculine singular', 'Qal': 'י׳׳׳', 'Niphal': 'י׳׳׳', 'Piel': 'י׳׳׳', 'Pual': 'י׳׳׳', 'Hiphil': 'י׳׳י׳', 'Hophal': 'י׳׳׳', 'Hithpael': 'ית׳׳׳'},
        {'Form': 'Incomplete', 'Person': '3rd feminine singular', 'Qal': 'ת׳׳׳', 'Niphal': 'ת׳׳׳', 'Piel': 'ת׳׳׳', 'Pual': 'ת׳׳׳', 'Hiphil': 'ת׳׳י׳', 'Hophal': 'ת׳׳׳', 'Hithpael': 'תת׳׳׳'},
        {'Form': 'Incomplete', 'Person': '2nd masculine singular', 'Qal': 'ת׳׳׳', 'Niphal': 'ת׳׳׳', 'Piel': 'ת׳׳׳', 'Pual': 'ת׳׳׳', 'Hiphil': 'ת׳׳י׳', 'Hophal': 'ת׳׳׳', 'Hithpael': 'תת׳׳׳'},
        {'Form': 'Incomplete', 'Person': '2nd feminine singular', 'Qal': 'ת׳׳׳י', 'Niphal': 'ת׳׳׳י', 'Piel': 'ת׳׳׳י', 'Pual': 'ת׳׳׳י', 'Hiphil': 'ת׳׳י׳י', 'Hophal': 'ת׳׳׳י', 'Hithpael': 'תת׳׳׳י'},
        {'Form': 'Incomplete', 'Person': '1st common singular', 'Qal': 'א׳׳׳', 'Niphal': 'א׳׳׳', 'Piel': 'א׳׳׳', 'Pual': 'א׳׳׳', 'Hiphil': 'א׳׳י׳', 'Hophal': 'א׳׳׳', 'Hithpael': 'את׳׳׳'},
        {'Form': 'Incomplete', 'Person': '3rd masculine plural', 'Qal': 'י׳׳׳ו', 'Niphal': 'י׳ת׳ו', 'Piel': 'י׳׳׳ו', 'Pual': 'י׳׳׳ו', 'Hiphil': 'י׳׳י׳ו', 'Hophal': 'י׳׳׳ו', 'Hithpael': 'ית׳׳׳ו'},
        {'Form': 'Incomplete', 'Person': '3rd feminine plural', 'Qal': 'ת׳׳׳נה', 'Niphal': 'ת׳׳׳נה', 'Piel': 'ת׳׳׳נה', 'Pual': 'ת׳׳׳נה', 'Hiphil': 'ת׳׳׳נה', 'Hophal': 'ת׳׳׳נה', 'Hithpael': 'תת׳׳׳נה'},
        {'Form': 'Incomplete', 'Person': '2nd masculine plural', 'Qal': 'ת׳׳׳ו', 'Niphal': 'ת׳׳׳ו', 'Piel': 'ת׳׳׳ו', 'Pual': 'ת׳׳׳ו', 'Hiphil': 'ת׳׳י׳ו', 'Hophal': 'ת׳׳׳ו', 'Hithpael': 'תת׳׳׳ו'},
        {'Form': 'Incomplete', 'Person': '2nd feminine plural', 'Qal': 'ת׳׳׳נה', 'Niphal': 'ת׳׳׳נה', 'Piel': 'ת׳׳׳נה', 'Pual': 'ת׳׳׳נה', 'Hiphil': 'ת׳׳׳נה', 'Hophal': 'ת׳׳׳נה', 'Hithpael': 'תת׳׳׳נה'},
        {'Form': 'Incomplete', 'Person': '1st common plural', 'Qal': 'נ׳׳׳', 'Niphal': 'נ׳׳׳', 'Piel': 'נ׳׳׳', 'Pual': 'נ׳׳׳', 'Hiphil': 'נ׳׳י׳', 'Hophal': 'נ׳׳׳', 'Hithpael': 'נת׳׳׳'},
        
        # Imperative forms
        {'Form': 'Imperative', 'Person': '2nd masculine singular', 'Qal': '׳׳׳', 'Niphal': 'ה׳׳׳', 'Piel': '׳׳׳', 'Pual': '', 'Hiphil': 'ה׳׳׳', 'Hophal': '', 'Hithpael': 'הת׳׳׳'},
        {'Form': 'Imperative', 'Person': '2nd feminine singular', 'Qal': '׳׳׳י', 'Niphal': 'ה׳׳׳י', 'Piel': '׳׳׳י', 'Pual': '', 'Hiphil': 'ה׳׳י׳י', 'Hophal': '', 'Hithpael': 'הת׳׳׳י'},
        {'Form': 'Imperative', 'Person': '2nd masculine singular', 'Qal': '׳׳׳ו', 'Niphal': 'ה׳׳׳ו', 'Piel': '׳׳׳ו', 'Pual': '', 'Hiphil': 'ה׳׳י׳ו', 'Hophal': '', 'Hithpael': 'הת׳׳׳ו'},
        {'Form': 'Imperative', 'Person': '2nd feminine plural', 'Qal': '׳׳׳נה', 'Niphal': 'ה׳׳׳נה', 'Piel': '׳׳׳נה', 'Pual': '', 'Hiphil': 'ה׳׳׳נה', 'Hophal': '', 'Hithpael': 'הת׳׳׳נה'},
        
        # Infinitive forms
        {'Form': 'Infinitive Construct', 'Person': '', 'Qal': '׳׳׳', 'Niphal': 'ה׳׳׳', 'Piel': '׳׳׳', 'Pual': '׳׳׳', 'Hiphil': 'ה׳׳י׳', 'Hophal': 'ה׳׳׳', 'Hithpael': 'הת׳׳׳'},
        {'Form': 'Infinitive Absolute', 'Person': '', 'Qal': '׳׳ו׳', 'Niphal': 'נ׳׳׳', 'Piel': '׳׳׳', 'Pual': '׳׳׳', 'Hiphil': 'ה׳׳׳', 'Hophal': 'ה׳׳׳', 'Hithpael': 'הת׳׳׳'},
        
        # Participle forms
        {'Form': 'Participle Active', 'Person': '', 'Qal': '׳׳׳', 'Niphal': '', 'Piel': 'מ׳׳׳', 'Pual': '', 'Hiphil': 'מ׳׳י׳', 'Hophal': '', 'Hithpael': 'מת׳׳׳'},
        {'Form': 'Participle Passive', 'Person': '', 'Qal': '׳׳ו׳', 'Niphal': 'נ׳׳׳', 'Piel': '', 'Pual': 'מ׳׳׳', 'Hiphil': '', 'Hophal': 'מ׳׳׳', 'Hithpael': ''}
    ]
    
    def is_match(input_verb, pattern):
        """
        Check if input_verb matches the pattern where Garesh (׳) is used as a wildcard.
        
        Args:
        input_verb (str): The Hebrew verb to match.
        pattern (str): The pattern with Garesh (׳) used as a wildcard.
        
        Returns:
        bool: True if input_verb matches pattern, False otherwise.
        """
        # Check if the input_verb and pattern have the same length
        if len(input_verb) != len(pattern):
            return False
        
        # Compare characters, allowing Garesh (׳) to match any character
        for p_char, v_char in zip(pattern, input_verb):
            if p_char != '׳' and p_char != v_char:
                return False
        
        return True

    results = []
    
    for row in table_data:
        form_matches = {
            'Form': row.get('Form', ''),
            'Person': row.get('Person', '')
        }
        for key, value in row.items():
            if key not in ['Form', 'Person'] and value:
                if is_match(input_verb, value):
                    form_matches[key] = value
        
        # Include only rows with at least one matching form and retain 'Form' and 'Person'
        if len(form_matches) > 2:  # At least 'Form' and 'Person' should be there
            results.append(form_matches)

    return results


def greek_lookup(lemma):
    # redirect to appropriate lemmas for greek lexicon lookup
    if lemma in [
        'α', 'ἅ', 'ἃ', 'αι', 'αἵ', 'αἳ', 'αις', 'αἷς', 'ας', 'ἃς', 'η', 'ἣ', 'ᾗ', 'ην', 'ἥν', 'ἣν', 
        'ης', 'ἧς', 'Ο', 'ὁ', 'ὅ', 'ὃ', 'οι', 'οἵ', 'οἳ', 'οις', 'οἷς', 'ον', 'ὃν', 'ος', 'ὅς', 
        'ὃς', 'όσα', 'ὅσα', 'ὅσοι', 'όστις', 'ου', 'οὗ', 'ουν', 'ους', 'οὓς', 'οφ', 'του', 'τούτων', 
        'των', 'ω', 'ᾧ', 'ων', 'ὧν', 'ως'
    ]:
        lemma = 'ὅς'
        
    elif lemma in [
        'ὁ', 'ὅ', 'ὃ', 'ο', 'ὃς',  # masculine singular
        'ἡ', 'ἥ', 'ἧ', 'ἣ', 'ἡς', 'ἥς',  # feminine singular
        'τό', 'τὸ', 'τῶ', 'τὸν', 'τὴν',  # neuter singular
        'οἱ', 'ὅι', 'ὅς', 'ὅν', 'οἷς',  # masculine plural
        'αἱ', 'αἵ', 'αἳ', 'αἷς',  # feminine plural
        'τά', 'τὰ', 'τῶν', 'τῷς', 'τὸν', 'τὴν'  # neuter plural
    ]:
        lemma = 'ὁ'
    
    return lemma
