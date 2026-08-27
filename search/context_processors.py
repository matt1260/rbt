from urllib.parse import urlencode
from django.conf import settings
from django.urls import reverse, NoReverseMatch
from search.seo_utils import (
    book_to_slug,
    slug_to_book,
    hreflang_for,
    SEO_LANGUAGES,
    RTL_LANGUAGES,
)


def _alternates(route, base_kwargs):
    """Build the rel=alternate hreflang cluster for one chapter/verse.

    Every page in the cluster must list every language *including itself* plus an
    x-default, otherwise Google ignores the annotations and falls back to treating
    the translations as duplicates.
    """
    alternates = []

    def add(hreflang, name, kwargs):
        try:
            alternates.append({'hreflang': hreflang, 'path': reverse(name, kwargs=kwargs)})
        except NoReverseMatch:
            pass

    add('x-default', route, dict(base_kwargs))
    add('en', route, dict(base_kwargs))
    for code in SEO_LANGUAGES:
        add(hreflang_for(code), f'{route}_lang', {**base_kwargs, 'lang_code': code})
    return alternates


def seo_context(request):
    """
    Context processor to inject dynamic SEO metadata based on the current page 
    and query parameters (book, chapter, verse) to maximize search visibility.
    """
    context = {
        'canonical_url': request.build_absolute_uri(request.path),
        'meta_title': 'Real Bible Translation Project',
        'meta_description': 'The Real Bible Translation Project focuses on precise, trustworthy translations of scripture using extensive tools and comprehensive linguistic workflows.',
        'meta_keywords': 'Bible, Translation, Hebrew, Greek, RBT, Real Bible Translation',
        'hreflang_alternates': [],
    }

    book_slug = None
    book = None
    chapter = None
    verse = None
    lang_code = None
    q = request.GET.get('q')

    if request.resolver_match and request.resolver_match.kwargs:
        book_slug = request.resolver_match.kwargs.get('book_slug')
        lang_code = request.resolver_match.kwargs.get('lang_code')
        chapter = request.resolver_match.kwargs.get('chapter')
        verse = request.resolver_match.kwargs.get('verse')

    # The page's real content language drives <html lang>/<dir>; without this every
    # translated page declared itself as en-US and read as an English duplicate.
    page_lang = lang_code if lang_code in SEO_LANGUAGES else 'en'
    context['page_lang'] = page_lang
    context['page_dir'] = 'rtl' if page_lang in RTL_LANGUAGES else 'ltr'

    if not book and book_slug:
        book = slug_to_book(book_slug) or book_slug.replace('-', ' ').title()

    if not book and request.GET:
        book = request.GET.get('book')
        chapter = request.GET.get('chapter')
        verse = request.GET.get('verse')

    if book and chapter:
        slug = book_slug or book_to_slug(book)
        if verse:
            context['meta_title'] = f"{book} {chapter}:{verse} | Original Translation & Context | RBT"
            context['meta_description'] = f"Read and study {book} {chapter}:{verse} with our deep original-language interlinear, rich footnotes, and accurate word-for-word translation."

            if slug:
                base_kwargs = {'book_slug': slug, 'chapter': chapter, 'verse': verse}
                route_name = 'verse_seo_view_lang' if page_lang != 'en' else 'verse_seo_view'
                kwargs = dict(base_kwargs)
                if route_name.endswith('_lang'):
                    kwargs['lang_code'] = page_lang
                path = reverse(route_name, kwargs=kwargs)
                context['canonical_url'] = request.build_absolute_uri(path)
                context['hreflang_alternates'] = _alternates('verse_seo_view', base_kwargs)
            else:
                params = urlencode({'book': book, 'chapter': chapter, 'verse': verse})
                context['canonical_url'] = f"{request.build_absolute_uri('/')}?{params}"
        else:
            context['meta_title'] = f"{book} {chapter} | Original Hebrew & Greek Interlinear | RBT"
            context['meta_description'] = f"Dive deep into {book} {chapter} through the Real Bible Translation project. Access literal Greek and Hebrew analysis with extensive context and footnotes."

            if slug:
                base_kwargs = {'book_slug': slug, 'chapter': chapter}
                route_name = 'chapter_seo_view_lang' if page_lang != 'en' else 'chapter_seo_view'
                kwargs = dict(base_kwargs)
                if route_name.endswith('_lang'):
                    kwargs['lang_code'] = page_lang
                path = reverse(route_name, kwargs=kwargs)
                context['canonical_url'] = request.build_absolute_uri(path)
                context['hreflang_alternates'] = _alternates('chapter_seo_view', base_kwargs)
            else:
                params = urlencode({'book': book, 'chapter': chapter})
                context['canonical_url'] = f"{request.build_absolute_uri('/')}?{params}"

    elif q:
        context['meta_title'] = f"Search Results for '{q}' | RBT"
        context['meta_description'] = f"Search results for '{q}' in the Real Bible Translation project database."

    if request.path.startswith('/edit') or request.path.startswith('/translate'):
         context['meta_robots'] = "noindex, nofollow"
    else:
         context['meta_robots'] = "index, follow, max-image-preview:large"

    return context
