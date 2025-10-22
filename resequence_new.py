import psycopg2
import os
import re
from collections import defaultdict
from datetime import datetime

def get_db_connection():
    """Get PostgreSQL database connection"""
    database_url = os.environ.get('DATABASE_URL')
    if database_url:
        return psycopg2.connect(database_url)
    else:
        # Fallback for local development
        return psycopg2.connect(
            host='localhost',
            database='rbt',
            user='matt',
            password='Malachi46'
        )

class ValidationLogger:
    """Logs validation results and discrepancies"""
    def __init__(self, log_file='footnote_validation.log'):
        # Clear log file on new run
        with open(log_file, 'w') as f:
            f.write(f"Validation Log Started: {datetime.now().isoformat()}\n")
            
        self.log_file = log_file
        self.discrepancies = []
        self.stats = {
            'total_verses': 0,
            'total_footnotes': 0,
            'successful_mappings': 0,
            'missing_content': 0,
            'content_mismatches': 0,
            'validation_errors': 0,
            'link_book_mismatches': 0
        }
        
    def log(self, message, level='INFO'):
        """Log a message with timestamp"""
        timestamp = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        log_entry = f"[{timestamp}] [{level}] {message}\n"
        with open(self.log_file, 'a') as f:
            f.write(log_entry)
        print(log_entry.strip())
    
    def log_discrepancy(self, discrepancy_type, verse_id, original_id, new_id, details):
        """Log a content discrepancy"""
        discrepancy = {
            'type': discrepancy_type,
            'verse_id': verse_id,
            'original_footnote_id': original_id,
            'new_footnote_id': new_id,
            'details': details,
            'timestamp': datetime.now().isoformat()
        }
        self.discrepancies.append(discrepancy)
        self.log(f"DISCREPANCY: {discrepancy_type} in {verse_id} - {details}", 'ERROR')
        if discrepancy_type in self.stats:
            self.stats[discrepancy_type] += 1
        else:
            self.stats['validation_errors'] += 1
    
    def write_summary(self):
        """Write validation summary report"""
        summary_file = self.log_file.replace('.log', '_summary.txt')
        with open(summary_file, 'w') as f:
            f.write("=" * 80 + "\n")
            f.write("FOOTNOTE RESEQUENCING VALIDATION SUMMARY\n")
            f.write("=" * 80 + "\n\n")
            
            f.write("Statistics:\n")
            f.write("-" * 40 + "\n")
            for key, value in self.stats.items():
                f.write(f"{key.replace('_', ' ').title()}: {value}\n")
            
            f.write("\n" + "=" * 80 + "\n")
            f.write(f"Total Discrepancies: {len(self.discrepancies)}\n")
            f.write("=" * 80 + "\n\n")
            
            if self.discrepancies:
                f.write("DISCREPANCY DETAILS:\n")
                f.write("-" * 80 + "\n")
                for i, disc in enumerate(self.discrepancies, 1):
                    f.write(f"\n{i}. {disc['type']}\n")
                    f.write(f"   Verse: {disc['verse_id']}\n")
                    f.write(f"   Original ID: {disc['original_footnote_id']}\n")
                    f.write(f"   New ID: {disc['new_footnote_id']}\n")
                    f.write(f"   Details: {disc['details']}\n")
            else:
                f.write("✓ No discrepancies found - all validations passed!\n")
        
        self.log(f"Summary written to {summary_file}")

def normalize_html(html):
    """Normalize HTML for comparison by removing whitespace variations"""
    if html is None:
        return ""
    # Remove extra whitespace
    html = re.sub(r'\s+', ' ', html)
    # Remove whitespace around tags
    html = re.sub(r'>\s+<', '><', html)
    return html.strip()

def get_footnote_table_name(book_abbrev):
    """Helper to get the consistent footnote table name"""
    if book_abbrev[0].isdigit():
        table_name = f"table_{book_abbrev}_footnotes"
    else:
        table_name = f"{book_abbrev}_footnotes"
    return table_name.lower()

def get_original_footnote(cursor, footnote_id, book, nt_abbrev, source_schema):
    """
    Retrieves the original footnote HTML from the appropriate footnote table.
    """
    if book not in nt_abbrev:
        return None

    table = get_footnote_table_name(book)
    possible_footnote_refs = []
    
    # Original format: Book-FootnoteID
    footnote_number = footnote_id.split('-')[-1]
    possible_footnote_refs.append(f"{book}-{footnote_number}")
    possible_footnote_refs.append(footnote_id)
    
    if '-' in footnote_id:
        parts = footnote_id.split('-')
        if len(parts) >= 3:
            possible_footnote_refs.append(f"{book}-{parts[-1]}")
    
    possible_footnote_refs.append(footnote_number)

    try:
        for footnote_ref in list(dict.fromkeys(possible_footnote_refs)):
            cursor.execute(f"SELECT footnote_html FROM {source_schema}.{table} WHERE footnote_id = %s", (footnote_ref,))
            result = cursor.fetchone()
            if result:
                return result[0]
        
        cursor.execute(f"SELECT footnote_id, footnote_html FROM {source_schema}.{table}")
        all_footnotes = cursor.fetchall()
        
        for db_footnote_id, footnote_html in all_footnotes:
            if db_footnote_id.endswith(f"-{footnote_number}") or db_footnote_id == footnote_number:
                return footnote_html
        
        return None
        
    except psycopg2.Error as e:
        print(f"  Error accessing table {table}: {e}")
        return None

