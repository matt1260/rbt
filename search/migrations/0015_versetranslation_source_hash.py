from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('search', '0014_alter_versetranslation_generated_by'),
    ]

    operations = [
        migrations.AddField(
            model_name='versetranslation',
            name='source_hash',
            field=models.CharField(blank=True, db_index=True, max_length=64, null=True),
        ),
    ]