"""
Gospel of Judas (Confessor) text viewer.

Public reader for the Gospel of Judas with codex-page-based navigation.
Displays prose translation with right-column panels for Greek, Coptic,
Notes (from the interlinear table), and Commentary.
"""

import re
import logging
from django.shortcuts import render
from django.core.cache import cache

from search.db_utils import get_db_connection
from search.translation_utils import SUPPORTED_LANGUAGES
from search.models import VerseTranslation

logger = logging.getLogger(__name__)

# Codex page range
CODEX_MIN = 33
CODEX_MAX = 58
CODEX_RANGE = list(range(CODEX_MIN, CODEX_MAX + 1))

# Valid right-panel modes
PANEL_MODES = {'greek', 'coptic', 'notes', 'commentary'}

CACHE_VERSION = 'v2'


def judas_view(request):
    """
    Public reader for Gospel of Judas (Confessor) text.

    Displays codex-page-based view with prose translation, plus a
    toggleable right column for Greek, Coptic, Notes, or Commentary.

    Query params:
        codex : int   — Codex page number 33-58 (default: none → landing)
        panel : str   — Right-column content: greek | coptic | notes | commentary
    """
    book_name = "Gospel of Confessor (Judas)"
    internal_book_name = "Gospel of Judas"

    codex_param = request.GET.get('codex')
    panel = request.GET.get('panel', '')
    if panel not in PANEL_MODES:
        panel = ''

    # Language support
    language = request.GET.get('lang', 'en')
    if language != 'en' and language not in SUPPORTED_LANGUAGES:
        language = 'en'

    # No codex selected → show landing page
    if not codex_param:
        context = {
            'book': book_name,
            'codex_range': CODEX_RANGE,
            'codex_num': None,
            'page_title': book_name,
            'prose': '',
            'right_panel': '',
            'panel': panel,
            'commentary': '',
            'scene_title': '',
            'supported_languages': SUPPORTED_LANGUAGES,
            'current_language': language,
            'needs_translation': False,
        }
        return render(request, 'judas.html', context)

    try:
        codex_num = int(codex_param)
        if codex_num < CODEX_MIN:
            codex_num = CODEX_MIN
        elif codex_num > CODEX_MAX:
            codex_num = CODEX_MAX
    except (TypeError, ValueError):
        codex_num = CODEX_MIN

    # Cache key — only cache English to avoid stale translations
    cache_key = f'judas_{codex_num}_{panel}_{CACHE_VERSION}'
    if language == 'en':
        try:
            from search.db_utils import safe_cache_get
            cached = safe_cache_get(cache_key)
        except Exception:
            try:
                cached = cache.get(cache_key)
            except Exception:
                cached = None

        if cached:
            context = {
                **cached,
                'cache_hit': True,
                'codex_range': CODEX_RANGE,
                'supported_languages': SUPPORTED_LANGUAGES,
                'current_language': language,
                'needs_translation': False,
            }
            return render(request, 'judas.html', context)

    prose = ''
    right_panel = ''
    scene_title = ''
    commentary_html = ''
    error_message = None
    needs_translation = False

    try:
        with get_db_connection() as conn:
            with conn.cursor() as cursor:
                cursor.execute("BEGIN")
                cursor.execute("SET LOCAL search_path TO gospel_of_judas")

                # Fetch prose for this codex page
                cursor.execute(
                    "SELECT scene_title, content FROM judas_prose WHERE codex = %s",
                    (codex_num,),
                )
                prose_row = cursor.fetchone()
                if prose_row:
                    scene_title = prose_row[0] or ''
                    prose = prose_row[1] or ''

                # Fetch interlinear data for this codex page
                cursor.execute(
                    """
                    SELECT line_num, coptic, greek, english, notes
                    FROM judas_interlinear
                    WHERE codex = %s
                    ORDER BY line_num
                    """,
                    (codex_num,),
                )
                interlinear_rows = cursor.fetchall()

                # Build right-panel content based on panel mode
                if panel == 'greek':
                    right_panel = _build_greek_panel(interlinear_rows)
                elif panel == 'coptic':
                    right_panel = _build_coptic_panel(interlinear_rows)
                elif panel == 'notes':
                    right_panel = _build_notes_panel(interlinear_rows)
                elif panel == 'commentary':
                    cursor.execute("SELECT content FROM judas_commentary LIMIT 1")
                    row = cursor.fetchone()
                    commentary_html = row[0] if row else ''
                    right_panel = commentary_html

    except Exception as exc:
        logger.exception("Error loading Gospel of Judas codex %s", codex_num)
        error_message = str(exc)

    # If non-English, look up translated book name from VerseTranslation (chapter=0, verse=0)
    if language != 'en':
        try:
            book_name_trans = VerseTranslation.objects.filter(
                book=internal_book_name,
                chapter=0,
                verse=0,
                language_code=language,
                footnote_id__isnull=True,
            ).first()
            if book_name_trans and book_name_trans.verse_text:
                book_name = book_name_trans.verse_text
        except Exception:
            logger.exception("Error looking up Judas book name translation for lang %s", language)

    # If non-English, look up translated prose from VerseTranslation
    if language != 'en' and prose:
        try:
            translation = VerseTranslation.objects.filter(
                book=internal_book_name,
                chapter=codex_num,
                verse=1,
                language_code=language,
                footnote_id__isnull=True,
            ).first()
            if translation and translation.verse_text:
                prose = translation.verse_text
            else:
                needs_translation = True
        except Exception:
            logger.exception("Error looking up Judas prose translation for codex %s lang %s", codex_num, language)

    context = {
        'book': book_name,
        'original_book': internal_book_name,
        'codex_num': codex_num,
        'codex_range': CODEX_RANGE,
        'prose': prose,
        'right_panel': right_panel,
        'panel': panel,
        'scene_title': scene_title,
        'commentary': commentary_html,
        'error_message': error_message,
        'cache_hit': False,
        'page_title': f"Codex {codex_num}",
        'supported_languages': SUPPORTED_LANGUAGES,
        'current_language': language,
        'needs_translation': needs_translation,
    }

    # Only cache English responses to avoid stale translations
    if not error_message and language == 'en':
        # Build a serialisable subset (exclude SUPPORTED_LANGUAGES which is always fresh)
        cache_payload = {k: v for k, v in context.items()
                         if k not in ('supported_languages', 'current_language', 'needs_translation', 'codex_range')}
        try:
            from search.db_utils import safe_cache_set
            safe_cache_set(cache_key, cache_payload)
        except Exception:
            try:
                cache.set(cache_key, cache_payload)
            except Exception:
                logger.exception("Failed to cache judas key %s", cache_key)

    context['codex_range'] = CODEX_RANGE
    return render(request, 'judas.html', context)