def resequence_footnotes(verses_table='nt', source_schema='new_testament', target_schema='resequenced'):
    """
    Resequences footnotes by creating a new schema with resequenced tables.
    The original schema remains untouched.
    """
    logger = ValidationLogger()
    logger.log(f"Starting footnote resequencing from {source_schema} to {target_schema}")
    
    nt_abbrev = [
        'Mat', 'Mar', 'Luk', 'Joh', 'Act', 'Rom', '1Co', '2Co',
        'Gal', 'Eph', 'Php', 'Col', '1Th', '2Th', '1Ti', '2Ti',
        'Tit', 'Phm', 'Heb', 'Jam', '1Pe', '2Pe',
        '1Jo', '2Jo', '3Jo', 'Jud', 'Rev'
    ]

    with get_db_connection() as conn:
        cursor = conn.cursor()
        
        # Create new schema
        cursor.execute(f"DROP SCHEMA IF EXISTS {target_schema} CASCADE")
        cursor.execute(f"CREATE SCHEMA {target_schema}")
        logger.log(f"Created new schema: {target_schema}")
        
        # Create validation tracking table
        cursor.execute(f'''
            CREATE TABLE {target_schema}.footnote_validation (
                verse_id TEXT,
                original_footnote_id TEXT,
                new_footnote_number INTEGER,
                new_book TEXT,
                original_content TEXT,
                new_content TEXT,
                content_matches BOOLEAN,
                validation_timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        ''')

        # Create new footnote tables in target schema
        logger.log("Creating new footnote tables...")
        for book_abbrev in nt_abbrev:
            table_name = get_footnote_table_name(book_abbrev)
            cursor.execute(f'''
                CREATE TABLE {target_schema}.{table_name} (
                    footnote_number INTEGER PRIMARY KEY,
                    original_footnote_id TEXT,
                    footnote_html TEXT,
                    verse_id TEXT,
                    chapter INTEGER,
                    verse INTEGER
                )
            ''')

        # Create new verses table
        cursor.execute(f'''
            CREATE TABLE {target_schema}.{verses_table} (
                verseID TEXT PRIMARY KEY,
                book TEXT NOT NULL,
                chapter INTEGER NOT NULL,
                startVerse INTEGER NOT NULL,
                verseText TEXT NOT NULL,
                rbt TEXT,
                nt_id INTEGER NOT NULL
            )
        ''')

        # Retrieve all verses from source
        cursor.execute(f'''
            SELECT verseID, book, chapter, startVerse, verseText, rbt, nt_id
            FROM {source_schema}.{verses_table} 
            ORDER BY nt_id
        ''')
        verses = cursor.fetchall()

        # Process verses
        footnote_counters = defaultdict(int)
        footnote_mappings = {}  # original_id -> (new_id, content)

        for verse in verses:
            verseID, book, chapter, startVerse, verseText, rbt, nt_id = verse
            logger.stats['total_verses'] += 1
            
            if rbt is None:
                # Copy verse without modification
                cursor.execute(f'''
                    INSERT INTO {target_schema}.{verses_table} 
                    (verseID, book, chapter, startVerse, verseText, rbt, nt_id)
                    VALUES (%s, %s, %s, %s, %s, %s, %s)
                ''', (verseID, book, chapter, startVerse, verseText, rbt, nt_id))
                continue

            updated_html = rbt
            footnote_pattern1 = r'<a\s+class="sdfootnoteanc"\s+href="\?footnote=([^"&]+)(?:&[^"]*)?"\s*[^>]*>\s*<sup>[^<]*</sup>\s*</a>'
            footnote_pattern2 = r'<a\s+class="sdfootnoteanc"\s+href="\?footnote=([^"&]+)(?:&[^"]*)?"\s*[^>]*>\s*<sup>[^<]*</sup>[^<]*</span>[^<]*</span>[^<]*</a>'
            
            footnote_replacements = {}
            all_matches = []
            
            for match in re.finditer(footnote_pattern1, rbt):
                all_matches.append((match.group(1), match.group(0), 'pattern1'))
            
            for match in re.finditer(footnote_pattern2, rbt):
                footnote_id = match.group(1)
                if not any(m[0] == footnote_id and m[2] == 'pattern1' for m in all_matches):
                    all_matches.append((footnote_id, match.group(0), 'pattern2'))
            
            for original_footnote_id, full_match, pattern_type in all_matches:
                logger.stats['total_footnotes'] += 1
                
                if original_footnote_id not in footnote_replacements:
                    footnote_html = get_original_footnote(cursor, original_footnote_id, book, nt_abbrev, source_schema)
                    
                    if footnote_html:
                        footnote_counter = footnote_counters[book] + 1
                        footnote_counters[book] = footnote_counter
                        
                        table_name = get_footnote_table_name(book)
                        try:
                            cursor.execute(f'''
                                INSERT INTO {target_schema}.{table_name}
                                (footnote_number, original_footnote_id, footnote_html, verse_id, chapter, verse)
                                VALUES (%s, %s, %s, %s, %s, %s)
                            ''', (footnote_counter, original_footnote_id, footnote_html, 
                                 verseID, chapter, startVerse))

                            footnote_mappings[original_footnote_id] = {
                                'new_id': footnote_counter,
                                'content': footnote_html,
                                'verse_id': verseID,
                                'book': book,
                                'chapter': chapter,
                                'verse': startVerse
                            }

                            new_replacement = f'<a class="sdfootnoteanc" href="?footnote={footnote_counter}&book={book}"><sup>{footnote_counter}</sup></a>'
                            footnote_replacements[original_footnote_id] = new_replacement
                            
                            logger.stats['successful_mappings'] += 1
                        except psycopg2.Error as e:
                            logger.log_discrepancy(
                                'DB_INSERT_ERROR',
                                verseID,
                                original_footnote_id,
                                str(footnote_counter),
                                f"Failed to insert into {table_name}: {e}"
                            )
                            continue
                    else:
                        logger.stats['missing_content'] += 1
                        logger.log_discrepancy(
                            'MISSING_CONTENT',
                            verseID,
                            original_footnote_id,
                            'N/A',
                            f"Could not find footnote content for {original_footnote_id}"
                        )
                        footnote_replacements[original_footnote_id] = full_match

            def replace_footnote(match, pattern_type):
                original_footnote_id = match.group(1)
                return footnote_replacements.get(original_footnote_id, match.group(0))
            
            updated_html = re.sub(footnote_pattern1, lambda m: replace_footnote(m, 'pattern1'), updated_html)
            updated_html = re.sub(footnote_pattern2, lambda m: replace_footnote(m, 'pattern2'), updated_html)

            # Insert updated verse into new schema
            cursor.execute(f'''
                INSERT INTO {target_schema}.{verses_table} 
                (verseID, book, chapter, startVerse, rbt, verseText, nt_id)
                VALUES (%s, %s, %s, %s, %s, %s, %s)
            ''', (verseID, book, chapter, startVerse, updated_html, verseText, nt_id))

        # Validate the resequencing
        logger.log("\n" + "="*80)
        logger.log("Starting validation phase")
        logger.log("="*80)
        
        validate_resequencing(cursor, target_schema, source_schema, verses_table, footnote_mappings, logger)
        
        conn.commit()
        logger.log(f"\nResequencing complete. Total footnotes processed: {logger.stats['total_footnotes']}")
        logger.log(f"New tables created in schema: {target_schema}")
        
        logger.write_summary()
        return logger

