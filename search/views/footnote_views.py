"""
Footnote retrieval and rendering functions.
"""
import re
from django.http import JsonResponse
from search.models import GenesisFootnotes, VerseTranslation
from translate.translator import book_abbreviations, new_testament_books, nt_abbrev, old_testament_books
from search.db_utils import execute_query


FOOTNOTE_LINK_PATTERN = re.compile(r'\?footnote=([^&"\s]+)')


def get_footnote(footnote_id, book, chapter_num=None, verse_num=None):
    """
    Retrieve a single footnote's HTML content based on footnote ID and book.
    Returns an HTML table row with the footnote reference and content.
    """
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

        note_location = f'<div class="note-location">{book} {chapter}:{verse}</div>'

        # Create an HTML table with two columns
        table_html = (
            f'<tr>'
            f'<td style="border-bottom: 1px solid #d2d2d2;">'
            f'<a href="?footnote={chapter}-{verse}-{footnote_ref}">{footnote_ref}</a>'
            f'</td>'
            f'<td style="border-bottom: 1px solid #d2d2d2;">{note_location}{footnote_html}</td>'
            f'</tr>'
        )

        return table_html

    else:
        # Determine canonical full name for schema; use abbreviation for table/id
        reverse_lookup = {abbrev: name for name, abbrev in book_abbreviations.items()}
        full_book = book if book in new_testament_books or book in old_testament_books else reverse_lookup.get(book, book)
        book_abbrev = book_abbreviations.get(full_book, full_book)
        is_nt = full_book in new_testament_books or book_abbrev in nt_abbrev

        if is_nt:
            table_abbrev = book_abbrev.lower()
            if table_abbrev[0].isdigit():
                table = f"table_{table_abbrev}_footnotes"
            else:
                table = f"{table_abbrev}_footnotes"

            footnote_parts = footnote_id.split('-')
            footnote_number = footnote_parts[-1]

            footnote_ref = f"{book_abbrev}-{footnote_number}"

            chapter_part = footnote_parts[0] if footnote_parts else chapter_num
            verse_part = footnote_parts[1] if len(footnote_parts) > 1 else verse_num
            note_location = ''
            if chapter_part and verse_part:
                note_location = f'<div class="note-location">{full_book} {chapter_part}:{verse_part}</div>'
            elif chapter_part:
                note_location = f'<div class="note-location">{full_book} {chapter_part}</div>'

            # Construct the SQL query to retrieve HTML
            sql_query = f"SELECT footnote_html FROM new_testament.{table} WHERE footnote_id = %s"
            result = execute_query(sql_query, (footnote_ref,), fetch='one')

            if result:
                footnote_html = result[0]
                # Create an HTML table with two columns
                table_html = (
                    f'<tr>'
                    f'<td style="border-bottom: 1px solid #d2d2d2;">'
                    f'<a href="?footnote={chapter_num}-{verse_num}-{footnote_number}&book={book_abbrev}">{footnote_number}</a>'
                    f'</td>'
                    f'<td style="border-bottom: 1px solid #d2d2d2;">{note_location}{footnote_html}</td>'
                    f'</tr>'
                )
            else:
                table_html = ''

            return table_html

        else:
            # Old Testament / Hebrewdata footnotes
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
                note_location = f'<div class="note-location">{foot_ref}</div>'
                # Create an HTML table with two columns
                table_html = (
                    f'<tr>'
                    f'<td style="border-bottom: 1px solid #d2d2d2;">{foot_ref}</td>'
                    f'<td style="border-bottom: 1px solid #d2d2d2;">{note_location}{footnote_html}</td>'
                    f'</tr>'
                )
            else:
                table_html = ''

            return table_html


def collect_chapter_notes(html_chunks, book, chapter_num=None, verse_num=None):
    """Extract unique footnote rows from provided HTML snippets."""
    if not html_chunks:
        return []

    collected: list[str] = []
    seen: set[str] = set()

    for chunk in html_chunks:
        if not chunk:
            continue

        matches = FOOTNOTE_LINK_PATTERN.findall(str(chunk))
        for footnote_id in matches:
            if footnote_id in seen:
                continue

            seen.add(footnote_id)
            try:
                footnote_row = get_footnote(footnote_id, book, chapter_num, verse_num)
            except Exception as exc:
                print(f"[WARN] Unable to collect footnote {footnote_id}: {exc}")
                footnote_row = ''

            if footnote_row:
                collected.append(footnote_row)

    return collected


