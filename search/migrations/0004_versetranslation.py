# Generated migration for verse translations

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('search', '0003_alter_englxx_verseid'),
    ]

    operations = [
        migrations.CreateModel(
            name='VerseTranslation',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('book', models.CharField(max_length=50)),
                ('chapter', models.IntegerField()),
                ('verse', models.IntegerField()),
                ('language_code', models.CharField(max_length=10, db_index=True)),
                ('verse_text', models.TextField(blank=True, null=True)),
                ('footnote_id', models.CharField(max_length=50, blank=True, null=True)),
                ('footnote_text', models.TextField(blank=True, null=True)),
                ('status', models.CharField(max_length=20, default='ai_generated', choices=[
                    ('ai_generated', 'AI Generated'),
                    ('human_reviewed', 'Human Reviewed'),
                    ('published', 'Published')
                ])),
                ('generated_by', models.CharField(max_length=50, default='gemini-2.0')),
                ('created_at', models.DateTimeField(auto_now_add=True)),
            ],
            options={
                'db_table': 'verse_translations',
                'indexes': [
                    models.Index(fields=['book', 'chapter', 'verse', 'language_code'], name='idx_verse_lang'),
                ],
            },
        ),
    ]