# ---------------------------------------------------------------------------
# Panel builders
# ---------------------------------------------------------------------------

def _build_greek_panel(rows):
    """Build HTML for the reconstructed Greek panel."""
    if not rows:
        return '<h4>Greek Reconstruction</h4><p class="panel-empty">No Greek reconstruction available for this codex page.</p>'
    lines = []
    previous_line_num = None
    for line_num, coptic, greek, english, notes in rows:
        if greek:
            try:
                current_line_num = int(line_num)
            except (TypeError, ValueError):
                current_line_num = None

            if (
                previous_line_num is not None
                and current_line_num is not None
                and current_line_num > previous_line_num + 1
            ):
                gap_start = previous_line_num + 1
                gap_end = current_line_num - 1
                if gap_start == gap_end:
                    gap_text = f'[Missing line {gap_start}]'
                else:
                    gap_text = f'[Missing lines {gap_start}-{gap_end}]'
                lines.append(f'<p class="line-gap">{gap_text}</p>')

            lines.append(
                f'<p class="interlinear-line">'
                f'<span class="line-num">{line_num}</span> '
                f'<span class="line-text">{greek}</span>'
                f'</p>'
            )

            if current_line_num is not None:
                previous_line_num = current_line_num

    if not lines:
        return '<h4>Greek Reconstruction</h4><p class="panel-empty">No Greek text for this codex page.</p>'
    return '<h4>Greek Reconstruction</h4>' + '\n'.join(lines)


def _build_coptic_panel(rows):
    """Build HTML for the Coptic text panel."""
    if not rows:
        return '<h4>Coptic</h4><p class="panel-empty">No Coptic text available for this codex page.</p>'
    lines = []
    previous_line_num = None
    for line_num, coptic, greek, english, notes in rows:
        if coptic:
            try:
                current_line_num = int(line_num)
            except (TypeError, ValueError):
                current_line_num = None

            if (
                previous_line_num is not None
                and current_line_num is not None
                and current_line_num > previous_line_num + 1
            ):
                gap_start = previous_line_num + 1
                gap_end = current_line_num - 1
                if gap_start == gap_end:
                    gap_text = f'[Missing line {gap_start}]'
                else:
                    gap_text = f'[Missing lines {gap_start}-{gap_end}]'
                lines.append(f'<p class="line-gap">{gap_text}</p>')

            lines.append(
                f'<p class="interlinear-line">'
                f'<span class="line-num">{line_num}</span> '
                f'<span class="line-text">{coptic}</span>'
                f'</p>'
            )

            if current_line_num is not None:
                previous_line_num = current_line_num

    if not lines:
        return '<h4>Coptic</h4><p class="panel-empty">No Coptic text for this codex page.</p>'
    return '<h4>Coptic</h4>' + '\n'.join(lines)


def _build_notes_panel(rows):
    """Build HTML for the scholarly Notes panel."""
    if not rows:
        return '<p class="panel-empty">No notes available for this codex page.</p>'
    lines = []
    for line_num, coptic, greek, english, notes in rows:
        if notes:
            normalized_notes = _inline_notes_html(notes)
            lines.append(
                f'<div class="note-entry">'
                f'<span class="line-num">{line_num}</span> '
                f'<span class="note-text">{normalized_notes}</span>'
                f'</div>'
            )
    if not lines:
        return '<p class="panel-empty">No notes for this codex page.</p>'
    return '\n'.join(lines)


def _inline_notes_html(notes_html):
    """Convert block div wrappers in notes to inline spans for compact line rendering."""
    text = (notes_html or '').strip()
    text = re.sub(r'<\s*/\s*div\s*>', '</span>', text, flags=re.IGNORECASE)
    text = re.sub(r'<\s*div(?:\s+[^>]*)?>', '<span>', text, flags=re.IGNORECASE)
    return text
