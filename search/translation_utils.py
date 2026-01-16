"""Utilities for multi-lingual verse translations using Gemini API"""

import os
from google import genai
from .models import VerseTranslation

# Comma-separated list of API keys from environment variable
# Format: GEMINI_API_KEYS="key1,key2,key3,..."
GEMINI_API_KEYS_STR = os.getenv('GEMINI_API_KEYS', '')
GEMINI_API_KEYS = [k.strip() for k in GEMINI_API_KEYS_STR.split(',') if k.strip()]

# Debug: Print what we loaded (only first few chars of each key for security)
print(f"[ENV DEBUG] GEMINI_API_KEYS_STR length: {len(GEMINI_API_KEYS_STR)}")
print(f"[ENV DEBUG] Number of API keys loaded: {len(GEMINI_API_KEYS)}")
if GEMINI_API_KEYS:
    print(f"[ENV DEBUG] First key starts with: {GEMINI_API_KEYS[0][:10]}...")
else:
    print(f"[ENV DEBUG] WARNING: No API keys found!")

SUPPORTED_LANGUAGES = {
    'es': 'Español',
    'pt': 'Português',
    'fr': 'Français',
    'de': 'Deutsch',
    'it': 'Italiano',
    'ru': 'Русский',
    'uk': 'Українська',
    'el': 'Ελληνικά',
    'sv': 'Svenska',
    'da': 'Dansk',
    'no': 'Norsk',
    'fi': 'Suomi',
    'cs': 'Čeština',
    'sk': 'Slovenčina',
    'hr': 'Hrvatski',
    'sr': 'Српски',
    'bg': 'Български',
    'ca': 'Català',
    'zh': '中文',
    'zh-TW': '繁體中文',
    'ja': '日本語',
    'ko': '한국어',
    'mn': 'Монгол',
    'ar': 'العربية',
    'hi': 'हिन्दी',
    'bn': 'বাংলা',
    'pa': 'ਪੰਜਾਬੀ',
    'ta': 'தமிழ்',
    'te': 'తెలుగు',
    'mr': 'मराठी',
    'gu': 'ગુજરાતી',
    'kn': 'ಕನ್ನಡ',
    'ml': 'മലയാളം',
    'ur': 'اردو',
    'fa': 'فارسی',
    'ps': 'پښتو',
    'nl': 'Nederlands',
    'pl': 'Polski',
    'tr': 'Türkçe',
    'vi': 'Tiếng Việt',
    'th': 'ไทย',
    'id': 'Bahasa Indonesia',
    'ms': 'Bahasa Melayu',
    'tl': 'Tagalog',
    'km': 'ភាសាខ្មែរ',
    'lo': 'ລາວ',
    'my': 'မြန်မာဘာသာ',
    'ceb': 'Cebuano',
    'jv': 'Basa Jawa',
    'ro': 'Română',
    'hu': 'Magyar',
    'sw': 'Kiswahili',
    'ha': 'Hausa',
    'yo': 'Yorùbá',
    'ig': 'Igbo',
    'am': 'አማርኛ',
    'om': 'Oromoo',
    'zu': 'isiZulu',
    'af': 'Afrikaans',
    'su': 'Basa Sunda',
    'mad': 'Madhurâ',
    'hmn': 'Hmoob',
    'az': 'Azərbaycan dili',
    'ku': 'Kurdî',
    'uz': 'Oʻzbekcha',
    'kk': 'Қазақ тілі',
    'ka': 'ქართული',
    'lt': 'Lietuvių',
    'lv': 'Latviešu',
    'et': 'Eesti',
    'sl': 'Slovenščina',
}


