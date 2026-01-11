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