def build_notes_html(html_chunks, book, chapter_num=None, verse_num=None, translated_footnotes=None):
    """Format aggregated chapter notes into a table suitable for rendering.
    
    Args:
        html_chunks: List of HTML strings to extract footnote references from
        book: Book name
        chapter_num: Chapter number (optional)
        verse_num: Verse number (optional)
        translated_footnotes: Dict of {full_footnote_id: translated_content} for translations
    """
    rows = collect_chapter_notes_with_translations(
        html_chunks, book, chapter_num, verse_num, translated_footnotes
    )
    if not rows:
        return ''

    merged = ''.join(rows)
    return f'<table class="notes-table"><tbody>{merged}</tbody></table>'


def collect_chapter_notes_with_translations(html_chunks, book, chapter_num=None, verse_num=None, translated_footnotes=None):
    """Extract unique footnote rows, using translated content when available."""
    if not html_chunks:
        return []

    collected: list[str] = []
    seen: set[str] = set()
    translated_footnotes = translated_footnotes or {}

    for chunk in html_chunks:
        if not chunk:
            continue

        matches = FOOTNOTE_LINK_PATTERN.findall(str(chunk))
        for footnote_id in matches:
            if footnote_id in seen:
                continue

            seen.add(footnote_id)
            
            # Check if we have a translated version
            full_footnote_id = f"{book}-{footnote_id}"
            if full_footnote_id in translated_footnotes:
                # Translated footnotes already contain the full <tr>...</tr> row structure
                # Just use them directly
                footnote_row = translated_footnotes[full_footnote_id]
            else:
                # Fall back to original English footnote
                try:
                    footnote_row = get_footnote(footnote_id, book, chapter_num, verse_num)
                except Exception as exc:
                    print(f"[WARN] Unable to collect footnote {footnote_id}: {exc}", flush=True)
                    footnote_row = ''

            if footnote_row:
                collected.append(footnote_row)

    return collected


