from xml.etree.ElementTree import Element, SubElement, tostring

from django.http import HttpResponse
from django.urls import reverse

from search.sitemaps import BibleChapterSitemap, StaticViewSitemap


def sitemap_xml(request):
    """Return the public Bible URL set without template or sitemap-index rendering."""
    urlset = Element('urlset', {'xmlns': 'http://www.sitemaps.org/schemas/sitemap/0.9'})
    sitemap_sources = (BibleChapterSitemap(), StaticViewSitemap())

    for sitemap_source in sitemap_sources:
        for item in sitemap_source.items():
            location = sitemap_source.location(item)
            if location.startswith('/'):
                location = request.build_absolute_uri(location)

            url = SubElement(urlset, 'url')
            SubElement(url, 'loc').text = location
            lastmod_method = getattr(sitemap_source, 'lastmod', None)
            lastmod = lastmod_method(item) if lastmod_method else None
            if lastmod:
                SubElement(url, 'lastmod').text = lastmod.isoformat()
            if sitemap_source.changefreq:
                SubElement(url, 'changefreq').text = sitemap_source.changefreq
            if sitemap_source.priority is not None:
                SubElement(url, 'priority').text = str(sitemap_source.priority)

    xml = tostring(urlset, encoding='utf-8', xml_declaration=True)
    return HttpResponse(xml, content_type='application/xml')