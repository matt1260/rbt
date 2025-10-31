import psycopg2
import os
import re
from datetime import datetime
from bs4 import BeautifulSoup

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

class FootnoteWrapperLogger:
    """Logs operations for adding missing span wrappers"""
    def __init__(self, log_file='footnote_wrapper_fix.log'):
        self.log_file = log_file
        self.stats = {
            'total_footnotes_processed': 0,
            'footnotes_already_wrapped': 0,
            'footnotes_fixed': 0,
            'paragraphs_wrapped': 0,
            'errors': 0
        }
        
    def log(self, message, level='INFO'):
        """Log a message with timestamp"""
        timestamp = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        log_entry = f"[{timestamp}] [{level}] {message}\n"
        with open(self.log_file, 'a') as f:
            f.write(log_entry)
        print(log_entry.strip())
    
    def write_summary(self):
        """Write summary report"""
        summary_file = self.log_file.replace('.log', '_summary.txt')
        with open(summary_file, 'w') as f:
            f.write("=" * 80 + "\n")
            f.write("FOOTNOTE WRAPPER FIX SUMMARY\n")
            f.write("=" * 80 + "\n\n")
            
            f.write("Statistics:\n")
            f.write("-" * 40 + "\n")
            for key, value in self.stats.items():
                f.write(f"{key.replace('_', ' ').title()}: {value}\n")
        
        self.log(f"Summary written to {summary_file}")

def has_rbt_footnote_class(html):
    """Check if HTML already has rbt_footnote class"""
    if not html:
        return False
    return 'class="rbt_footnote"' in html

def strip_data_attributes(html):
    """
    Strips data-* attributes from HTML tags.
    """
    # Pattern matches any data-* attribute with its value
    pattern = r'\s+data-[a-zA-Z-]+="[^"]*"'
    return re.sub(pattern, '', html)

def wrap_paragraph_content(p_tag_content, has_header_class):
    """
    Wraps the content inside a <p> tag with <span class="rbt_footnote">
    unless it already has the class or is a header.
    """
    # Skip if it's a header paragraph
    if has_header_class or 'class="footnote_header"' in p_tag_content:
        return p_tag_content
    
    # Skip if already has rbt_footnote class
    if 'class="rbt_footnote"' in p_tag_content:
        return p_tag_content
    
    # Check if paragraph has any class attribute
    class_match = re.search(r'<p([^>]*class="[^"]*"[^>]*)>', p_tag_content)
    if class_match:
        # Has a class but not rbt_footnote - add it
        p_opening = class_match.group(0)
        # Check if it's just <p class="something">
        existing_class_match = re.search(r'class="([^"]*)"', p_opening)
        if existing_class_match:
            existing_classes = existing_class_match.group(1)
            if 'rbt_footnote' not in existing_classes:
                # Add rbt_footnote to existing classes
                new_classes = f'{existing_classes} rbt_footnote'
                new_p_opening = p_opening.replace(f'class="{existing_classes}"', f'class="{new_classes}"')
                return p_tag_content.replace(p_opening, new_p_opening)
    else:
        # No class attribute - wrap content with span
        # Extract content between <p> and </p>
        content_match = re.match(r'<p([^>]*)>(.*?)</p>', p_tag_content, re.DOTALL)
        if content_match:
            p_attrs = content_match.group(1)
            inner_content = content_match.group(2).strip()
            
            # Don't wrap if content is empty or only whitespace
            if not inner_content:
                return p_tag_content
            
            # Wrap the inner content with span
            return f'<p{p_attrs}><span class="rbt_footnote">{inner_content}</span></p>'
    
    return p_tag_content

def fix_footnote_html(html):
    """
    Adds <span class="rbt_footnote"> wrapper to paragraph content that lacks it.
    Ensures all <ul> elements have rbt_footnote class.
    Strips data-* attributes from tags.
    """
    if not html:
        return html, 0
        
    html = strip_data_attributes(html)
    
    paragraphs_wrapped = 0
    ul_fixed = 0
    
    # Process <p> tags
    p_pattern = r'<p[^>]*>.*?</p>'
    paragraphs = re.findall(p_pattern, html, re.DOTALL)
    modified_html = html
    
    for p_tag in paragraphs:
        has_header_class = 'class="footnote_header"' in p_tag or '<span class="footnote_header">' in p_tag
        new_p_tag = wrap_paragraph_content(p_tag, has_header_class)
        
        if new_p_tag != p_tag:
            paragraphs_wrapped += 1
            modified_html = modified_html.replace(p_tag, new_p_tag, 1)
    
    # fix <ul> tags
    modified_html, ul_fixed = fix_ul_classes(modified_html)
    
    return modified_html, paragraphs_wrapped + ul_fixed

def get_all_footnote_tables(cursor, schema):
    """Get list of all footnote tables in the schema"""
    cursor.execute(f"""
        SELECT table_name 
        FROM information_schema.tables 
        WHERE table_schema = %s 
        AND table_name LIKE '%%footnotes'
        ORDER BY table_name
    """, (schema,))
    
    return [row[0] for row in cursor.fetchall()]

