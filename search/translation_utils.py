"""Utilities for multi-lingual verse translations using Gemini API"""

import os
from google import genai
from .models import VerseTranslation, GeminiUsageLog

# Comma-separated list of API keys from environment variable
# Format: GEMINI_API_KEYS="key1,key2,key3,..."
GEMINI_API_KEYS_STR = os.getenv('GEMINI_API_KEYS', '')
GEMINI_API_KEYS = [k.strip() for k in GEMINI_API_KEYS_STR.split(',') if k.strip()]
ENABLE_VERBOSE_DEBUG = os.getenv('ENABLE_VERBOSE_DEBUG', 'False') == 'True'

# Debug: Print what we loaded (only first few chars of each key for security)
if ENABLE_VERBOSE_DEBUG:
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


# Fallback instruction sets. These are what shipped hard-coded in the prompt and
# what migration 0013 seeds PromptRule with. Kept here so prompt building still
# works if the table is missing, empty, or unreadable -- Gemini must never be sent
# a prompt with no rules just because a migration has not run.
FALLBACK_RULES = {
    'chapter': [       'NEVER modify, alter, or translate ANY HTML tags, attributes, or code',
        'NEVER change: <tag names>, class="...", style="...", href="...", src="...", '
        'width="...", or ANY attribute values',
        'NEVER translate English words that appear inside HTML attributes (like '
        'class="tooltip" or href values)',
        'ONLY translate the human-readable text content that appears BETWEEN opening and '
        'closing tags',
        'Keep <<<VERSE_N>>> markers EXACTLY as written - these are parsing markers, not '
        'content',
        'Preserve ALL whitespace, line breaks, and HTML structure exactly',
        'Image URLs must remain EXACTLY as provided - do not translate or modify them',
        'CSS class names, style values, and color codes must remain in English/original '
        'form',
        'HTML entities and special characters must be preserved exactly',
        'SPECIAL: If the English text uses the word \'dual\' (e.g., "dual hands"), '
        "translate it to the closest equivalent conveying 'pair' or 'twofold' in the "
        'target language',
        'SPECIAL: Try to maintain articular infinitives where possible in the target '
        "language, preserving their grammatical function, e.g. 'the Afflicting of "
        "Himself.'",
        'SPECIAL: Try to maintain substantive clauses where possible in the target '
        "language, preserving their grammatical function, e.g. 'the One who is Coming' or "
        "'from the Eyes of Themselves'.",
        "SPECIAL: Avoid combining emphatic clauses like 'within the Days, these ones,' "
        'into simpler forms; retain the emphasis and structure of the original English.',
        "SPECIAL: Preserve reflexive pronoun emphasis in clauses, e.g., 'they, "
        "themselves,' 'you, yourself,' 'he, himself,' to maintain the original emphasis in "
        'translation.',
        "SPECIAL: 'has sevened' and similar uses of 'seven' as a verbal should be "
        "translated to convey 'make seven' or 'cause to be seven' rather than a simple "
        'past tense, to preserve the original meaning and nuance.',
        "SPECIAL: 'self eternal' means 'eternal by one's own nature' or 'reflexively "
        "eternal' and is generally used adjectivally (e.g. 'the self-eternal stone' is a "
        'stone that exists of itself/self-existent) - translate accordingly to preserve '
        'this meaning.',
        "SPECIAL: 'the self' is integral to the meaning of certain phrases and should be "
        "preserved in translation (e.g. 'I, self, am striving' or 'learners of self' or "
        "he, self, is coming' - the 'self' emphasizes a reflexivity and should be retained "
        'as best as possible to preserve meaning).',
        'IMPORTANT: This is NOT a standard Bible translation. Translate the English text '
        'as-is, without trying to conform to traditional biblical language or style in the '
        'target language. The goal is a natural, accurate rendering of the English '
        'meaning, not a formal "Bible-like" style.'],
    'footnote': [       'NEVER modify, alter, or translate ANY HTML tags, attributes, or code structure',
        'NEVER change: <p>, <span>, <strong>, <em>, <br>, <ul>, <li>, <h5>, <a>, or ANY '
        'tag names',
        'NEVER translate attribute values: class="...", style="...", href="...", etc.',
        "Keep Hebrew/Greek terms in their original language (e.g., ἀρχή, ὁ λόγος, Strong's "
        'numbers)',
        'Keep <<<FOOTNOTE_X>>> markers EXACTLY as they are - these are parsing markers',
        'ONLY translate human-readable English text that appears between HTML tags',
        'Preserve ALL line breaks, indentation, whitespace, and formatting exactly',
        'Do NOT translate: URLs, CSS styles, HTML entities, class names, or code examples',
        'Maintain scholarly, technical tone and theological accuracy'],
}


