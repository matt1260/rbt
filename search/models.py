from django.db import models

# Django genesis database 
class Genesis(models.Model):
    
    id = models.AutoField(primary_key=True)
    chapter = models.IntegerField()
    verse = models.IntegerField()
    html = models.TextField()
    text = models.TextField()
    hebrew = models.TextField()
    rbt_reader = models.TextField()
    
    class Meta:
        db_table = 'genesis'

    def __str__(self):
        return f"Chapter {self.chapter}, Verse {self.verse}"
    
class EngLXX(models.Model):
    
    verseID = models.CharField(max_length=50, primary_key=True)
    canon_order = models.TextField()
    book = models.TextField()
    chapter = models.TextField()
    startVerse = models.TextField()
    endVerse = models.TextField()
    verseText = models.TextField()

    class Meta:
        db_table = 'englxxup'

    def __str__(self):
        return f"Book {self.book}, Chapter {self.chapter}, Verse {self.startVerse}"

class LITV(models.Model):
    
    id = models.AutoField(primary_key=True)
    book = models.TextField()
    chapter = models.TextField()
    verse = models.TextField()
    text = models.TextField()

    class Meta:
        db_table = 'litv'

    def __str__(self):
        return f"Book {self.book}, Chapter {self.chapter}, Verse {self.verse}"
    
# Django genesis footnotes database 
class GenesisFootnotes(models.Model):
    
    id = models.AutoField(primary_key=True)
    footnote_id = models.TextField()
    footnote_html = models.TextField()
    original_footnotes_html = models.TextField()
    
    class Meta:
        db_table = 'genesis_footnotes'

    def __str__(self):
        return f"Footnote ID {self.footnote_id}, Footnote {self.footnote_html}"
    

class TranslationUpdates(models.Model):
    date = models.DateTimeField(primary_key=True)
    version = models.TextField()
    reference = models.TextField()
    update_text = models.TextField()

    class Meta:
        db_table = 'translation_updates'

    def __str__(self):
        return f"Date {self.date}, Reference {self.reference}, Update {self.update_text}"


class VerseTranslation(models.Model):
    """Multi-lingual translations for verses and footnotes"""
    
    STATUS_CHOICES = [
        ('ai_generated', 'AI Generated'),
        ('human_reviewed', 'Human Reviewed'),
        ('published', 'Published'),
    ]
    
    book = models.CharField(max_length=50)
    chapter = models.IntegerField()
    verse = models.IntegerField()
    language_code = models.CharField(max_length=10, db_index=True)
    verse_text = models.TextField(blank=True, null=True)
    footnote_id = models.CharField(max_length=50, blank=True, null=True)
    footnote_text = models.TextField(blank=True, null=True)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='ai_generated')
    generated_by = models.CharField(max_length=50, default='gemini-3-flash-preview')
    created_at = models.DateTimeField(auto_now_add=True)
    
    class Meta:
        db_table = 'verse_translations'
        indexes = [
            models.Index(fields=['book', 'chapter', 'verse', 'language_code'], name='idx_verse_lang'),
        ]
    
    def __str__(self):
        return f"{self.book} {self.chapter}:{self.verse} ({self.language_code})"


class TranslationJob(models.Model):
    """Background translation job tracking"""
    
    STATUS_CHOICES = [
        ('pending', 'Pending'),
        ('processing', 'Processing'),
        ('completed', 'Completed'),
        ('failed', 'Failed'),
    ]
    
    job_id = models.CharField(max_length=36, primary_key=True)  # UUID
    book = models.CharField(max_length=50)
    chapter = models.IntegerField()
    language_code = models.CharField(max_length=10)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='pending')
    
    # Progress tracking
    total_verses = models.IntegerField(default=0)
    translated_verses = models.IntegerField(default=0)
    total_footnotes = models.IntegerField(default=0)
    translated_footnotes = models.IntegerField(default=0)
    
    # Metadata
    error_message = models.TextField(blank=True, null=True)
    created_at = models.DateTimeField(auto_now_add=True)
    started_at = models.DateTimeField(blank=True, null=True)
    completed_at = models.DateTimeField(blank=True, null=True)
    
    class Meta:
        db_table = 'translation_jobs'
        indexes = [
            models.Index(fields=['status', 'created_at'], name='idx_job_status'),
        ]
    
    def __str__(self):
        return f"Job {self.job_id}: {self.book} {self.chapter} ({self.language_code}) - {self.status}"
    
    @property
    def progress_percent(self):
        total = self.total_verses + self.total_footnotes
        done = self.translated_verses + self.translated_footnotes
        if total == 0:
            return 0
        return int((done / total) * 100)


class InterlinearConfig(models.Model):
    """Singleton-like model to store interlinear English replacements as JSON."""

    id = models.AutoField(primary_key=True)
    mapping = models.JSONField(default=dict)
    updated_at = models.DateTimeField(auto_now=True)
    updated_by = models.CharField(max_length=100, blank=True, null=True)

    class Meta:
        db_table = 'interlinear_config'

    def __str__(self):
        return f"InterlinearConfig (updated: {self.updated_at})"