from urllib.parse import urlencode

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

    # Only process GET requests containing SEO-relevant params
    if not request.GET:
        return context

    book = request.GET.get('book')
    chapter = request.GET.get('chapter')
    verse = request.GET.get('verse')
    q = request.GET.get('q')

    if book and chapter:
        if verse:
            context['meta_title'] = f"{book} {chapter}:{verse} | Real Bible Translation Project"
            context['meta_description'] = f"Read and study {book} {chapter}:{verse} with Greek and Hebrew interlinear data, comprehensive footnotes, and literal translations."
            
            # Canonical URL logic
            params = urlencode({'book': book, 'chapter': chapter, 'verse': verse})
            context['canonical_url'] = f"{request.build_absolute_uri('/')}?{params}"
        else:
            context['meta_title'] = f"{book} {chapter} | Real Bible Translation Project"
            context['meta_description'] = f"Dive deep into {book} {chapter} through the Real Bible Translation project. Access literal Greek and Hebrew analysis with extensive footnotes."
            
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