# ── RBT terminology glossary ──────────────────────────────────────────────
# RBT renders some Greek/Hebrew words with a deliberate technical sense that a
# general-purpose translator gets wrong. Gemini translated "The Logos Ratio"
# into Polish as "Relacja Logos" -- defensible for a relation between things,
# but wrong here: the intended sense is the mathematical one, where Polish
# wants "stosunek".
#
# Each entry states the SENSE in English, which steers all 70+ target languages
# at once. LANGUAGE_TERM_OVERRIDES then pins exact wording for the languages
# where the correct term is known. Add to either as more cases surface.

TRANSLATION_GLOSSARY = [
    {
        'term': 'Logos Ratio',
        'sense': (
            "Greek λόγος in its MATHEMATICAL sense: the ratio or proportion between "
            "two quantities, as used by Euclid and Aristotle."
        ),
        'use': (
            "the target language's ordinary MATHEMATICAL word for 'ratio' -- the one "
            "used for 'a 2:1 ratio' or 'the length-to-width ratio'"
        ),
        'avoid': (
            "words meaning 'word', 'speech', 'message' or 'account', and also any "
            "general 'relation/relationship' word used for connections between "
            "people or things"
        ),
    },
]

# language_code -> {english term: exact preferred rendering}
LANGUAGE_TERM_OVERRIDES = {
    'pl': {
        # "relacja" can carry a quantitative sense, but "stosunek" is the
        # conventional Polish mathematical term for ratio.
        'Logos Ratio': 'Stosunek Logos',
    },
}

# These are translator-facing observations, not universal rules. They tell the
# model what semantic information must survive when English leaves a pronoun or
# a deliberately unusual theological image under-specified in the target
# language. The database model below makes them editable from the dashboard.
LANGUAGE_TRANSLATION_AWARENESS = {
    code: (
        f"Translate naturally in {name}. Preserve the source's semantic roles, "
        "including who is acting and who is being acted upon; do not let a "
        "natural paraphrase erase a deliberate personification."
    )
    for code, name in SUPPORTED_LANGUAGES.items()
}