def validate_resequencing(cursor, target_schema, source_schema, verses_table, footnote_mappings, logger):
    """
    Validates that new footnote links in the target schema point to the 
    same content as the original footnotes.
    """
    logger.log("Validating footnote content integrity...")
    
    cursor.execute(f'''
        SELECT verseID, book, chapter, startVerse, rbt
        FROM {target_schema}.{verses_table}
        WHERE rbt LIKE %s
    ''', ('%<a class="sdfootnoteanc"%',))
    
    updated_verses = cursor.fetchall()
    logger.log(f"Validating {len(updated_verses)} verses with footnotes")
    
    new_footnote_pattern = r'<a class="sdfootnoteanc" href="\?footnote=(\d+)&book=([^"]+)"><sup>\1</sup></a>'

    for verse_id, book, chapter, verse_num, rbt in updated_verses:
        new_matches = re.findall(new_footnote_pattern, rbt)
        
        for footnote_number_str, book_from_link in new_matches:
            footnote_number = int(footnote_number_str)

            if book_from_link != book:
                logger.log_discrepancy(
                    'LINK_BOOK_MISMATCH', 
                    verse_id, 
                    'N/A', 
                    str(footnote_number), 
                    f"Link book '{book_from_link}' does not match verse book '{book}'"
                )
                continue
            
            table_name = get_footnote_table_name(book)

            try:
                cursor.execute(f'''
                    SELECT original_footnote_id, footnote_html
                    FROM {target_schema}.{table_name}
                    WHERE footnote_number = %s
                ''', (footnote_number,))
                result = cursor.fetchone()
            except psycopg2.Error as e:
                logger.log_discrepancy(
                    'VALIDATION_DB_ERROR', 
                    verse_id, 
                    'N/A', 
                    str(footnote_number), 
                    f"Error querying {table_name}: {e}"
                )
                continue
            
            if result:
                original_id, stored_content = result
                
                if original_id in footnote_mappings:
                    expected_content = footnote_mappings[original_id]['content']
                    
                    normalized_stored = normalize_html(stored_content)
                    normalized_expected = normalize_html(expected_content)
                    
                    content_matches = normalized_stored == normalized_expected
                    
                    cursor.execute(f'''
                        INSERT INTO {target_schema}.footnote_validation
                        (verse_id, original_footnote_id, new_footnote_number, new_book, 
                         original_content, new_content, content_matches)
                        VALUES (%s, %s, %s, %s, %s, %s, %s)
                    ''', (verse_id, original_id, footnote_number, book, 
                          expected_content, stored_content, content_matches))
                    
                    if not content_matches:
                        logger.log_discrepancy(
                            'CONTENT_MISMATCH',
                            verse_id,
                            original_id,
                            str(footnote_number),
                            f"Content differs between original and resequenced footnote"
                        )
                else:
                    logger.log_discrepancy(
                        'MAPPING_NOT_FOUND',
                        verse_id,
                        original_id,
                        str(footnote_number),
                        "Original footnote mapping not found in tracking data"
                    )
            else:
                logger.log_discrepancy(
                    'RESEQUENCED_NOT_FOUND',
                    verse_id,
                    'UNKNOWN',
                    str(footnote_number),
                    f"New footnote #{footnote_number} not found in {table_name}"
                )
    
    cursor.execute(f'''
        SELECT 
            COUNT(*) as total,
            SUM(CASE WHEN content_matches THEN 1 ELSE 0 END) as matches,
            SUM(CASE WHEN NOT content_matches THEN 1 ELSE 0 END) as mismatches
        FROM {target_schema}.footnote_validation
    ''')
    total, matches, mismatches = cursor.fetchone()
    
    logger.log(f"\nValidation Results:")
    logger.log(f"  Total validations: {total or 0}")
    logger.log(f"  Content matches: {matches or 0}")
    logger.log(f"  Content mismatches: {mismatches or 0}")
    
    if mismatches and mismatches > 0:
        logger.log(f"  WARNING: {mismatches} content discrepancies detected!", 'WARNING')