def footnote_json(request, footnote_id):
    """
    Return footnote content as JSON for popup display.
    Supports Genesis format (1-3-15), OT format (Eze-16-4-07), and NT format (Psa-150-2-02)
    """
    footnote_html = ""
    title = ""
    language = request.GET.get('lang', 'en')
    book_param = request.GET.get('book')  # Optional book parameter for NT/OT
    
    try:
        footnote_parts = footnote_id.split('-')
        
        reverse_lookup = {abbrev: name for name, abbrev in book_abbreviations.items()}

        # Genesis format: 1-3-15 (chapter-verse-footnoteNum) - check FIRST before NT/OT
        # Genesis uses 3-part numeric IDs (e.g., 1-18-35b) and book=Genesis
        is_genesis = book_param and book_param.lower() == 'genesis'
        
        if len(footnote_parts) == 3 and (is_genesis or (footnote_parts[0].isdigit() and not book_param)):
            chapter_ref, verse_ref, footnote_ref = footnote_parts
            book = 'Genesis'
            title = f'Genesis {chapter_ref}:{verse_ref}'
            
            # Check for translation first
            if language and language != 'en':
                translation = VerseTranslation.objects.filter(
                    book=book,
                    language_code=language,
                    footnote_id__icontains=footnote_id,
                    status='completed'
                ).first()
                if translation and translation.footnote_text:
                    footnote_html = translation.footnote_text
            
            # Fallback to English
            if not footnote_html:
                results = GenesisFootnotes.objects.filter(
                    footnote_id=footnote_id).values('footnote_html')
                
                if results:
                    footnote_html = results[0]['footnote_html']
                else:
                    footnote_html = f"No footnote found for {footnote_id}."

        # NT/OT explicit book with 3-part ID (e.g., ?footnote=2-1-2&book=Gal)
        elif len(footnote_parts) == 3 and book_param:
            chapter_ref, verse_ref, footnote_ref = footnote_parts
            full_book = book_param if book_param in new_testament_books or book_param in old_testament_books else reverse_lookup.get(book_param, book_param)
            book_abbrev = book_abbreviations.get(full_book, full_book)
            is_nt_book = full_book in new_testament_books or book_abbrev in nt_abbrev

            title = f'{full_book} {chapter_ref}:{verse_ref}'

            # Translated footnote first - stored as "{book}-{footnote_ref}" (e.g., "Galatians-2")
            if language and language != 'en':
                # Try full book name format first (e.g., "Galatians-2")
                stored_footnote_id = f"{full_book}-{footnote_ref}"
                translation = VerseTranslation.objects.filter(
                    book=full_book,
                    language_code=language,
                    footnote_id=stored_footnote_id,
                    status='completed'
                ).first()
                # Also try abbreviation format (e.g., "Gal-2")
                if not translation or not translation.footnote_text:
                    stored_footnote_id_abbrev = f"{book_abbrev}-{footnote_ref}"
                    translation = VerseTranslation.objects.filter(
                        book=full_book,
                        language_code=language,
                        footnote_id=stored_footnote_id_abbrev,
                        status='completed'
                    ).first()
                if translation and translation.footnote_text:
                    footnote_html = translation.footnote_text

            if not footnote_html:
                if is_nt_book:
                    table = f"table_{book_abbrev.lower()}_footnotes" if book_abbrev and book_abbrev[0].isdigit() else f"{book_abbrev.lower()}_footnotes"
                    db_footnote_id = f"{book_abbrev}-{footnote_ref}"
                    result = execute_query(
                        f"SELECT footnote_html FROM new_testament.{table} WHERE footnote_id = %s",
                        (db_footnote_id,),
                        fetch='one'
                    )
                    if result and result[0]:
                        footnote_html = result[0]
                else:
                    # OT: fallback to hebrewdata (chapter.verse-footnote)
                    rbt_heb_ref = f"{book_abbrev}.{chapter_ref}.{verse_ref}-{footnote_ref}"
                    result = execute_query(
                        "SELECT footnote FROM old_testament.hebrewdata WHERE Ref = %s",
                        (rbt_heb_ref,),
                        fetch='one'
                    )
                    if result and result[0]:
                        footnote_html = result[0]

            if not footnote_html:
                footnote_html = f"No footnote found for {footnote_id}."
        
        # NT format: Psa-150-2-02 (abbrev-chapter-verse-footnoteNum)
        elif len(footnote_parts) == 4 and not footnote_parts[0].isdigit():
            book_abbrev, chapter_ref, verse_ref, footnote_ref = footnote_parts
            
            # Map abbreviations to full book names
            abbrev_to_book = {abbrev: bk for bk, abbrev in book_abbreviations.items()}
            full_book_name = abbrev_to_book.get(book_abbrev, book_abbrev)
            
            # Determine if this is NT or OT book
            is_nt_book = full_book_name in new_testament_books
            
            title = f'{full_book_name} {chapter_ref}:{verse_ref}'
            # For OT books, use abbrev-footnote format (e.g., Psa-02)
            # For NT books, use fullname-footnote format (e.g., John-1)
            db_footnote_id = f'{book_abbrev}-{footnote_ref}' if not is_nt_book else f'{full_book_name}-{footnote_ref}'
            
            if language and language != 'en':
                # Try various footnote ID formats
                possible_ids = [
                    f'{full_book_name}-{footnote_id}',  # Psalms-Psa-150-2-02
                    f'{full_book_name}-{chapter_ref}-{verse_ref}-{footnote_ref}',  # Psalms-150-2-02
                    db_footnote_id,  # Psa-02 for OT, John-1 for NT
                ]
                translation = VerseTranslation.objects.filter(
                    book=full_book_name,
                    language_code=language,
                    footnote_id__in=possible_ids,
                    status='completed'
                ).first()
                if translation and translation.footnote_text:
                    footnote_html = translation.footnote_text
            
            # Fallback to English from database
            if not footnote_html:
                # Use correct schema based on book type
                schema = 'new_testament' if is_nt_book else 'old_testament'
                
                print(f"[FOOTNOTE JSON] Book: {full_book_name}, Abbrev: {book_abbrev}, Schema: {schema}, Is NT: {is_nt_book}")
                
                try:
                    if is_nt_book:
                        # NT books have separate footnote tables
                        if book_abbrev[0].isdigit():
                            table = f"table_{book_abbrev.lower()}_footnotes"
                        else:
                            table = f"{book_abbrev.lower()}_footnotes"
                        
                        result = execute_query(
                            f"SELECT footnote_html FROM {schema}.{table} WHERE footnote_id = %s",
                            (db_footnote_id,),
                            fetch='one'
                        )
                        if result and result[0]:
                            footnote_html = result[0]
                    else:
                        # OT books store footnotes in hebrewdata table
                        # Reference format: Psa.150.2-02
                        rbt_heb_ref = f'{book_abbrev}.{chapter_ref}.{verse_ref}-{footnote_ref}'
                        result = execute_query(
                            "SELECT footnote FROM old_testament.hebrewdata WHERE Ref = %s",
                            (rbt_heb_ref,),
                            fetch='one'
                        )
                        if result and result[0]:
                            footnote_html = result[0]
                    
                    if not footnote_html:
                        footnote_html = f"No footnote found for {footnote_id} (tried {db_footnote_id if is_nt_book else rbt_heb_ref})."
                        
                except Exception as e:
                    print(f"[FOOTNOTE JSON ERROR] {e}")
                    footnote_html = f"Error retrieving footnote: {e}"
        
        else:
            footnote_html = f"Invalid footnote format: {footnote_id}"
            title = "Error"
    
    except Exception as e:
        import traceback
        traceback.print_exc()
        footnote_html = f"Error retrieving footnote: {str(e)}"
        title = "Error"
    
    return JsonResponse({
        'footnote_id': footnote_id,
        'title': title,
        'content': footnote_html
    })