def fix_footnote_wrappers(schema='new_testament', tables=None, dry_run=False):
    """
    Adds missing <span class="rbt_footnote"> wrappers to footnote HTML.
    
    Args:
        schema: Database schema name
        tables: List of specific table names to process (None = all footnote tables)
        dry_run: If True, show changes without committing
    """
    logger = FootnoteWrapperLogger()
    logger.log(f"Starting footnote wrapper fix (dry_run={dry_run})")
    
    with get_db_connection() as conn:
        cursor = conn.cursor()
        cursor.execute(f"SET search_path TO {schema}")
        
        # Get all footnote tables if not specified
        if tables is None:
            tables = get_all_footnote_tables(cursor, schema)
            logger.log(f"Found {len(tables)} footnote tables to process")
        
        for table in tables:
            logger.log(f"\nProcessing table: {table}")
            
            try:
                # Get column info first
                cursor.execute(f"""
                    SELECT column_name 
                    FROM information_schema.columns 
                    WHERE table_schema = %s AND table_name = %s
                    ORDER BY ordinal_position
                """, (schema, table))
                
                columns = [row[0] for row in cursor.fetchall()]
                id_column = 'id' if 'id' in columns else columns[0]
                footnote_id_column = 'footnote_id' if 'footnote_id' in columns else id_column
                
                # Get all footnotes from table
                cursor.execute(f"""
                    SELECT {id_column}, {footnote_id_column}, footnote_html 
                    FROM {schema}.{table}
                    ORDER BY {id_column}
                """)
                
                footnotes = cursor.fetchall()
                logger.log(f"  Found {len(footnotes)} footnotes in {table}")
                
                for footnote_id_pk, footnote_id, html in footnotes:
                    logger.stats['total_footnotes_processed'] += 1
                    
                    if has_rbt_footnote_class(html):
                        logger.stats['footnotes_already_wrapped'] += 1
                    
                    # Strip data attributes and fix HTML wrapping if needed
                    fixed_html, paragraphs_wrapped = fix_footnote_html(html)
                    
                    # If HTML was modified (either wrapped or stripped)
                    if fixed_html != html:
                        if paragraphs_wrapped > 0:
                            logger.stats['footnotes_fixed'] += 1
                            logger.stats['paragraphs_wrapped'] += paragraphs_wrapped
                            logger.log(f"  Fixed {footnote_id}: wrapped {paragraphs_wrapped} paragraph(s)")
                        else:
                            logger.log(f"  Fixed {footnote_id}: stripped data attributes")
                        
                        if not dry_run:
                            # Update the database
                            cursor.execute(f"""
                                UPDATE {schema}.{table}
                                SET footnote_html = %s
                                WHERE {id_column} = %s
                            """, (fixed_html, footnote_id_pk))
                
                if not dry_run:
                    conn.commit()
                    logger.log(f"  Committed changes for {table}")
                    
            except psycopg2.Error as e:
                logger.stats['errors'] += 1
                logger.log(f"  ERROR processing {table}: {e}", 'ERROR')
                conn.rollback()
        
        logger.log("\n" + "="*80)
        logger.log("PROCESSING COMPLETE")
        logger.log("="*80)
        logger.log(f"Total footnotes processed: {logger.stats['total_footnotes_processed']}")
        logger.log(f"Already wrapped: {logger.stats['footnotes_already_wrapped']}")
        logger.log(f"Footnotes fixed: {logger.stats['footnotes_fixed']}")
        logger.log(f"Paragraphs wrapped: {logger.stats['paragraphs_wrapped']}")
        logger.log(f"Errors: {logger.stats['errors']}")
        
        if dry_run:
            logger.log("\nDRY RUN - No changes were committed to the database")
        
        logger.write_summary()
        
        return logger


def fix_ul_classes(html):
    """
    Ensures all <ul> tags have the 'rbt_footnote' class.
    Returns the modified HTML and the number of ul tags updated.
    """
    if not html:
        return html, 0

    soup = BeautifulSoup(html, 'html.parser')
    updated_count = 0

    for ul in soup.find_all('ul'):
        existing_classes = ul.get('class', [])
        if 'rbt_footnote' not in existing_classes:
            existing_classes.append('rbt_footnote')
            ul['class'] = existing_classes
            updated_count += 1

    return str(soup), updated_count


