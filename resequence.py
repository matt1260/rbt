import sqlite3
import re
from collections import defaultdict

def resequence_footnotes(db_path='rbt_new_testament.sqlite3', verses_table='nt_old', output_table='nt'):
    """
    Resequences footnotes per book and stores updated verses in a new table.
    """
    nt_abbrev = [
        'Mat', 'Mar', 'Luk', 'Joh', 'Act', 'Rom', '1Co', '2Co',
        'Gal', 'Eph', 'Php', 'Col', '1Th', '2Th', '1Ti', '2Ti',
        'Tit', 'Phm', 'Heb', 'Jam', '1Pe', '2Pe',
        '1Jo', '2Jo', '3Jo', 'Jud', 'Rev'
    ]

    with sqlite3.connect(db_path) as conn:
        cursor = conn.cursor()

        # Create or reset resequenced_footnotes table
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS resequenced_footnotes (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                verse_id TEXT,
                footnote_number INTEGER,
                original_footnote_id TEXT,
                footnote_html TEXT,
                book TEXT,
                chapter INTEGER,
                verse INTEGER
            )
        ''')
        cursor.execute('DELETE FROM resequenced_footnotes')

        # Create or reset output verse table
        cursor.execute(f'''
            CREATE TABLE IF NOT EXISTS {output_table} AS 
            SELECT * FROM {verses_table} WHERE 0
        ''')
        cursor.execute(f'DELETE FROM {output_table}')

        # Retrieve all verses
        cursor.execute(f'''
            SELECT verseID, book, chapter, startVerse, verseText, rbt, nt_id
            FROM {verses_table} 
            ORDER BY nt_id
        ''')
        verses = cursor.fetchall()

        # Per-book footnote counters
        footnote_counters = defaultdict(int)
        total_footnotes = 0

        for verse in verses:
            verseID, book, chapter, startVerse, verseText, rbt, nt_id = verse
            if rbt is None:
                # Copy verse with null rbt without modification
                cursor.execute(f'''
                    INSERT INTO {output_table} (verseID, book, chapter, startVerse, verseText, rbt, nt_id)
                    VALUES (?, ?, ?, ?, ?, ?, ?)
                ''', (verseID, book, chapter, startVerse, verseText, rbt, nt_id))
                continue

            print(f"Processing {book} {chapter}:{startVerse}")
            updated_html = rbt

            # Primary pattern for well-formed footnote links
            footnote_pattern1 = r'<a\s+class="sdfootnoteanc"\s+href="\?footnote=([^"&]+)(?:&[^"]*)?"\s*[^>]*>\s*<sup>[^<]*</sup>\s*</a>'
            
            # Secondary pattern for malformed footnote links (like with extra </span> tags)
            footnote_pattern2 = r'<a\s+class="sdfootnoteanc"\s+href="\?footnote=([^"&]+)(?:&[^"]*)?"\s*[^>]*>\s*<sup>[^<]*</sup>[^<]*</span>[^<]*</span>[^<]*</a>'
            
            # Create a mapping of original footnote IDs to new sequential numbers
            footnote_replacements = {}
            all_matches = []
            
            # Find matches from both patterns
            for match in re.finditer(footnote_pattern1, rbt):
                all_matches.append((match.group(1), match.group(0), 'pattern1'))
            
            for match in re.finditer(footnote_pattern2, rbt):
                # Only add if not already found by pattern1
                footnote_id = match.group(1)
                if not any(m[0] == footnote_id and m[2] == 'pattern1' for m in all_matches):
                    all_matches.append((footnote_id, match.group(0), 'pattern2'))
            
            print(f"  Found {len(all_matches)} footnote matches")
            
            # Process all matches
            for original_footnote_id, full_match, pattern_type in all_matches:
                original_footnote_id = original_footnote_id
                full_match = full_match
                
                if original_footnote_id not in footnote_replacements:
                    footnote_html = get_original_footnote(cursor, original_footnote_id, book, nt_abbrev)
                    print(f"  Footnote ID: {original_footnote_id} => Content: {footnote_html is not None}")
                    
                    if footnote_html:
                        # Resequence per book
                        footnote_counter = footnote_counters[book] + 1
                        footnote_counters[book] = footnote_counter
                        total_footnotes += 1

                        cursor.execute('''
                            INSERT INTO resequenced_footnotes 
                            (verse_id, footnote_number, original_footnote_id, footnote_html, book, chapter, verse)
                            VALUES (?, ?, ?, ?, ?, ?, ?)
                        ''', (verseID, footnote_counter, original_footnote_id, footnote_html, book, chapter, startVerse))

                        # Create new footnote reference
                        new_replacement = f'<a class="sdfootnoteanc" href="?footnote={chapter}-{startVerse}-{footnote_counter}"><sup>{footnote_counter}</sup></a>'
                        footnote_replacements[original_footnote_id] = new_replacement
                    else:
                        print(f"  Warning: Could not find footnote for {original_footnote_id}")
                        footnote_replacements[original_footnote_id] = full_match  # Keep original if not found

            # Now perform all replacements using both patterns
            def replace_footnote1(match):
                original_footnote_id = match.group(1)
                return footnote_replacements.get(original_footnote_id, match.group(0))
            
            def replace_footnote2(match):
                original_footnote_id = match.group(1)
                return footnote_replacements.get(original_footnote_id, match.group(0))
            
            # Replace footnotes using both patterns
            updated_html = re.sub(footnote_pattern1, replace_footnote1, updated_html)
            updated_html = re.sub(footnote_pattern2, replace_footnote2, updated_html)

            # Insert updated verse into output table
            cursor.execute(f'''
                INSERT INTO {output_table} (verseID, book, chapter, startVerse, rbt, verseText, nt_id)
                VALUES (?, ?, ?, ?, ?, ?, ?)
            ''', (verseID, book, chapter, startVerse, updated_html, verseText, nt_id))

        conn.commit()
        print(f"\nResequencing complete. Total footnotes processed: {total_footnotes}")
        print(f"Updated verses written to table: {output_table}")

def get_original_footnote(cursor, footnote_id, book, nt_abbrev):
    """
    Retrieves the original footnote HTML from the appropriate footnote table.
    Enhanced to handle footnote IDs with letters and various formats.
    """
    if book not in nt_abbrev:
        return None

    # Determine table name
    if book[0].isdigit():
        table = f"table_{book}_footnotes"
    else:
        table = f"{book}_footnotes"
    table = table.lower()

    # Try multiple footnote ID formats
    possible_footnote_refs = []
    
    # Original format: Book-FootnoteID
    footnote_number = footnote_id.split('-')[-1]  # Get the last part after the last dash
    possible_footnote_refs.append(f"{book}-{footnote_number}")
    
    # Alternative format: Just the footnote ID as is
    possible_footnote_refs.append(footnote_id)
    
    # Format without chapter-verse prefix if present
    if '-' in footnote_id:
        parts = footnote_id.split('-')
        if len(parts) >= 3:  # Format like "1-19-34a"
            possible_footnote_refs.append(f"{book}-{parts[-1]}")

    try:
        for footnote_ref in possible_footnote_refs:
            cursor.execute(f"SELECT footnote_html FROM {table} WHERE footnote_id = ?", (footnote_ref,))
            result = cursor.fetchone()
            if result:
                print(f"    Found footnote with ID: {footnote_ref}")
                return result[0]
        
        # If no exact match found, try searching for similar IDs
        cursor.execute(f"SELECT footnote_id, footnote_html FROM {table}")
        all_footnotes = cursor.fetchall()
        
        for db_footnote_id, footnote_html in all_footnotes:
            # Check if the footnote number matches (ignoring book prefix)
            if db_footnote_id.endswith(f"-{footnote_number}") or db_footnote_id == footnote_number:
                print(f"    Found similar footnote with ID: {db_footnote_id}")
                return footnote_html
        
        print(f"    No footnote found for any of: {possible_footnote_refs}")
        return None
        
    except sqlite3.OperationalError as e:
        print(f"  Error accessing table {table}: {e}")
        return None

def create_footnote_lookup_function():
    """
    Returns Python code for looking up resequenced footnotes by number.
    """
    return '''