def translate_chapter_batch(verses_dict, target_language_code):
    """Translate entire chapter at once for efficiency
    
    Args:
        verses_dict: Dict of {verse_num: english_text}
                     verse_num = 0 means it's a book name (simple text)
        target_language_code: Target language code
        
    Returns:
        Dict of {verse_num: translated_text}
    """
    print(f"[TRANSLATION DEBUG] batch starting for {len(verses_dict)} verses. Target: {target_language_code}")
    if not GEMINI_API_KEYS:
        print("[TRANSLATION DEBUG] No API key configured")
        return {v: "[Translation unavailable - API key not configured]" for v in verses_dict}
    
    language_name = SUPPORTED_LANGUAGES.get(target_language_code, target_language_code)
    
    # Separate book name from verses
    book_name = verses_dict.get(0)
    verse_dict_only = {k: v for k, v in verses_dict.items() if k != 0}
    
    results = {}
    
    # Translate book name separately if present (simpler prompt)
    if book_name:
        book_prompt = f"""Translate the literal meaning of this phrase to {language_name}: "{book_name}"

IMPORTANT: This is NOT a standard Bible book name. Translate the actual words/meaning, not the biblical book reference.

Examples:
- "He is Favored" → "Él es Favorecido" (Spanish)
- "The Glory" → "La Gloria" (Spanish)
- "The Twins" → "Los Gemelos" (Spanish)
- "He Adds" → "Él Añade" (Spanish)

Return ONLY the translated phrase, no explanation or extra text."""
        
        # Try API keys for book name
        for api_key in GEMINI_API_KEYS:
            try:
                print(f"[TRANSLATION DEBUG] Translating book name: {book_name}")
                client = genai.Client(api_key=api_key)
                response = client.models.generate_content(
                    model='models/gemini-3-flash-preview',
                    contents=book_prompt
                )
                translated_book = response.text.strip() # type: ignore
                results[0] = translated_book
                print(f"[TRANSLATION DEBUG] Book name translated: {translated_book}")
                break  # Success, exit key loop
            except Exception as e:
                error_str = str(e).lower()
                if 'quota' in error_str or 'rate limit' in error_str or 'resource exhausted' in error_str:
                    print(f"[TRANSLATION DEBUG] Book name API key exhausted, trying next...")
                    continue
                else:
                    results[0] = f"[Translation error: {str(e)}]"
                    break
    
    # If no verses, return book name only
    if not verse_dict_only:
        return results
    
    # Build chapter text with verse markers - use more distinctive markers
    chapter_text = ""
    for verse_num in sorted(verse_dict_only.keys()):
        chapter_text += f"<<<VERSE_{verse_num}>>>\n{verse_dict_only[verse_num]}\n\n"
    
    prompt = f"""Translate this Bible chapter to {language_name}.

CRITICAL INSTRUCTIONS - READ CAREFULLY:
1. NEVER modify, alter, or translate ANY HTML tags, attributes, or code
2. NEVER change: <tag names>, class="...", style="...", href="...", src="...", width="...", or ANY attribute values
3. NEVER translate English words that appear inside HTML attributes (like class="tooltip" or href values)
4. ONLY translate the human-readable text content that appears BETWEEN opening and closing tags
5. Keep <<<VERSE_N>>> markers EXACTLY as written - these are parsing markers, not content
6. Preserve ALL whitespace, line breaks, and HTML structure exactly
7. Image URLs must remain EXACTLY as provided - do not translate or modify them
8. CSS class names, style values, and color codes must remain in English/original form
9. HTML entities and special characters must be preserved exactly
10. SPECIAL: If the English text uses the word 'dual' (e.g., "dual hands"), translate it to the closest equivalent conveying 'pair' or 'twofold' in the target language (preserve the paired/twofold nuance; avoid casual "double" translations if the intent is grammatical or lexical).

EXAMPLES OF WHAT TO TRANSLATE:
✓ <h5><span style="color: blue;">The Twins</span></h5>
  → <h5><span style="color: blue;">Los Gemelos</span></h5>
  (Only "The Twins" becomes "Los Gemelos", all HTML stays identical)

✓ <div class="tooltip"><b>The Seed</b><br>Movement slows...</div>
  → <div class="tooltip"><b>La Semilla</b><br>El movimiento se ralentiza...</div>
  (Only text content translated, class name stays "tooltip", <b> and <br> unchanged)

EXAMPLES OF WHAT NEVER TO CHANGE:
✗ class="tooltip-container" → NEVER translate to class="contenedor-de-información"
✗ style="color: blue;" → NEVER translate to style="color: azul;"
✗ href="?footnote=1-1-1" → NEVER modify URLs or parameters
✗ src="http://www.realbible.tech/wp-content/uploads/2024/04/image.jpg" → NEVER change URLs
✗ width="50%" → NEVER translate measurement units or values
✗ <img>, <div>, <span>, <a> → NEVER translate tag names

If you are uncertain whether something should be translated, DO NOT translate it. Only translate obvious human-readable text between tags.

Chapter text:
{chapter_text}

Return ONLY the translated verses with all HTML tags and <<<VERSE_N>>> markers preserved exactly."""
    
    # Try each API key in sequence until one works
    api_keys = GEMINI_API_KEYS
    last_error = None
    
    for api_key in api_keys:
        try:
            print(f"[TRANSLATION DEBUG] Calling Gemini API with key ending in ...{api_key[-4:] if api_key else 'None'}")
            client = genai.Client(api_key=api_key)
            response = client.models.generate_content(
                model='models/gemini-3-flash-preview',
                contents=prompt
            )
            translated_text = response.text.strip() # type: ignore
            print(f"[TRANSLATION DEBUG] API Response received. Length: {len(translated_text)}")
            # print(f"[TRANSLATION DEBUG] Response preview: {translated_text[:100]}...")
            
            # Parse back into verse dictionary using the distinctive markers
            import re
            verse_results = {}
            verse_pattern = r'<<<VERSE_(\d+)>>>\s*(.*?)(?=<<<VERSE_\d+>>>|$)'
            matches = re.findall(verse_pattern, translated_text, re.DOTALL)
            print(f"[TRANSLATION DEBUG] Regex found {len(matches)} verse segments")
            
            for verse_num_str, verse_text in matches:
                verse_num = int(verse_num_str)
                verse_results[verse_num] = verse_text.strip()
            
            # Fallback: if parsing failed, return original with error
            if not verse_results:
                print(f"[TRANSLATION DEBUG] ERROR: Verse parsing failed!")
                print(f"[TRANSLATION DEBUG] First 500 chars of response: {translated_text[:500]}")
                # Merge with book name result if we have it
                if results:
                    return {**results, **{v: f"[Translation parsing error]" for v in verse_dict_only}}
                return {v: f"[Translation parsing error]" for v in verses_dict}
            
            print(f"[TRANSLATION DEBUG] Verse batch completed successfully! {len(verse_results)} verses translated")
            # Merge book name results with verse results
            return {**results, **verse_results}
            
        except Exception as e:
            error_str = str(e).lower()
            last_error = e
            # Check for quota/rate limit errors - if so, try next key
            if 'quota' in error_str or 'rate limit' in error_str or 'resource exhausted' in error_str:
                print(f"[TRANSLATION DEBUG] API key exhausted, trying next key...")
                continue
            else:
                # Non-quota error, fail immediately
                # Merge with book name result if we have it
                error_dict = {v: f"[Translation error: {str(e)}]" for v in verse_dict_only}
                return {**results, **error_dict}
    
    # All keys exhausted
    print(f"[TRANSLATION DEBUG] All API keys exhausted")
    return {'__quota_exceeded__': True}


