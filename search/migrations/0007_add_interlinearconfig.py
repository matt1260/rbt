# Generated migration to add InterlinearConfig model
from django.db import migrations, models

class Migration(migrations.Migration):

    dependencies = [
        ('search', '0006_add_translation_job_model'),
    ]

    operations = [
        migrations.CreateModel(
            name='InterlinearConfig',
            fields=[
                ('id', models.AutoField(primary_key=True, serialize=False)),
                ('mapping', models.JSONField(default=dict)),
                ('updated_at', models.DateTimeField(auto_now=True)),
                ('updated_by', models.CharField(blank=True, max_length=100, null=True)),
            ],
            options={'db_table': 'interlinear_config'},
        ),
    ]
