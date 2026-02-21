"""
Backward-compatible imports for search views.

This allows existing code to continue using:
    from search.views import home, search, get_results, etc.

The views have been refactored into focused modules:
- utils.py: Helper functions (detect_script, strip_hebrew_vowels, highlight_match)
- footnote_views.py: Footnote handling (get_footnote, collect_notes, footnote_json)
- translation_views.py: Translation API (translate_chapter_api, job management)
- chapter_views.py: Chapter display (search, get_results, storehouse_view, etc.)
- search_views.py: Search functionality (search_api, search_suggestions)
- statistics_views.py: Statistics and analytics

TODO: Create remaining modules (chapter_views.py, search_views.py, statistics_views.py)
and import them here for backward compatibility.
"""

# Utility functions
from .utils import (
    HEBREW_RANGE,
    GREEK_RANGE,
    detect_script,
    strip_hebrew_vowels,
    highlight_match,
)

# Footnote views
from .footnote_views import (
    FOOTNOTE_LINK_PATTERN,
    get_footnote,
    collect_chapter_notes,
    build_notes_html,
    collect_chapter_notes_with_translations,
    footnote_json,
)

# Translation views
from .translation_views import (
    INTERLINEAR_CACHE_VERSION,
    get_cache_key,
    translate_chapter_api,
    start_translation_job,
    translation_job_status,
    clear_translation_cache,
    retry_failed_translations,
)

# Chapter views (PARTIAL - core functions only)
from .chapter_views_part1 import (
    home,
    update_count,
    updates,
    get_results,
)

# Storehouse view (Joseph & Aseneth)
from .storehouse_views import (
    storehouse_view,
)

# Search dispatch view (main entry point)
from .search_dispatch_views import (
    search,
    handle_reference_search,
    handle_keyword_search,
    handle_single_verse,
    handle_single_chapter,
)

# Chapter handlers (called by search dispatch)
from .chapter_handlers import (
    handle_genesis_chapter,
    handle_nt_chapter,
    handle_ot_chapter,
)

# Search views
from .search_views import (
    search_results_page,
    search_api,
    search_suggestions,
)

# Statistics views
from .statistics_views import (
    update_statistics_view,
    update_statistics_api,
    visitor_locations_api,
)

__all__ = [
    # Utils
    'HEBREW_RANGE',
    'GREEK_RANGE',
    'detect_script',
    'strip_hebrew_vowels',
    'highlight_match',
    
    # Footnotes
    'FOOTNOTE_LINK_PATTERN',
    'get_footnote',
    'collect_chapter_notes',
    'build_notes_html',
    'collect_chapter_notes_with_translations',
    'footnote_json',
    
    # Translation
    'INTERLINEAR_CACHE_VERSION',
    'get_cache_key',
    'translate_chapter_api',
    'start_translation_job',
    'translation_job_status',
    'clear_translation_cache',
    'retry_failed_translations',
    
    # Chapter views (PARTIAL)
    'home',
    'update_count',
    'updates',
    'get_results',
    
    # Storehouse view
    'storehouse_view',
    
    # Search dispatch (main entry point)
    'search',
    'handle_reference_search',
    'handle_keyword_search',
    'handle_single_verse',
    'handle_single_chapter',
    
    # Chapter handlers
    'handle_genesis_chapter',
    'handle_nt_chapter',
    'handle_ot_chapter',
    
    # Search views
    'search_results_page',
    'search_api',
    'search_suggestions',
    
    # Statistics views
    'update_statistics_view',
    'update_statistics_api',
    'visitor_locations_api',
]