LANGUAGE_TRANSLATION_AWARENESS.update({
    'he': (
        "Hebrew marks grammatical gender strongly. When 'the Separation' is the "
        "personified feminine prophetic figure and the source says 'she will "
        "condemn her', use feminine agreement and the feminine object form for "
        "the Separation, not a neuter or masculine substitute."
    ),
    'es': (
        "Spanish distinguishes la/ella from lo/ello. In personified prophetic "
        "language, 'the Separation' is a feminine woman-like referent: retain "
        "la/ella or another natural feminine construction, rather than lo or "
        "eso meaning 'it'."
    ),
    'pt': (
        "Portuguese distinguishes a/ela from o/ele/isso. Treat the personified "
        "feminine 'Separation' as a woman-like feminine referent and preserve "
        "ela/a or an explicit feminine noun where needed, rather than isso."
    ),
    'fr': (
        "French requires attention to elle/la versus il/le/ça. The personified "
        "'Séparation' is feminine and woman-like in this passage; preserve that "
        "feminine reference in the object pronoun or state it explicitly."
    ),
    'de': (
        "German gender follows the chosen noun. Keep the personified 'Trennung' "
        "as feminine and use sie/sie or another feminine construction for the "
        "referent, not es, even though an abstract noun may tempt an impersonal "
        "rendering."
    ),
    'it': (
        "Italian distinguishes la/lei from lo. The personified feminine "
        "'separazione' is a woman-like referent here; preserve la/lei or an "
        "explicit feminine noun, not lo/esso."
    ),
    'ru': (
        "Russian case and gender are important: the personified 'разделение' is "
        "the feminine prophetic figure in this passage. Render the object with "
        "the feminine form её, not masculine его or an impersonal это."
    ),
    'uk': (
        "Ukrainian case and gender are important: the personified 'розділення' is "
        "the feminine prophetic figure. Render the object with feminine її, not "
        "masculine його or an impersonal це."
    ),
    'pl': (
        "Polish case and gender are important: the personified feminine "
        "'separacja' is the referent. Use feminine ją or an explicit feminine "
        "noun, not neuter je."
    ),
    'cs': (
        "Czech case and gender are important: the personified feminine "
        "'Oddělení' is the referent. Preserve feminine ji or an explicit feminine "
        "construction, not neuter ho/to."
    ),
    'sk': (
        "Slovak case and gender are important: keep the personified feminine "
        "referent feminine in the object form, rather than using a neuter form."
    ),
    'hr': (
        "Croatian uses gendered object forms. The personified 'Razdvajanje' is "
        "feminine here; use feminine nju or an explicit feminine noun, not a "
        "masculine/neuter object."
    ),
    'sr': (
        "Serbian uses gendered object forms. The personified 'Раздвајање' is "
        "feminine here; use feminine њу or an explicit feminine noun, not a "
        "masculine/neuter object."
    ),
    'bg': (
        "Bulgarian distinguishes feminine я from neuter го/това. Keep the "
        "personified Separation feminine rather than impersonal."
    ),
    'el': (
        "Greek gender and case matter. The personified 'Χωρισμός' should remain "
        "a feminine woman-like prophetic referent in this passage; preserve the "
        "feminine object form or make the woman-like referent explicit."
    ),
    'ar': (
        "Arabic gender and agreement matter. The personified Separation is a "
        "feminine prophetic figure; use feminine agreement and a feminine object "
        "reference such as إياها, not a masculine or inanimate هذا/ذلك."
    ),
    'fa': (
        "Persian pronouns are often gender-neutral, so make the antecedent clear "
        "with an explicit feminine expression such as 'that woman' when a bare "
        "او/آن could otherwise mean an inanimate 'it'."
    ),
    'ur': (
        "Urdu gender and honorific agreement matter. Keep the personified "
        "Separation feminine and use a feminine person reference, or explicitly "
        "say 'that woman', rather than an inanimate object reference."
    ),
    'hi': (
        "Hindi gender and agreement matter. The personified Separation is feminine; "
        "use उसे/उस स्त्री को or another natural feminine person reference, not a "
        "neuter-style 'that thing'."
    ),
    'bn': (
        "Bengali pronouns do not reliably mark gender. When a bare তাকে could be "
        "ambiguous, use an explicit feminine expression such as সেই নারীকে so the "
        "referent cannot become an inanimate 'it'."
    ),
    'pa': (
        "Punjabi gender and person reference matter. Preserve the feminine woman-like "
        "referent, using a feminine pronoun or an explicit phrase such as ਉਸ ਔਰਤ ਨੂੰ, "
        "not an inanimate ਇਸਨੂੰ."
    ),
    'ta': (
        "Tamil can use an inanimate neuter form for 'it'. This passage personifies "
        "the Separation as feminine; use அவளை or an explicit feminine person noun, "
        "not அதைக்."
    ),
    'ja': (
        "Japanese has no obligatory grammatical gender. Because this is a deliberate "
        "female personification, use 彼女 or an explicit feminine person expression "
        "rather than それ, which makes the referent inanimate."
    ),
    'ko': (
        "Korean has no obligatory grammatical gender. Preserve the deliberate female "
        "personification with 그녀 or an explicit woman-like expression, rather than "
        "그것, which makes the referent inanimate."
    ),
    'zh': (
        "Written Chinese distinguishes 她 from 它. The personified Separation is "
        "feminine; use 她 or an explicit feminine person expression, never 它."
    ),
    'zh-TW': (
        "Written Traditional Chinese distinguishes 她 from 它. The personified "
        "Separation is feminine; use 她 or an explicit feminine person expression, "
        "never 它."
    ),
    'th': (
        "Thai pronouns can be gender-neutral or inanimate. Preserve the female "
        "personification with a feminine person reference such as เธอ or an explicit "
        "woman expression, not มัน."
    ),
    'vi': (
        "Vietnamese pronouns encode social/person reference rather than grammatical "
        "gender. Use bà ấy/cô ấy or another feminine person reference for the "
        "personified Separation, not nó, which makes it inanimate."
    ),
    'id': (
        "Indonesian pronouns are gender-neutral. Make this deliberate female "
        "personification explicit with perempuan itu or another natural feminine "
        "person expression instead of leaving -nya ambiguous."
    ),
    'sw': (
        "Swahili noun classes can make an abstract noun sound inanimate. Preserve "
        "the personified female referent with the appropriate human/feminine form "
        "huyo or mwanamke huyo rather than hicho."
    ),
    'am': (
        "Amharic gendered pronouns matter here. Use the feminine object form 그녀-like "
        "equivalent እሷን for the personified Separation, not masculine እርሱን."
    ),
    'om': (
        "Oromo gendered pronouns matter here. Preserve the feminine object form "
        "ishee for the personified Separation, not masculine/inanimate isa."
    ),
    'yo': (
        "Yoruba pronouns are generally gender-neutral. Make the personified female "
        "referent explicit with obìnrin náà when a bare pronoun could mean an object."
    ),
    'ig': (
        "Igbo pronouns are generally gender-neutral. Make the personified female "
        "referent explicit with nwanyị ahụ when a bare pronoun could mean an object."
    ),
})


