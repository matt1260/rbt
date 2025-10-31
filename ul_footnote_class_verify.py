import psycopg2
import os
from bs4 import BeautifulSoup
from datetime import datetime

def get_db_connection():
    """Get PostgreSQL database connection"""
    database_url = os.environ.get('DATABASE_URL')
    if database_url:
        return psycopg2.connect(database_url)
    else:
        return psycopg2.connect(
            host='localhost',
            database='rbt',
            user='matt',
            password='Malachi46'
        )

class ULClassLogger:
    """Logs operations for verifying and fixing <ul> class consistency"""
    def __init__(self, log_file='ul_class_fix.log'):
        self.log_file = log_file
        self.stats = {
            'total_footnotes_processed': 0,
            'footnotes_fixed': 0,
            'uls_checked': 0,
            'uls_fixed': 0,
            'errors': 0
        }

    def log(self, message, level='INFO'):
        """Write a timestamped log entry"""
        timestamp = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        entry = f"[{timestamp}] [{level}] {message}\n"
        with open(self.log_file, 'a') as f:
            f.write(entry)
        print(entry.strip())

    def write_summary(self):
        """Write a summary file of the operation"""
        summary_path = self.log_file.replace('.log', '_summary.txt')
        with open(summary_path, 'w') as f:
            f.write("="*80 + "\n")
            f.write("UL CLASS VERIFICATION SUMMARY\n")
            f.write("="*80 + "\n\n")
            for k, v in self.stats.items():
                f.write(f"{k.replace('_', ' ').title()}: {v}\n")
        self.log(f"Summary written to {summary_path}")

def get_all_footnote_tables(cursor, schema):
    """Get list of all tables ending with 'footnotes'"""
    cursor.execute(f"""
        SELECT table_name
        FROM information_schema.tables
        WHERE table_schema = %s
        AND table_name LIKE '%%footnotes'
        ORDER BY table_name
    """, (schema,))
    return [r[0] for r in cursor.fetchall()]

def ensure_ul_class(html):
    """
    Adds 'rbt_footnote' class to all <ul> tags that lack it.
    Returns modified HTML and count of ULs changed.
    """
    if not html:
        return html, 0

    soup = BeautifulSoup(html, 'html.parser')
    count = 0

    for ul in soup.find_all('ul'):
        existing_classes = ul.get('class', [])
        if 'rbt_footnote' not in existing_classes:
            existing_classes.append('rbt_footnote')
            ul['class'] = existing_classes
            count += 1

    return str(soup), count

def verify_ul_classes(schema='new_testament', dry_run=False):
    """Verify and fix missing <ul class='rbt_footnote'>"""
    logger = ULClassLogger()
    logger.log(f"Starting UL class verification (dry_run={dry_run})")

    with get_db_connection() as conn:
        cursor = conn.cursor()
        cursor.execute(f"SET search_path TO {schema}")

        tables = get_all_footnote_tables(cursor, schema)
        logger.log(f"Found {len(tables)} footnote tables")

        for table in tables:
            logger.log(f"\nProcessing table: {table}")
            try:
                cursor.execute(f"""
                    SELECT footnote_id, footnote_html
                    FROM {schema}.{table}
                    ORDER BY footnote_id
                """)
                rows = cursor.fetchall()
                logger.log(f"  Found {len(rows)} footnotes in {table}")

                for footnote_id, html in rows:
                    logger.stats['total_footnotes_processed'] += 1
                    fixed_html, ul_fixed = ensure_ul_class(html)
                    logger.stats['uls_checked'] += html.count('<ul')

                    if ul_fixed > 0:
                        logger.stats['footnotes_fixed'] += 1
                        logger.stats['uls_fixed'] += ul_fixed
                        logger.log(f"  Fixed footnote {footnote_id}: added class to {ul_fixed} UL(s)")
                        if not dry_run:
                            cursor.execute(f"""
                                UPDATE {schema}.{table}
                                SET footnote_html = %s
                                WHERE footnote_id = %s
                            """, (fixed_html, footnote_id))
                if not dry_run:
                    conn.commit()
                    logger.log(f"  Committed changes for {table}")

            except Exception as e:
                logger.stats['errors'] += 1
                logger.log(f"  ERROR processing {table}: {e}", 'ERROR')
                conn.rollback()

    logger.log("\n" + "="*80)
    logger.log("UL CLASS VERIFICATION COMPLETE")
    logger.log("="*80)
    logger.log(f"Total footnotes processed: {logger.stats['total_footnotes_processed']}")
    logger.log(f"Footnotes fixed: {logger.stats['footnotes_fixed']}")
    logger.log(f"ULs checked: {logger.stats['uls_checked']}")
    logger.log(f"ULs fixed: {logger.stats['uls_fixed']}")
    logger.log(f"Errors: {logger.stats['errors']}")

    if dry_run:
        logger.log("DRY RUN — No database changes committed")

    logger.write_summary()
    return logger

if __name__ == "__main__":
    SCHEMA = 'new_testament'
    response = input("Run UL class verification (dry run first)? (yes/no): ").strip().lower()
    if response == 'yes':
        verify_ul_classes(SCHEMA, dry_run=True)
        confirm = input("Dry run complete. Apply changes to DB? (yes/no): ").strip().lower()
        if confirm == 'yes':
            verify_ul_classes(SCHEMA, dry_run=False)
        else:
            print("Aborted before commit.")
    else:
        print("Cancelled.")
