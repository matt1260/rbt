"""
Isaiah, Jeremiah and Jude got new RBT titles, and the Gospel of Judas a new heading
("Gospel of Praised One"). Their translations were saved before titles carried a
source_hash, so nothing can tell they're out of date: mark them stale. Pages then show the
English title until the translation dashboard's "Refresh titles" re-translates them
(search/title_translations.py).
"""
from django.db import migrations

STALE = 'stale'
RENAMED_BOOKS = ['Isaiah', 'Jeremiah', 'Jude', 'Gospel of Judas']


def mark_stale(apps, schema_editor):
    VerseTranslation = apps.get_model('search', 'VerseTranslation')
    # Only rows never fingerprinted: run after a refresh, this must not undo it.
    titles = VerseTranslation.objects.filter(chapter=0, footnote_id__isnull=True, source_hash__isnull=True)
    titles.filter(verse=0, book__in=RENAMED_BOOKS).update(source_hash=STALE)
    titles.filter(verse=3, book='Gospel of Judas').update(source_hash=STALE)


class Migration(migrations.Migration):

    dependencies = [
        ('search', '0016_chapter_paraphrases'),
    ]

    operations = [
        migrations.RunPython(mark_stale, migrations.RunPython.noop),
    ]