def _db_language_guidance(target_language_code):
    """Return editable language awareness text, or None if DB config is unavailable."""
    try:
        from search.models import PromptLanguageGuidance
        row = (PromptLanguageGuidance.objects
               .filter(language_code=target_language_code, active=True)
               .values_list('guidance', flat=True)
               .first())
        return row or None
    except Exception:
        return None


def build_language_awareness_section(target_language_code):
    """Render contextual guidance for the target language."""
    guidance = _db_language_guidance(target_language_code)
    if guidance is None:
        guidance = LANGUAGE_TRANSLATION_AWARENESS.get(target_language_code)
    if not guidance:
        return ''
    return (
        "\n\nSEMANTIC AWARENESS FOR THIS LANGUAGE:\n"
        "These observations describe meaning to preserve; apply them naturally, "
        "without adding explanations to the translation:\n"
        f"- {guidance}"
    )


def _db_rules(scope):
    """Active PromptRule texts for `scope`, or None if the table cannot be used.

    Returning None (never []) lets the caller tell "configured as empty" apart
    from "database unavailable", so a migration that has not run yet falls back
    to the code constants rather than sending Gemini a prompt with no rules.
    """
    try:
        from search.models import PromptRule
        rows = list(
            PromptRule.objects
            .filter(active=True)
            .filter(scope__in=[scope, 'both'])
            .order_by('order', 'id')
            .values_list('text', flat=True)
        )
        return rows or None
    except Exception:
        return None


def build_rules_section(scope):
    """The numbered instruction list for one prompt, as sent."""
    rules = _db_rules(scope)
    if rules is None:
        rules = FALLBACK_RULES.get(scope, [])
    return '\n'.join(f'{i}. {text}' for i, text in enumerate(rules, start=1))


