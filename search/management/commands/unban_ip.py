from django.core.management.base import BaseCommand
from django.core.cache import cache

ENDPOINTS = ['verse', 'chapter', 'api', 'general']

class Command(BaseCommand):
    help = 'Unban an IP by removing any banned/strikes/ratelimit cache entries for that IP'

    def add_arguments(self, parser):
        parser.add_argument('ip', help='IP address to unban')

    def handle(self, *args, **options):
        ip = options['ip']
        # Django DatabaseCache stores keys as MD5 hashes, so we must use the
        # cache API (not raw SQL LIKE) to ensure proper key transformation.
        keys = [f'banned:{ip}']
        for ep in ENDPOINTS:
            keys.append(f'ratelimit:{ep}:{ip}')
            keys.append(f'strikes:{ep}:{ip}')
        cache.delete_many(keys)
        self.stdout.write(self.style.SUCCESS(f'Cleared {len(keys)} cache keys for {ip}'))
