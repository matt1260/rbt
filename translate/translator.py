import re
import json
from .db_utils import get_db_connection, execute_query
import os

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

rbt_books = {
    'Genesis': 'In the Head',
    'Exodus': 'A Mighty One of Names',
    'Leviticus': 'He is Reading',
    'Numbers': 'He is Arranging Words',
    'Deuteronomy': 'A Mighty One of Words',
    'Song of Solomon': 'Song of Singers',
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
    sanitized_book = book.replace(' ', '_')

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
    replacements = []

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
        if json_string[0] == '"' and json_string[-1] == '"':
            json_string = json_string[1:-1]
        json_string = json_string.replace("\\", "")

        replacements = json.loads(json_string)

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
    if len(strong_ref) == 6:
        last_character = strong_ref[-1]
    else:
        last_character = '' 

    strong_number = re.sub(r'[^0-9]', '', strong_ref)
    strong_number = int(strong_number)
    strong_number = str(strong_number)
    strong_ref = strong_number + last_character
    if strong_ref == '1961':
        hayah = True
    strong_link = f'<a href="https://biblehub.com/hebrew/{strong_ref}.htm" target="_blank">{strong_ref}</a>'
    
    strong_number = 'H' + strong_number
    # Fetch the Strong's dictionary entry
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
        lemma = result[0]
        xlit = result[1]
        derivation = result[2]
        definition = result[3]
        description = result[4]
    else:
        definition = 'Definition not found'
        lemma = ''
        derivation = ''
        xlit = ''
        description = ''
    
    single_ref = f'<div class="popup-container">{strong_link}<div class="popup-content"><font size="14">{lemma}</font><br>{xlit}<br><b>Definition: </b>{definition}<br><b>Root: </b>{derivation}<br><b>Exhaustive: </b>{description}</div></div>'
    
    return single_ref


def build_heb_interlinear(rows_data):
    # Initialize rows for English and Hebrew
    english_rows = []
    hebrew_rows = []
    morph_rows = []
    strong_rows = []
    hebrew_clean = []

    for index, row_data in enumerate(rows_data):
        id, ref, eng, heb1, heb2, heb3, heb4, heb5, heb6, morph, unique, strong, color, html_list, heb1_n, heb2_n, heb3_n, heb4_n, heb5_n, heb6_n, combined_heb, combined_heb_niqqud, footnote = row_data

        parts = strong.split('/')

        strong_refs = []
        for part in parts:
            subparts = re.split(r'[=«]', part)

            for subpart in subparts:
                if subpart.startswith('H'):
                    strong_refs.append(subpart)

            # special numbers for particles
            if subparts[0] == 'H9005' or subparts[0] == 'H9001' or subparts[0] == 'H9002' or subparts[0] == 'H9003' or subparts[0] == 'H9004' or subparts[0] == 'H9006':
                    heb1 = f'<span style="color: blue;">{heb1}</span>'
                    
        # Get the definitions for each Strong's reference
        definitions = []
        lemmas = []
        derivations = []
        strong_links = []
        strongs_references = []
        hayah = False
        
        for strong_ref in strong_refs:

            single_ref = strong_data(strong_ref)

            strongs_references.insert(0, single_ref)

        strongs_references = ' | '.join(strongs_references)

        
        #combined_hebrew = f"{heb1 or ''} {heb2 or ''} {heb3 or ''} {heb4 or ''} {heb5 or ''} {heb6 or ''}".replace(' ', '')
        combined_hebrew = f"{heb1 or ''} {heb2 or ''} {heb3 or ''} {heb4 or ''} {heb5 or ''} {heb6 or ''}"
        combined_hebrew_clean = f"{heb1_n or ''} {heb2_n or ''} {heb3_n or ''} {heb4_n or ''} {heb5_n or ''} {heb6_n or ''}"

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
        if hayah == True:
            eng = f'<span class="hayah">{eng}</span>'
        english_cell = f'<td>{eng}</td>'
        hebrew_cell = f'<td>{combined_hebrew}</td>'

        morph_color = ""

        # Determine the color based on the presence of 'f' or 'm'
        if 'f' in morph:
            morph_color = 'style="color: #FF1493;"'
        elif 'm' in morph:
            morph_color = 'style="color: blue;"'

        morph_cell = f'<td style="font-size: 12px;" class="morph-cell"><input type="hidden" id="code" value="{morph}"/><div {morph_color}>{morph}</div><div class="morph-popup" id="morph"></div></td>'

        #morph_cell = f'<td style="font-size: 12px;" class="morph-cell"><input type="hidden" id="code" value="{morph}"/>{morph}<div class="morph-popup" id="morph"></div></td>'

        # Append cells to current row
        strong_rows.append(strong_cell)
        english_rows.append(english_cell)
        hebrew_rows.append(hebrew_cell)
        morph_rows.append(morph_cell)
        hebrew_clean.append(combined_hebrew_clean)

    return strong_rows, english_rows, hebrew_rows, morph_rows, hebrew_clean



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