def _db_glossary(target_language_code):
    """(entries, overrides) from the DB, or (None, None) when unavailable."""
    try:
        from search.models import PromptGlossaryTerm
        entries, overrides = [], {}
        qs = (PromptGlossaryTerm.objects
              .filter(active=True)
              .order_by('order', 'term')
              .prefetch_related('overrides'))
        for t in qs:
            entries.append({
                'term': t.term,
                'sense': t.sense,
                'use': t.use_guidance,
                'avoid': t.avoid,
            })
            for o in t.overrides.all():
                if o.active and o.language_code == target_language_code:
                    overrides[t.term] = o.rendering
        return (entries or None), overrides
    except Exception:
        return None, None


def build_glossary_section(target_language_code):
    """Render the glossary as a prompt section, or '' when there is nothing to say.

    Shared by the chapter and footnote prompts so the two cannot drift. Reads the
    editable configuration, falling back to the module constants.
    """
    entries, overrides = _db_glossary(target_language_code)
    if entries is None:
        entries = TRANSLATION_GLOSSARY
        overrides = LANGUAGE_TERM_OVERRIDES.get(target_language_code, {})

    if not entries and not overrides:
        return ''

    lines = [
        "",
        "TERMINOLOGY - THESE OVERRIDE YOUR DEFAULT WORD CHOICE:",
        "These English phrases carry a specific technical sense. Translate the SENSE "
        "described, not the most common dictionary meaning of the English words.",
        "",
    ]

    for entry in entries:
        term = entry['term']
        lines.append(f'- "{term}"')
        lines.append(f"    Sense: {entry['sense']}")
        lines.append(f"    Use: {entry['use']}.")
        if entry.get('avoid'):
            lines.append(f"    Do NOT use: {entry['avoid']}.")
        if term in overrides:
            lines.append(
                f'    REQUIRED for this language: render "{term}" as "{overrides[term]}". '
                "Inflect it naturally for grammatical case, number and agreement as the "
                "sentence requires -- keep the vocabulary, not the exact surface form."
            )
        lines.append("")

    extra = {k: v for k, v in overrides.items()
             if k not in {e['term'] for e in entries}}
    if extra:
        lines.append("Additional required renderings for this language:")
        for term, target in extra.items():
            lines.append(f'- "{term}" -> "{target}" (inflect naturally as needed)')
        lines.append("")

    return "\n".join(lines)


