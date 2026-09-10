from django.db import migrations, models


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
    ]