def translate_footnotes_batch(footnotes_dict, target_language_code):
    """Translate multiple footnotes at once for efficiency
    
    Args:
        footnotes_dict: Dict of {footnote_id: english_footnote_html}
        target_language_code: Target language code
        
    Returns:
        Dict of {footnote_id: translated_footnote_html}
    """
    print(f"[TRANSLATION DEBUG] Footnote batch starting for {len(footnotes_dict)} footnotes. Target: {target_language_code}")
    if not GEMINI_API_KEYS:
        return {f_id: "[Translation unavailable - API key not configured]" for f_id in footnotes_dict}
    
    if not footnotes_dict:
        return {}
    
    language_name = SUPPORTED_LANGUAGES.get(target_language_code, target_language_code)
    
    # Build footnotes text with markers
    footnotes_text = ""
    for footnote_id in sorted(footnotes_dict.keys()):
        footnotes_text += f"<<<FOOTNOTE_{footnote_id}>>>\n{footnotes_dict[footnote_id]}\n\n"
    
    prompt = f"""Translate these Bible footnotes/commentaries to {language_name}.

CRITICAL RULES - NEVER BREAK THESE:
1. NEVER modify, alter, or translate ANY HTML tags, attributes, or code structure
2. NEVER change: <p>, <span>, <strong>, <em>, <br>, <ul>, <li>, <h5>, <a>, or ANY tag names
3. NEVER translate attribute values: class="...", style="...", href="...", etc.
4. Keep Hebrew/Greek terms in their original language (e.g., ἀρχή, ὁ λόγος, Strong's numbers)
5. Keep <<<FOOTNOTE_X>>> markers EXACTLY as they are - these are parsing markers
6. ONLY translate human-readable English text that appears between HTML tags
7. Preserve ALL line breaks, indentation, whitespace, and formatting exactly
8. Do NOT translate: URLs, CSS styles, HTML entities, class names, or code examples
9. Maintain scholarly, technical tone and theological accuracy

EXAMPLES:
✓ <p class="rbt_footnote"><span>The Greek <strong>Ἐν</strong> means "in"</span></p>
  → <p class="rbt_footnote"><span>El griego <strong>Ἐν</strong> significa "en"</span></p>
  (Only descriptive English translated, Greek term and HTML preserved)

✗ NEVER change class="rbt_footnote" to class="nota_rbt"
✗ NEVER translate Strong's #G5316 to Fuerte's #G5316
✗ NEVER modify <strong>ἀρχή</strong> or Greek/Hebrew characters

Footnotes:
{footnotes_text}

Return the translated footnotes with <<<FOOTNOTE_X>>> markers and ALL HTML preserved exactly.
"""
    
    # Try each API key in sequence until one works
    api_keys = GEMINI_API_KEYS
    last_error = None
    
    for key_idx, api_key in enumerate(api_keys):
        try:
            print(f"[TRANSLATION DEBUG] Footnotes: Trying API key {key_idx + 1}/{len(api_keys)} (ending ...{api_key[-4:] if api_key else 'None'})")
            client = genai.Client(api_key=api_key)
            response = client.models.generate_content(
                model='models/gemini-3-flash-preview',
                contents=prompt
            )
            translated_text = response.text.strip() # type: ignore
            print(f"[TRANSLATION DEBUG] Footnotes API response received. Length: {len(translated_text)}")
            
            # Parse back into footnote dictionary
            import re
            result = {}
            
            # Split by the marker pattern to get individual footnotes
            # Pattern: <<<FOOTNOTE_XXXXX>>> followed by content
            parts = re.split(r'<<<FOOTNOTE_([^>]+)>>>', translated_text)
            
            # parts will be: [preamble, id1, content1, id2, content2, ...]
            # So we iterate pairs starting at index 1
            if len(parts) > 1:
                for i in range(1, len(parts) - 1, 2):
                    footnote_id = parts[i].strip()
                    footnote_content = parts[i + 1].strip() if i + 1 < len(parts) else ''
                    if footnote_id and footnote_content:
                        result[footnote_id] = footnote_content
            
            print(f"[TRANSLATION DEBUG] Parsed {len(result)} footnotes from response (split method)")
            
            # Debug: if we got fewer than expected, log what we found
            if len(result) < len(footnotes_dict):
                print(f"[TRANSLATION DEBUG] WARNING: Expected {len(footnotes_dict)} footnotes, got {len(result)}")
                print(f"[TRANSLATION DEBUG] Found IDs: {list(result.keys())[:10]}...")
            
            # Fallback: if parsing failed, return error
            if not result:
                print(f"[TRANSLATION DEBUG] ERROR: Parsing failed, no footnotes extracted!")
                print(f"[TRANSLATION DEBUG] Response length: {len(translated_text)} chars")
                print(f"[TRANSLATION DEBUG] First 500 chars: {translated_text[:500]}")
                return {f_id: f"[Translation parsing error]" for f_id in footnotes_dict}
            
            print(f"[TRANSLATION DEBUG] Footnote batch completed successfully! {len(result)} footnotes translated")
            return result
            
        except Exception as e:
            error_str = str(e).lower()
            last_error = e
            # Check for quota/rate limit errors - if so, try next key
            if 'quota' in error_str or 'rate limit' in error_str or 'resource exhausted' in error_str:
                print(f"[TRANSLATION DEBUG] API key {key_idx + 1}/{len(api_keys)} exhausted, trying next key...")
                continue
            else:
                # Non-quota error, fail immediately
                print(f"[TRANSLATION DEBUG] Non-quota error: {str(e)}")
                return {f_id: f"[Translation error: {str(e)}]" for f_id in footnotes_dict}
    
    # All keys exhausted
    print(f"[TRANSLATION DEBUG] All {len(api_keys)} API keys exhausted")
    return {'__quota_exceeded__': True}


