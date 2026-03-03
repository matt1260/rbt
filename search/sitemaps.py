from django.contrib.sitemaps import Sitemap
from django.urls import reverse
from urllib.parse import urlencode
from translate.translator import old_testament_books, new_testament_books
import datetime

class BibleChapterSitemap(Sitemap):
    changefreq = "weekly"
    priority = 0.8
    protocol = "https"

    def items(self):
        # We can simulate chapters using a dictionary. 
        # For simplicity in this static map without fully probing the DB for max chapters per book:
        # We will map standard chapter counts for 66 books.
        bible_chapter_counts = {
            'Genesis': 50, 'Exodus': 40, 'Leviticus': 27, 'Numbers': 36, 'Deuteronomy': 34,
            'Joshua': 24, 'Judges': 21, 'Ruth': 4, '1 Samuel': 31, '2 Samuel': 24,
            '1 Kings': 22, '2 Kings': 25, '1 Chronicles': 29, '2 Chronicles': 36,
            'Ezra': 10, 'Nehemiah': 13, 'Esther': 10, 'Job': 42, 'Psalms': 150,
            'Proverbs': 31, 'Ecclesiastes': 12, 'Song of Solomon': 8, 'Isaiah': 66,
            'Jeremiah': 52, 'Lamentations': 5, 'Ezekiel': 48, 'Daniel': 12,
            'Hosea': 14, 'Joel': 3, 'Amos': 9, 'Obadiah': 1, 'Jonah': 4,
            'Micah': 7, 'Nahum': 3, 'Habakkuk': 3, 'Zephaniah': 3, 'Haggai': 2,
            'Zechariah': 14, 'Malachi': 4,
            'Matthew': 28, 'Mark': 16, 'Luke': 24, 'John': 21, 'Acts': 28,
            'Romans': 16, '1 Corinthians': 16, '2 Corinthians': 13, 'Galatians': 6,
            'Ephesians': 6, 'Philippians': 4, 'Colossians': 4, '1 Thessalonians': 5,
            '2 Thessalonians': 3, '1 Timothy': 6, '2 Timothy': 4, 'Titus': 3,
            'Philemon': 1, 'Hebrews': 13, 'James': 5, '1 Peter': 5, '2 Peter': 3,
            '1 John': 5, '2 John': 1, '3 John': 1, 'Jude': 1, 'Revelation': 22
        }
        
        items = []
        for book, count in bible_chapter_counts.items():
            for chapter in range(1, count + 1):
                items.append((book, chapter))
        return items

    def lastmod(self, item):
        return datetime.date.today()

    def location(self, item):
        book, chapter = item
        params = urlencode({'book': book, 'chapter': chapter})
        return f"/?{params}"

class StaticViewSitemap(Sitemap):
    priority = 0.5
    changefreq = "daily"
    protocol = "https"

    def items(self):
        return ['search', 'storehouse', 'updates']

    def location(self, item):
        return reverse(item)
