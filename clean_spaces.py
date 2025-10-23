import psycopg2
import os
import re

def get_db_connection():
    """Get PostgreSQL database connection"""
    DB_NAME = os.getenv('DB_NAME', 'rbt')
    DB_USER = os.getenv('DB_USER', 'matt')
    DB_PASSWORD = os.getenv('DB_PASSWORD', 'Malachi46')
    DB_HOST = os.getenv('DB_HOST', 'localhost')
    
    return psycopg2.connect(
        dbname=DB_NAME,
        user=DB_USER,
        password=DB_PASSWORD,
        host=DB_HOST
    )

def clean_text(text):
    """Remove extra spaces from text"""
    if not text:
        return text
    
    # Replace multiple spaces with a single space and trim
    return re.sub(r'\s+', ' ', text).strip()

def clean_spaces_in_nt():
    """Clean extra spaces from text in new_testament schema"""
    print("Starting space cleanup in new_testament schema...")
    
    with get_db_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("SET search_path TO new_testament")
        
        # Get all records from nt table
        cursor.execute("""
            SELECT verseID, rbt, verseText
            FROM nt
            WHERE rbt IS NOT NULL OR verseText IS NOT NULL
        """)
        verses = cursor.fetchall()
        
        total = len(verses)
        updated = 0
        
        print(f"Found {total} verses to process")
        
        for verse_id, rbt, verse_text in verses:
            cleaned_rbt = clean_text(rbt) if rbt else None
            cleaned_text = clean_text(verse_text) if verse_text else None
            
            # Only update if there are changes
            if cleaned_rbt != rbt or cleaned_text != verse_text:
                cursor.execute("""
                    UPDATE nt
                    SET rbt = %s, verseText = %s
                    WHERE verseID = %s
                """, (cleaned_rbt, cleaned_text, verse_id))
                updated += 1
                
                if updated % 100 == 0:
                    print(f"Processed {updated}/{total} updates...")
        
        conn.commit()
        print(f"\nCleanup complete!")
        print(f"Total verses processed: {total}")
        print(f"Verses updated: {updated}")

if __name__ == "__main__":
    clean_spaces_in_nt()