from django import template

register = template.Library()

@register.filter(name='get_range') 
def get_range(number):
    return range(1, number + 1)

@register.filter(name='get_item')
def get_item(dictionary, key):
    """Get an item from a dictionary"""
    if dictionary and key:
        return dictionary.get(key)
    return None
from search.seo_utils import book_to_slug
from django.urls import reverse

@register.filter(name='get_book_slug')
def get_book_slug_filter(book_name):
    return book_to_slug(book_name) or str(book_name).lower().replace(' ', '-')

@register.simple_tag
def generate_seo_link(lang_code, book_name, chapter_num, verse_num=None):
    slug = get_book_slug_filter(book_name)
    if verse_num:
        if lang_code and lang_code != 'en':
            try:
                return reverse('verse_seo_view_lang', kwargs={'lang_code': lang_code, 'book_slug': slug, 'chapter': chapter_num, 'verse': str(verse_num)})
            except Exception:
                return f'?book={book_name}&chapter={chapter_num}&verse={verse_num}'
        try:
            return reverse('verse_seo_view', kwargs={'book_slug': slug, 'chapter': chapter_num, 'verse': str(verse_num)})
        except Exception:
            return f'?book={book_name}&chapter={chapter_num}&verse={verse_num}'
    else:
        if lang_code and lang_code != 'en':
            try:
                return reverse('chapter_seo_view_lang', kwargs={'lang_code': lang_code, 'book_slug': slug, 'chapter': chapter_num})
            except Exception:
                return f'?book={book_name}&chapter={chapter_num}'
        try:
            return reverse('chapter_seo_view', kwargs={'book_slug': slug, 'chapter': chapter_num})
        except Exception:
            return f'?book={book_name}&chapter={chapter_num}'