def translate_chapter_batch(verses_dict, target_language_code, chapter=None):
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
                    model='models/gemini-3.8-flash',
                    contents=book_prompt
                )
                translated_book = (response.text or '').strip() # type: ignore
                results[0] = translated_book
                print(f"[TRANSLATION DEBUG] Book name translated: {translated_book}")
                _log_gemini_usage(api_key, 'book_name', target_language_code, book=book_name)
                break  # Success, exit key loop
            except Exception as e:
                error_str = str(e).lower()
                status_code = 429 if 'quota' in error_str or 'rate limit' in error_str or 'resource exhausted' in error_str else 500
                _log_gemini_usage(api_key, 'book_name', target_language_code, book=book_name, status_code=status_code, error_message=str(e))
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
    
    glossary_section = build_glossary_section(target_language_code)
    language_awareness_section = build_language_awareness_section(target_language_code)
    rules_section = build_rules_section('chapter')

    prompt = f"""Translate this Bible chapter to {language_name}.

CRITICAL INSTRUCTIONS - READ CAREFULLY:
{rules_section}
{glossary_section}
{language_awareness_section}
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
    
    # Helpers
    def _parse_verse_results(translated_text: str):
        import re
        verse_results = {}
        verse_pattern = r'<<<VERSE_(\d+)>>>\s*(.*?)(?=<<<VERSE_\d+>>>|$)'
        matches = re.findall(verse_pattern, translated_text, re.DOTALL)
        print(f"[TRANSLATION DEBUG] Regex found {len(matches)} verse segments")
        for verse_num_str, verse_text in matches:
            verse_num = int(verse_num_str)
            verse_results[verse_num] = verse_text.strip()
        return verse_results

    def _call_model(client, model_name: str, prompt_text: str) -> str:
        response = client.models.generate_content(
            model=model_name,
            contents=prompt_text
        )
        return (response.text or '').strip()  # type: ignore

    # Try each API key in sequence until one works
    api_keys = GEMINI_API_KEYS
    last_error = None
    
    for api_key in api_keys:
        try:
            print(f"[TRANSLATION DEBUG] Calling Gemini API with key ending in ...{api_key[-4:] if api_key else 'None'}")
            client = genai.Client(api_key=api_key)
            translated_text = _call_model(client, 'models/gemini-3.8-flash', prompt)
            print(f"[TRANSLATION DEBUG] API Response received. Length: {len(translated_text)}")
            _log_gemini_usage(api_key, 'chapter', target_language_code, book=book_name, chapter=chapter)
            # print(f"[TRANSLATION DEBUG] Response preview: {translated_text[:100]}...")
            
            verse_results = _parse_verse_results(translated_text) if translated_text else {}

            # Fallback: retry with gemini-3.6-flash if parsing failed or empty
            if not verse_results:
                print(f"[TRANSLATION DEBUG] Primary model parsing failed or empty. Retrying with gemini-3.6-flash...")
                translated_text = _call_model(client, 'models/gemini-3.6-flash', prompt)
                print(f"[TRANSLATION DEBUG] Fallback response received. Length: {len(translated_text)}")
                verse_results = _parse_verse_results(translated_text) if translated_text else {}

            if not verse_results:
                print(f"[TRANSLATION DEBUG] ERROR: Verse parsing failed after fallback!")
                if translated_text:
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
            status_code = 429 if 'quota' in error_str or 'rate limit' in error_str or 'resource exhausted' in error_str else 500
            _log_gemini_usage(api_key, 'chapter', target_language_code, book=book_name, chapter=chapter, status_code=status_code, error_message=str(e))
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
    
    glossary_section = build_glossary_section(target_language_code)
    rules_section = build_rules_section('footnote')

    prompt = f"""Translate these Bible footnotes/commentaries to {language_name}.

CRITICAL RULES - NEVER BREAK THESE:
{rules_section}
{glossary_section}
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
                model='models/gemini-3.8-flash',
                contents=prompt
            )
            translated_text = (response.text or '').strip() # type: ignore
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
            
            # Fallback: retry with gemini-3.6-flash if parsing failed or empty
            if not result:
                print(f"[TRANSLATION DEBUG] Footnotes parsing failed or empty. Retrying with gemini-3.6-flash...")
                response = client.models.generate_content(
                    model='models/gemini-3.6-flash',
                    contents=prompt
                )
                translated_text = (response.text or '').strip() # type: ignore
                print(f"[TRANSLATION DEBUG] Footnotes fallback response length: {len(translated_text)}")
                parts = re.split(r'<<<FOOTNOTE_([^>]+)>>>', translated_text)
                if len(parts) > 1:
                    for i in range(1, len(parts) - 1, 2):
                        footnote_id = parts[i].strip()
                        footnote_content = parts[i + 1].strip() if i + 1 < len(parts) else ''
                        if footnote_id and footnote_content:
                            result[footnote_id] = footnote_content

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
            model='models/gemini-3.8-flash',
            contents=prompt
        )
        return (response.text or '').strip() # type: ignore
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
            model='models/gemini-3.8-flash',
            contents=prompt
        )
        return (response.text or '').strip() # type: ignore
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

def _log_gemini_usage(api_key, request_type, language_code, book=None, chapter=None, status_code=200, error_message=None):
    try:
        from .models import GeminiUsageLog
        abbrev = f"...{api_key[-4:]}" if api_key else "None"
        GeminiUsageLog.objects.create(
            api_key_abbrev=abbrev,
            request_type=request_type,
            language_code=language_code,
            book=book,
            chapter=chapter,
            status_code=status_code,
            error_message=str(error_message)[:200] if error_message else None
        )
    except Exception as e:
        print(f"[TRANSLATION LOG ERROR] {e}")
