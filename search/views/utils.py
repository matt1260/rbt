"""
Utility functions for text processing and search operations.
"""
import re

# Hebrew character range for detection
HEBREW_RANGE = '\u0590-\u05FF'
# Greek character range for detection  
GREEK_RANGE = '\u0370-\u03FF\u1F00-\u1FFF'


def detect_script(text):
    """Detect if text contains Hebrew, Greek, or Latin characters"""
    has_hebrew = bool(re.search(f'[{HEBREW_RANGE}]', text))
    has_greek = bool(re.search(f'[{GREEK_RANGE}]', text))
    return {
        'hebrew': has_hebrew,
        'greek': has_greek,
        'latin': not has_hebrew and not has_greek
    }


def strip_hebrew_vowels(text):
    """Remove Hebrew niqqud (vowel points) from text"""
    niqqud_pattern = '[\u0591-\u05BD\u05BF\u05C1-\u05C5\u05C7]'
    return re.sub(niqqud_pattern, '', text)


def highlight_match(text, query, max_length=200):
    """Highlight search term in text and truncate around match"""
    if not text:
        return ''
    
    # Remove HTML tags for display
    clean_text = re.sub(r'<[^>]+>', '', str(text))
    
    # Find match position (case insensitive)
    pattern = re.compile(f'({re.escape(query)})', re.IGNORECASE)
    match = pattern.search(clean_text)
    
    if match:
        start_pos = max(0, match.start() - 50)
        end_pos = min(len(clean_text), match.end() + max_length - 50)
        excerpt = clean_text[start_pos:end_pos]
        
        if start_pos > 0:
            excerpt = '...' + excerpt
        if end_pos < len(clean_text):
            excerpt = excerpt + '...'
        
        # Apply highlighting
        highlighted = pattern.sub(r'<mark>\1</mark>', excerpt)
        return highlighted
    
    return clean_text[:max_length] + ('...' if len(clean_text) > max_length else '')
