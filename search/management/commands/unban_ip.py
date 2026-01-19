from django.core.management.base import BaseCommand
from django.db import connection

class Command(BaseCommand):
    help = 'Unban an IP by removing any banned/strikes/ratelimit cache entries for that IP'

    def add_arguments(self, parser):
        parser.add_argument('ip', help='IP address to unban')

    def handle(self, *args, **options):
        ip = options['ip']
        cur = connection.cursor()
        cur.execute("SELECT cache_key FROM django_cache_table WHERE cache_key LIKE %s OR cache_key LIKE %s OR cache_key LIKE %s", (f'banned:{ip}', f'strikes:%:{ip}', f'ratelimit:%:{ip}'))
        rows = cur.fetchall()
        if not rows:
            self.stdout.write(f'No cache entries found for {ip}')
            return
        keys = [r[0].decode() if isinstance(r[0], bytes) else r[0] for r in rows]
        # Delete rows
        cur.execute("DELETE FROM django_cache_table WHERE cache_key = ANY(%s)", (keys,))
        self.stdout.write(f'Removed {len(keys)} cache entries for {ip}')
