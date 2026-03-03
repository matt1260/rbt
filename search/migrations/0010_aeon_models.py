from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ('search', '0009_visitorlocation'),
    ]

    operations = [
        migrations.CreateModel(
            name='AeonCorpusSource',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('source_type', models.CharField(db_index=True, default='conversation', max_length=32)),
                ('source_identifier', models.CharField(db_index=True, max_length=128)),
                ('title', models.CharField(db_index=True, max_length=255)),
                ('status', models.CharField(choices=[('pending', 'Pending'), ('processing', 'Processing'), ('ready', 'Ready'), ('failed', 'Failed')], db_index=True, default='pending', max_length=20)),
                ('metadata', models.JSONField(blank=True, default=dict)),
                ('error_message', models.TextField(blank=True, null=True)),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('updated_at', models.DateTimeField(auto_now=True)),
                ('last_ingested_at', models.DateTimeField(blank=True, null=True)),
            ],
            options={
                'db_table': 'aeon_corpus_sources',
                'unique_together': {('source_type', 'source_identifier')},
            },
        ),
        migrations.CreateModel(
            name='AeonChunk',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('chunk_index', models.IntegerField()),
                ('role_mix', models.CharField(blank=True, max_length=50, null=True)),
                ('start_turn', models.IntegerField(default=0)),
                ('end_turn', models.IntegerField(default=0)),
                ('text', models.TextField()),
                ('text_hash', models.CharField(db_index=True, max_length=64)),
                ('embedding', models.JSONField(blank=True, null=True)),
                ('metadata', models.JSONField(blank=True, default=dict)),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('updated_at', models.DateTimeField(auto_now=True)),
                ('source', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='chunks', to='search.aeoncorpussource')),
            ],
            options={
                'db_table': 'aeon_chunks',
                'unique_together': {('source', 'chunk_index')},
            },
        ),
        migrations.AddIndex(
            model_name='aeoncorpussource',
            index=models.Index(fields=['source_type', 'title'], name='idx_aeon_source_type_title'),
        ),
        migrations.AddIndex(
            model_name='aeoncorpussource',
            index=models.Index(fields=['status', 'updated_at'], name='idx_aeon_source_status'),
        ),
        migrations.AddIndex(
            model_name='aeonchunk',
            index=models.Index(fields=['source', 'chunk_index'], name='idx_aeon_chunk_source_idx'),
        ),
        migrations.AddIndex(
            model_name='aeonchunk',
            index=models.Index(fields=['text_hash'], name='idx_aeon_chunk_text_hash'),
        ),
    ]