def test_resequencing(target_schema='resequenced'):
    """
    Tests the resequenced tables in the new schema.
    """
    with get_db_connection() as conn:
        cursor = conn.cursor()
        cursor.execute(f"SET search_path TO {target_schema}")
        
        try:
            mat_table = get_footnote_table_name('Mat')
            cursor.execute(f'''
                SELECT verse_id, footnote_number, original_footnote_id, chapter, verse
                FROM {target_schema}.{mat_table}
                ORDER BY footnote_number 
                LIMIT 10
            ''')
            print(f"\nFirst 10 resequenced footnotes (from {mat_table}):")
            for row in cursor.fetchall():
                print(f"  Footnote #Mat-{row[1]}: {row[0]} {row[3]}:{row[4]} (was {row[2]})")
        except psycopg2.Error as e:
            print(f"\nCould not query '{mat_table}' for test: {e}")
        
        cursor.execute(f'''
            SELECT verse_id, original_footnote_id, new_footnote_number, content_matches
            FROM {target_schema}.footnote_validation
            WHERE NOT content_matches
            LIMIT 10
        ''')
        mismatches = cursor.fetchall()
        if mismatches:
            print("\nContent mismatches found:")
            for row in mismatches:
                print(f"  {row[0]}: {row[1]} -> {row[2]}")
        else:
            print("\n✓ All content validations passed!")

if __name__ == "__main__":
    SOURCE_SCHEMA = 'new_testament'
    TARGET_SCHEMA = 'resequenced'

    print(f"Starting footnote resequencing from {SOURCE_SCHEMA} to {TARGET_SCHEMA}...\n")
    logger = resequence_footnotes(source_schema=SOURCE_SCHEMA, target_schema=TARGET_SCHEMA)
    test_resequencing(TARGET_SCHEMA)
    
    print(f"\nValidation complete. Check {logger.log_file} for detailed results.")
    print(f"Summary report: {logger.log_file.replace('.log', '_summary.txt')}")
    print(f"\nResequenced tables are in schema: {TARGET_SCHEMA}")
    print("To use the new tables, update your application's schema to point to this schema.")