def show_sample_fixes(schema='new_testament', table_name=None, limit=5):
    """
    Shows sample before/after comparisons without making changes.
    """
    print("="*80)
    print("SAMPLE BEFORE/AFTER COMPARISONS")
    print("="*80)
    
    with get_db_connection() as conn:
        cursor = conn.cursor()
        cursor.execute(f"SET search_path TO {schema}")
        
        # Get a sample footnote table if not specified
        if table_name is None:
            tables = get_all_footnote_tables(cursor, schema)
            if not tables:
                print("No footnote tables found!")
                return
            table_name = tables[0]
            print(f"\nUsing table: {table_name}")
        
        # First check what columns exist
        cursor.execute(f"""
            SELECT column_name 
            FROM information_schema.columns 
            WHERE table_schema = %s AND table_name = %s
            ORDER BY ordinal_position
        """, (schema, table_name))
        
        columns = [row[0] for row in cursor.fetchall()]
        print(f"Available columns: {', '.join(columns)}")
        
        # Determine the ID column name
        id_column = 'id' if 'id' in columns else columns[0]
        footnote_id_column = 'footnote_id' if 'footnote_id' in columns else 'id'
        
        # Get sample footnotes that have data-* attributes
        cursor.execute(f"""
            SELECT {footnote_id_column}, footnote_html 
            FROM {schema}.{table_name}
            WHERE footnote_html ~ 'data-[a-zA-Z-]+="[^"]*"'
            AND footnote_html IS NOT NULL
            LIMIT %s
        """, (limit,))
        
        samples = cursor.fetchall()
        
        if not samples:
            print(f"\nNo footnotes found that need fixing in {table_name}")
            return
        
        for i, (footnote_id, html) in enumerate(samples, 1):
            print(f"\n{'-'*80}")
            print(f"Sample {i}: {footnote_id}")
            print(f"{'-'*80}")
            # Find the first data-* attribute for better display
            match = re.search(r'<[^>]*data-[a-zA-Z-]+="[^"]*"[^>]*>', html)
            if match:
                tag_with_data = match.group(0)
                tag_without_data = strip_data_attributes(tag_with_data)
                
                print(f"\nBEFORE (showing example tag):")
                print(tag_with_data)
                print(f"\nAFTER:")
                print(tag_without_data)
                
                fixed_html, count = fix_footnote_html(html)
                if count > 0:
                    print(f"\nNote: Also wrapped {count} paragraph(s) with rbt_footnote class")

def verify_fixes(schema='new_testament'):
    """
    Verify that all footnotes now have proper wrapping.
    """
    print("\n" + "="*80)
    print("VERIFICATION REPORT")
    print("="*80)
    
    with get_db_connection() as conn:
        cursor = conn.cursor()
        cursor.execute(f"SET search_path TO {schema}")
        
        tables = get_all_footnote_tables(cursor, schema)
        
        total_footnotes = 0
        total_with_wrapper = 0
        total_without_wrapper = 0
        
        for table in tables:
            try:
                cursor.execute(f"""
                    SELECT COUNT(*) as total,
                           SUM(CASE WHEN footnote_html LIKE '%%class="rbt_footnote"%%' THEN 1 ELSE 0 END) as with_wrapper,
                           SUM(CASE WHEN footnote_html NOT LIKE '%%class="rbt_footnote"%%' AND footnote_html IS NOT NULL THEN 1 ELSE 0 END) as without_wrapper
                    FROM {schema}.{table}
                """)
                
                result = cursor.fetchone()
                if result and result[0] is not None:
                    total, with_wrapper, without_wrapper = result
                    # Handle NULL values from SUM
                    with_wrapper = with_wrapper or 0
                    without_wrapper = without_wrapper or 0
                    
                    total_footnotes += total
                    total_with_wrapper += with_wrapper
                    total_without_wrapper += without_wrapper
                    
                    print(f"\n{table}:")
                    print(f"  Total: {total}")
                    print(f"  With wrapper: {with_wrapper}")
                    print(f"  Without wrapper: {without_wrapper}")
            except Exception as e:
                print(f"\n{table}: Error - {e}")
        
        print("\n" + "="*80)
        print("OVERALL TOTALS:")
        print(f"  Total footnotes: {total_footnotes}")
        if total_footnotes > 0:
            print(f"  With wrapper: {total_with_wrapper} ({100*total_with_wrapper/total_footnotes:.1f}%)")
            print(f"  Without wrapper: {total_without_wrapper} ({100*total_without_wrapper/total_footnotes:.1f}%)")
        print("="*80)

if __name__ == "__main__":
    SCHEMA = 'new_testament'
    
    # Show what changes would be made
    print("Showing sample fixes...\n")
    show_sample_fixes(SCHEMA, limit=3)
    
    # Ask user to confirm
    print("\n" + "="*80)
    response = input("\nProceed with fixing all footnotes? (yes/no): ").strip().lower()
    
    if response == 'yes':
        # First do a dry run
        print("\nRunning dry run to validate changes...\n")
        logger = fix_footnote_wrappers(SCHEMA, dry_run=True)
        
        print("\n" + "="*80)
        response2 = input("\nDry run complete. Commit changes to database? (yes/no): ").strip().lower()
        
        if response2 == 'yes':
            print("\nApplying fixes to database...\n")
            logger = fix_footnote_wrappers(SCHEMA, dry_run=False)
            
            # Verify the fixes
            verify_fixes(SCHEMA)
            
            print(f"\nComplete! Check {logger.log_file} for detailed results.")
        else:
            print("\nOperation cancelled. No changes made to database.")
    else:
        print("\nOperation cancelled.")