from django.core.management.base import BaseCommand
from django.db import connection
import pickle
import time
from datetime import datetime

class Command(BaseCommand):
    help = 'List active bans, strikes, and rate limits from the DB cache'

    def handle(self, *args, **options):
        cur = connection.cursor()
        cur.execute("SELECT cache_key, value, expires FROM django_cache_table WHERE cache_key LIKE 'banned:%' OR cache_key LIKE 'strikes:%' OR cache_key LIKE 'ratelimit:%'")
        rows = cur.fetchall()
        if not rows:
            self.stdout.write('(no active entries)')
            return

        entries = []
        for k, v, expires in rows:
            key = k.decode() if isinstance(k, bytes) else str(k)
            raw_val = None
            try:
                raw_val = pickle.loads(v) if isinstance(v, (bytes, bytearray)) else v
            except Exception:
                raw_val = v

            entry = {'key': key, 'value': raw_val, 'expires': expires}
            # parse key
            parts = key.split(':')
            if parts[0] == 'banned':
                entry['type'] = 'banned'
                entry['ip'] = parts[1]
            elif parts[0] == 'strikes':
                entry['type'] = 'strikes'
                # strikes:endpoint:ip
                entry['endpoint'] = parts[1] if len(parts) >= 3 else None
                entry['ip'] = parts[2] if len(parts) >= 3 else None
            elif parts[0] == 'ratelimit':
                entry['type'] = 'ratelimit'
                entry['endpoint'] = parts[1] if len(parts) >= 3 else None
                entry['ip'] = parts[2] if len(parts) >= 3 else None
            else:
                entry['type'] = 'unknown'
            entries.append(entry)

        # Sort by expires (soonest to latest)
        entries.sort(key=lambda x: (x.get('expires') or 0))

        for e in entries:
            expires = e.get('expires')
            exp_str = datetime.utcfromtimestamp(expires).isoformat() if expires else 'N/A'
            self.stdout.write(f"{e.get('type'):8} {e.get('ip'):15} endpoint={e.get('endpoint', ''):8} expires={exp_str} value={e.get('value')}")