def translate_verse_text(english_text, target_language_code):
    """Translate verse text to target language using Gemini API"""
    if not GEMINI_API_KEYS:
        return f"[Translation unavailable - API key not configured]"
    
    language_name = SUPPORTED_LANGUAGES.get(target_language_code, target_language_code)
    
    prompt = f"""Translate this Bible verse to {language_name}. 
Preserve all HTML tags exactly as they are (span, h5, a, etc.).
Keep the theological meaning accurate and natural in {language_name}. Don't assume contexts, idioms, or metaphors.
This does NOT follow traditional biblical translation methods or conventions.

IMPORTANT TRANSLATION POINTS: 
1) If the English phrase includes the word 'dual' (for example, "dual hands"), render it to the closest equivalent that conveys 'pair' or 'twofold' in the target language (preserve the 'paired/twofold' nuance; avoid casual translations like 'double' or 'both' when the intent is grammatical or lexical).
2) 'has sevened' and other similar uses of seven as verbal equate to 'make seven' or 'cause to be seven' - translate accordingly.
3) 'self eternal' means 'eternal by one's own nature' or 'reflexively eternal' and is generally used adjectivally e.g. 'the self-eternal stone' is a stone that exists of itself/self-existent - translate accordingly.
4) Articular infinitives (e.g. 'Within the Standing Up') should be treated as verbal nouns (i.e. 'the act of standing up') - translate accordingly.

English text:
{english_text}

Return only the translated text with HTML tags preserved."""
    
    try:
        client = genai.Client(api_key=GEMINI_API_KEYS[0])
        response = client.models.generate_content(
            model='models/gemini-3-flash-preview',
            contents=prompt
        )
        return response.text.strip() # type: ignore
    except Exception as e:
        return f"[Translation error: {str(e)}]"


