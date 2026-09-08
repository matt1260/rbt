"""Seed the editable prompt configuration from the constants that used to be
hard-coded in search/translation_utils.py.

Seeding rather than starting empty means behaviour is identical the moment this
migration runs -- the prompt sent to Gemini is byte-for-byte what it was before
the tables existed. Editing only begins to matter when someone actually edits.
"""
from django.db import migrations


CHAPTER_RULES = [   'NEVER modify, alter, or translate ANY HTML tags, attributes, or code',
    'NEVER change: <tag names>, class="...", style="...", href="...", src="...", width="...", '
    'or ANY attribute values',
    'NEVER translate English words that appear inside HTML attributes (like class="tooltip" '
    'or href values)',
    'ONLY translate the human-readable text content that appears BETWEEN opening and closing '
    'tags',
    'Keep <<<VERSE_N>>> markers EXACTLY as written - these are parsing markers, not content',
    'Preserve ALL whitespace, line breaks, and HTML structure exactly',
    'Image URLs must remain EXACTLY as provided - do not translate or modify them',
    'CSS class names, style values, and color codes must remain in English/original form',
    'HTML entities and special characters must be preserved exactly',
    'SPECIAL: If the English text uses the word \'dual\' (e.g., "dual hands"), translate it '
    "to the closest equivalent conveying 'pair' or 'twofold' in the target language",
    'SPECIAL: Try to maintain articular infinitives where possible in the target language, '
    "preserving their grammatical function, e.g. 'the Afflicting of Himself.'",
    'SPECIAL: Try to maintain substantive clauses where possible in the target language, '
    "preserving their grammatical function, e.g. 'the One who is Coming' or 'from the Eyes of "
    "Themselves'.",
    "SPECIAL: Avoid combining emphatic clauses like 'within the Days, these ones,' into "
    'simpler forms; retain the emphasis and structure of the original English.',
    "SPECIAL: Preserve reflexive pronoun emphasis in clauses, e.g., 'they, themselves,' 'you, "
    "yourself,' 'he, himself,' to maintain the original emphasis in translation.",
    "SPECIAL: 'has sevened' and similar uses of 'seven' as a verbal should be translated to "
    "convey 'make seven' or 'cause to be seven' rather than a simple past tense, to preserve "
    'the original meaning and nuance.',
    "SPECIAL: 'self eternal' means 'eternal by one's own nature' or 'reflexively eternal' and "
    "is generally used adjectivally (e.g. 'the self-eternal stone' is a stone that exists of "
    'itself/self-existent) - translate accordingly to preserve this meaning.',
    "SPECIAL: 'the self' is integral to the meaning of certain phrases and should be "
    "preserved in translation (e.g. 'I, self, am striving' or 'learners of self' or he, self, "
    "is coming' - the 'self' emphasizes a reflexivity and should be retained as best as "
    'possible to preserve meaning).',
    'IMPORTANT: This is NOT a standard Bible translation. Translate the English text as-is, '
    'without trying to conform to traditional biblical language or style in the target '
    'language. The goal is a natural, accurate rendering of the English meaning, not a formal '
    '"Bible-like" style.']

FOOTNOTE_RULES = [   'NEVER modify, alter, or translate ANY HTML tags, attributes, or code structure',
    'NEVER change: <p>, <span>, <strong>, <em>, <br>, <ul>, <li>, <h5>, <a>, or ANY tag names',
    'NEVER translate attribute values: class="...", style="...", href="...", etc.',
    "Keep Hebrew/Greek terms in their original language (e.g., ἀρχή, ὁ λόγος, Strong's "
    'numbers)',
    'Keep <<<FOOTNOTE_X>>> markers EXACTLY as they are - these are parsing markers',
    'ONLY translate human-readable English text that appears between HTML tags',
    'Preserve ALL line breaks, indentation, whitespace, and formatting exactly',
    'Do NOT translate: URLs, CSS styles, HTML entities, class names, or code examples',
    'Maintain scholarly, technical tone and theological accuracy']

GLOSSARY = [
    {
        'term': 'Logos Ratio',
        'sense': (
            "Greek \u03bb\u03cc\u03b3\u03bf\u03c2 in its MATHEMATICAL sense: the ratio or proportion "
            "between two quantities, as used by Euclid and Aristotle."
        ),
        'use_guidance': (
            "the target language's ordinary MATHEMATICAL word for 'ratio' -- the one "
            "used for 'a 2:1 ratio' or 'the length-to-width ratio'"
        ),
        'avoid': (
            "words meaning 'word', 'speech', 'message' or 'account', and also any "
            "general 'relation/relationship' word used for connections between "
            "people or things"
        ),
        'overrides': {'pl': 'Stosunek Logos'},
    },
]


def seed(apps, schema_editor):
    PromptRule = apps.get_model('search', 'PromptRule')
    PromptGlossaryTerm = apps.get_model('search', 'PromptGlossaryTerm')
    PromptLanguageOverride = apps.get_model('search', 'PromptLanguageOverride')

    if not PromptRule.objects.exists():
        for i, text in enumerate(CHAPTER_RULES):
            PromptRule.objects.create(scope='chapter', order=i + 1, text=text)
        for i, text in enumerate(FOOTNOTE_RULES):
            PromptRule.objects.create(scope='footnote', order=i + 1, text=text)

    if not PromptGlossaryTerm.objects.exists():
        for i, entry in enumerate(GLOSSARY):
            term = PromptGlossaryTerm.objects.create(
                term=entry['term'], sense=entry['sense'],
                use_guidance=entry['use_guidance'], avoid=entry['avoid'],
                order=i,
            )
            for code, rendering in entry['overrides'].items():
                PromptLanguageOverride.objects.create(
                    term=term, language_code=code, rendering=rendering)


def unseed(apps, schema_editor):
    for model in ('PromptLanguageOverride', 'PromptGlossaryTerm', 'PromptRule'):
        apps.get_model('search', model).objects.all().delete()


class Migration(migrations.Migration):

    dependencies = [
        ('search', '0012_promptglossaryterm_promptrule_promptlanguageoverride'),
    ]

    operations = [migrations.RunPython(seed, unseed)]
