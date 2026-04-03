from urllib.parse import urlencode
from django.conf import settings
from django.urls import reverse
from search.seo_utils import book_to_slug, slug_to_book

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
    }

    # Extract args from resolver_match (SEO URLs) or GET (legacy)
    book_slug = None
    book = None
    chapter = None
    verse = None
    q = request.GET.get('q')

    if request.resolver_match and request.resolver_match.kwargs:
        book_slug = request.resolver_match.kwargs.get('book_slug')
        chapter = request.resolver_match.kwargs.get('chapter')
        verse = request.resolver_match.kwargs.get('verse')

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
                path = reverse('verse_seo_view', kwargs={'book_slug': slug, 'chapter': chapter, 'verse': verse})
                context['canonical_url'] = request.build_absolute_uri(path)
            else:
                params = urlencode({'book': book, 'chapter': chapter, 'verse': verse})
                context['canonical_url'] = f"{request.build_absolute_uri('/')}?{params}"
        else:
            context['meta_title'] = f"{book} {chapter} | Original Hebrew & Greek Interlinear | RBT"
            context['meta_description'] = f"Dive deep into {book} {chapter} through the Real Bible Translation project. Access literal Greek and Hebrew analysis with extensive context and footnotes."
            
            if slug:
                path = reverse('chapter_seo_view', kwargs={'book_slug': slug, 'chapter': chapter})
                context['canonical_url'] = request.build_absolute_uri(path)
            else:
                params = urlencode({'book': book, 'chapter': chapter})
                context['canonical_url'] = f"{request.build_absolute_uri('/')}?{params}"

    elif q:
        context['meta_title'] = f"Search Results for '{q}' | RBT"
        context['meta_description'] = f"Search results for '{q}' in the Real Bible Translation project database."

    # Prevent indexing of internal search queries or parameterized non-canonical routes to prevent duplicate content
    if request.path.startswith('/edit') or request.path.startswith('/translate'):
         context['meta_robots'] = "noindex, nofollow"
    else:
         context['meta_robots'] = "index, follow, max-image-preview:large"

    return context