def get_resequenced_footnote(footnote_number, book, db_path='rbt_new_testament.sqlite3'):
    \"""
    Retrieves resequenced footnote HTML by footnote number and book.
    \"""
    import sqlite3
    with sqlite3.connect(db_path) as conn:
        cursor = conn.cursor()
        cursor.execute(
            "SELECT footnote_html FROM resequenced_footnotes WHERE footnote_number = ? AND book = ?", 
            (footnote_number, book)
        )
        result = cursor.fetchone()
        if result:
            table_html = f'<table><tr><td>{footnote_number}</td><td>{result[0]}</td></tr></table>'
            return table_html
        return ''
'''

def test_resequencing(db_path='rbt_new_testament.sqlite3'):
    """
    Prints sample rows from the resequenced_footnotes table and shows before/after comparison.
    """
    with sqlite3.connect(db_path) as conn:
        cursor = conn.cursor()
        
        # Show resequenced footnotes
        cursor.execute('''
            SELECT verse_id, footnote_number, original_footnote_id, book, chapter, verse
            FROM resequenced_footnotes 
            ORDER BY book, footnote_number 
            LIMIT 10
        ''')
        print("\nFirst 10 resequenced footnotes:")
        for row in cursor.fetchall():
            print(f"Footnote #{row[1]} ({row[3]}): {row[0]} {row[4]}:{row[5]} (was {row[2]})")
            
        # Show a sample of the updated HTML to check for corruption
        cursor.execute('''
            SELECT book, chapter, startVerse, rbt
            FROM nt 
            WHERE rbt LIKE '%<a class="sdfootnoteanc"%' 
            LIMIT 3
        ''')
        print("\nSample updated verses:")
        for row in cursor.fetchall():
            book, chapter, verse, rbt = row
            print(f"\n{book} {chapter}:{verse}")
            # Check for HTML corruption patterns
            if '<a class="sdfootnoteanc"' in rbt and ('style="' in rbt):
                # Look for footnotes that might be inside style attributes
                corrupted_patterns = re.findall(r'style="[^"]*<a class="sdfootnoteanc"[^>]*>[^<]*</a>[^"]*"', rbt)
                if corrupted_patterns:
                    print(f"  WARNING: Possible HTML corruption detected: {corrupted_patterns}")
                else:
                    print("  HTML structure looks clean")
            
            # Extract footnote links for display
            footnote_links = re.findall(r'<a class="sdfootnoteanc"[^>]*><sup>\d+</sup></a>', rbt)
            print(f"  Footnote links: {footnote_links}")

if __name__ == "__main__":
    DATABASE_PATH = 'rbt_new_testament.sqlite3'
    VERSES_TABLE = 'nt_old'
    OUTPUT_TABLE = 'nt'

    print("Starting footnote resequencing...\n")
    resequence_footnotes(DATABASE_PATH, VERSES_TABLE, OUTPUT_TABLE)
    test_resequencing(DATABASE_PATH)

    print("\nFootnote lookup function:")
    print(create_footnote_lookup_function())