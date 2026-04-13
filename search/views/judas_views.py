"""
Gospel of Judas (Confessor) text viewer.

Public reader for the Gospel of Judas with codex-page-based navigation.
Displays prose translation with right-column panels for Greek, Coptic,
Notes (from the interlinear table), and Commentary.
"""

import re
import logging
from django.shortcuts import render, redirect
from django.urls import reverse
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

CACHE_VERSION = 'v3'


def judas_view(request, codex_num=None, panel_code=None, lang_code=None):
    """
    Public reader for Gospel of Judas (Confessor) text.

    Displays codex-page-based view with prose translation, plus a
    toggleable right column for Greek, Coptic, Notes, or Commentary.

    Path params (SEO):
        codex_num : int   — Codex page number 33-58
        panel_code : str  — Right-column content: greek|coptic|notes|commentary
    """
    book_name = "Gospel of Confessor (Judas)"
    internal_book_name = "Gospel of Judas"

    # If it is a query param request, redirect to SEO route
    if request.GET.get('codex') or request.GET.get('panel') or request.GET.get('lang'):
        cx = request.GET.get('codex')
        pl = request.GET.get('panel', '')
        la = request.GET.get('lang', 'en')
        # Also honour the path-based lang_code if query param is absent
        if la == 'en' and lang_code and lang_code in SUPPORTED_LANGUAGES:
            la = lang_code
        if pl not in PANEL_MODES:
            pl = ''
        # Fall back to the path parameter if codex is not in query string
        if not cx and codex_num is not None:
            cx = str(codex_num)
        if not cx:
            if la != 'en' and la in SUPPORTED_LANGUAGES:
                return redirect(f"/{la}/judas/", permanent=True)
            return redirect('/judas/', permanent=True)
        
        try:
            cx_int = int(cx)
        except ValueError:
            cx_int = CODEX_MIN

        if la != 'en' and la in SUPPORTED_LANGUAGES:
            if pl:
                return redirect('judas_seo_view_panel_lang', lang_code=la, codex_num=cx_int, panel_code=pl, permanent=True)
            else:
                return redirect('judas_seo_view_lang', lang_code=la, codex_num=cx_int, permanent=True)
        else:
            if pl:
                return redirect('judas_seo_view_panel', codex_num=cx_int, panel_code=pl, permanent=True)
            else:
                return redirect('judas_seo_view', codex_num=cx_int, permanent=True)

    panel = panel_code if panel_code else ''
    if panel not in PANEL_MODES:
        panel = ''

    language = lang_code if lang_code else 'en'
    if language != 'en' and language not in SUPPORTED_LANGUAGES:
        language = 'en'
        
    codex_param = codex_num

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
    heading_prefix = "Gospel of Confessor"
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

    # If non-English, look up translated heading prefix (chapter=0, verse=3)
    if language != 'en':
        try:
            heading_trans = VerseTranslation.objects.filter(
                book=internal_book_name,
                chapter=0,
                verse=3,
                language_code=language,
                footnote_id__isnull=True,
            ).first()
            if heading_trans and heading_trans.verse_text:
                heading_prefix = heading_trans.verse_text
        except Exception:
            logger.exception("Error looking up Judas heading translation for lang %s", language)

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

    # If non-English and commentary panel, look up translated commentary (chapter=0, verse=2)
    if language != 'en' and panel == 'commentary' and right_panel:
        try:
            comm_translation = VerseTranslation.objects.filter(
                book=internal_book_name,
                chapter=0,
                verse=2,
                language_code=language,
                footnote_id__isnull=True,
            ).first()
            if comm_translation and comm_translation.verse_text:
                right_panel = comm_translation.verse_text
                commentary_html = comm_translation.verse_text
            else:
                needs_translation = True
        except Exception:
            logger.exception("Error looking up Judas commentary translation for lang %s", language)

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
        'heading_prefix': heading_prefix,
        'page_title': f"Gospel of Judas {codex_num}",
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
