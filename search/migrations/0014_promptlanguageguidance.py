from django.db import migrations, models


GUIDANCE = {
    'es': "Spanish distinguishes la/ella from lo/ello. In personified prophetic language, the Separation is a feminine woman-like referent: retain la/ella or another natural feminine construction, rather than lo or eso meaning 'it'.",
    'pt': "Portuguese distinguishes a/ela from o/ele/isso. Treat the personified feminine Separation as a woman-like referent and preserve ela/a or an explicit feminine noun where needed, rather than isso.",
    'fr': "French requires attention to elle/la versus il/le/ça. The personified Separation is feminine and woman-like in this passage; preserve that feminine reference in the object pronoun or state it explicitly.",
    'de': "German gender follows the chosen noun. Keep the personified Trennung as feminine and use sie or another feminine construction for the referent, not es.",
    'it': "Italian distinguishes la/lei from lo. The personified feminine separazione is a woman-like referent here; preserve la/lei or an explicit feminine noun, not lo/esso.",
    'ru': "Russian case and gender are important: the personified Separation is the feminine prophetic figure. Render the object with feminine её, not masculine его or an impersonal это.",
    'uk': "Ukrainian case and gender are important: the personified Separation is the feminine prophetic figure. Render the object with feminine її, not masculine його or an impersonal це.",
    'pl': "Polish case and gender are important: the personified feminine Separation is the referent. Use feminine ją or an explicit feminine noun, not neuter je.",
    'cs': "Czech case and gender are important: the personified feminine Separation is the referent. Preserve feminine ji or an explicit feminine construction, not neuter ho/to.",
    'hr': "Croatian uses gendered object forms. The personified Separation is feminine here; use feminine nju or an explicit feminine noun, not a masculine/neuter object.",
    'sr': "Serbian uses gendered object forms. The personified Separation is feminine here; use feminine њу or an explicit feminine noun, not a masculine/neuter object.",
    'el': "Greek gender and case matter. The personified Separation should remain a feminine woman-like prophetic referent; preserve the feminine object form or make the woman-like referent explicit.",
    'ar': "Arabic gender and agreement matter. The personified Separation is a feminine prophetic figure; use feminine agreement and a feminine object reference such as إياها, not a masculine or inanimate reference.",
    'fa': "Persian pronouns are often gender-neutral, so make the antecedent clear with an explicit feminine expression such as 'that woman' when a bare pronoun could mean an inanimate 'it'.",
    'ur': "Urdu gender and agreement matter. Keep the personified Separation feminine and use a feminine person reference, or explicitly say 'that woman', rather than an inanimate object reference.",
    'hi': "Hindi gender and agreement matter. The personified Separation is feminine; use उसे/उस स्त्री को or another natural feminine person reference, not a neuter-style 'that thing'.",
    'bn': "Bengali pronouns do not reliably mark gender. When a bare pronoun could be ambiguous, use an explicit feminine expression such as সেই নারীকে so the referent cannot become an inanimate 'it'.",
    'pa': "Punjabi gender and person reference matter. Preserve the feminine woman-like referent with a feminine pronoun or explicit woman expression, not an inanimate form.",
    'ta': "Tamil can use an inanimate neuter form for 'it'. This passage personifies the Separation as feminine; use அவளை or an explicit feminine person noun, not அதைக்.",
    'ja': "Japanese has no obligatory grammatical gender. Because this is a deliberate female personification, use 彼女 or an explicit feminine person expression rather than それ, which makes the referent inanimate.",
    'ko': "Korean has no obligatory grammatical gender. Preserve the deliberate female personification with 그녀 or an explicit woman-like expression, rather than 그것, which makes the referent inanimate.",
    'zh': "Written Chinese distinguishes 她 from 它. The personified Separation is feminine; use 她 or an explicit feminine person expression, never 它.",
    'zh-TW': "Written Traditional Chinese distinguishes 她 from 它. The personified Separation is feminine; use 她 or an explicit feminine person expression, never 它.",
    'th': "Thai pronouns can be gender-neutral or inanimate. Preserve the female personification with a feminine person reference such as เธอ or an explicit woman expression, not มัน.",
    'vi': "Vietnamese pronouns encode social/person reference. Use bà ấy/cô ấy or another feminine person reference for the personified Separation, not nó, which makes it inanimate.",
    'id': "Indonesian pronouns are gender-neutral. Make this deliberate female personification explicit with perempuan itu or another natural feminine person expression instead of leaving a bare pronoun ambiguous.",
    'sw': "Swahili noun classes can make an abstract noun sound inanimate. Preserve the personified female referent with the appropriate human/feminine form huyo or mwanamke huyo rather than hicho.",
    'am': "Amharic gendered pronouns matter here. Use the feminine object form እሷን for the personified Separation, not masculine እርሱን.",
    'om': "Oromo gendered pronouns matter here. Preserve the feminine object form ishee for the personified Separation, not masculine/inanimate isa.",
    'yo': "Yoruba pronouns are generally gender-neutral. Make the personified female referent explicit with obìnrin náà when a bare pronoun could mean an object.",
    'ig': "Igbo pronouns are generally gender-neutral. Make the personified female referent explicit with nwanyị ahụ when a bare pronoun could mean an object.",
}


def seed(apps, schema_editor):
    Guidance = apps.get_model('search', 'PromptLanguageGuidance')
    for language_code, guidance in GUIDANCE.items():
        Guidance.objects.create(language_code=language_code, guidance=guidance)


def unseed(apps, schema_editor):
    apps.get_model('search', 'PromptLanguageGuidance').objects.all().delete()


class Migration(migrations.Migration):
    dependencies = [('search', '0013_seed_prompt_config')]
    operations = [
        migrations.CreateModel(
            name='PromptLanguageGuidance',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('language_code', models.CharField(max_length=10, unique=True)),
                ('guidance', models.TextField()),
                ('active', models.BooleanField(default=True)),
                ('updated_at', models.DateTimeField(auto_now=True)),
            ],
            options={'db_table': 'prompt_language_guidance', 'ordering': ['language_code']},
        ),
        migrations.RunPython(seed, unseed),
    ]