def translate_footnote_text(english_footnote, target_language_code):
    """Translate footnote text to target language using Gemini API"""
    if not GEMINI_API_KEYS:
        return f"[Translation unavailable - API key not configured]"
    
    language_name = SUPPORTED_LANGUAGES.get(target_language_code, target_language_code)
    
    prompt = f"""Translate this Bible footnote/commentary to {language_name}.
Preserve all HTML tags and formatting exactly.
Keep Hebrew/Greek terms in their original language.
Maintain scholarly tone and accuracy.

IMPORTANT TRANSLATION POINTS: 
1) If the English phrase includes the word 'dual' (for example, "dual hands"), render it to the closest equivalent that conveys 'pair' or 'twofold' in the target language (preserve the 'paired/twofold' nuance; avoid casual translations like 'double' or 'both' when the intent is grammatical or lexical).
2) 'has sevened' and other similar uses of seven as verbal equate to 'make seven' or 'cause to be seven' - translate accordingly.
3) 'self eternal' means 'eternal by one's own nature' or 'reflexively eternal' and is generally used adjectivally e.g. 'the self-eternal stone' is a stone that exists of itself/self-existent - translate accordingly.
4) Articular infinitives (e.g. 'Within the Standing Up') should be treated as verbal nouns (i.e. 'the act of standing up') - translate accordingly.

English footnote:
{english_footnote}

Return only the translated text with HTML tags preserved."""
    
    try:
        client = genai.Client(api_key=GEMINI_API_KEYS[0])
        response = client.models.generate_content(
            model='models/gemini-3-flash-preview',
            contents=prompt
        )
        return response.text.strip() # type: ignore
    except Exception as e:
        return f"[Translation error: {str(e)}]"


def get_or_create_verse_translation(book, chapter, verse, language_code, english_text):
    """Get cached translation or create new one on-demand"""
    if language_code == 'en':
        return english_text
    
    # Check if translation exists
    translation = VerseTranslation.objects.filter(
        book=book,
        chapter=chapter,
        verse=verse,
        language_code=language_code,
        verse_text__isnull=False
    ).first()
    
    if translation:
        return translation.verse_text
    
    # Generate new translation
    translated_text = translate_verse_text(english_text, language_code)
    
    # Save to database
    VerseTranslation.objects.create(
        book=book,
        chapter=chapter,
        verse=verse,
        language_code=language_code,
        verse_text=translated_text,
        status='ai_generated'
    )
    
    return translated_text


def get_or_create_footnote_translation(footnote_id, language_code, english_footnote):
    """Get cached footnote translation or create new one"""
    if language_code == 'en':
        return english_footnote
    
    # Parse footnote ID to extract book/chapter/verse
    # Format: "Eze-16-4-07" or "1-3-15"
    parts = footnote_id.split('-')
    if len(parts) >= 3:
        book = parts[0]
        chapter = int(parts[1])
        verse = int(parts[2])
    else:
        book = 'Unknown'
        chapter = 0
        verse = 0
    
    # Check if translation exists
    translation = VerseTranslation.objects.filter(
        book=book,
        chapter=chapter,
        verse=verse,
        language_code=language_code,
        footnote_id=footnote_id,
        footnote_text__isnull=False
    ).first()
    
    if translation:
        return translation.footnote_text
    
    # Generate new translation
    translated_text = translate_footnote_text(english_footnote, language_code)
    
    # Save to database
    VerseTranslation.objects.create(
        book=book,
        chapter=chapter,
        verse=verse,
        language_code=language_code,
        footnote_id=footnote_id,
        footnote_text=translated_text,
        status='ai_generated'
    )
    
    return translated_text
