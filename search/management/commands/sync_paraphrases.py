"""
Merge AI chapter paraphrases and their prompt presets between this database and another
(local <-> production) without deleting anything. Wrapped by scripts/push_paraphrases.sh
and scripts/pull_paraphrases.sh.

    python manage.py sync_paraphrases pull --remote "$REMOTE_DATABASE_URL"
    python manage.py sync_paraphrases push --remote "$REMOTE_DATABASE_URL" --dry-run

Unlike push_new_testament.sh (which truncates the target), both sides keep their rows:
paraphrases match by uid and presets by name, and the copy with the newer updated_at
wins. Generations still running are skipped. Afterwards each chapter has exactly one
published paraphrase — whichever was published most recently on either side — and there
is one default preset.
"""
from datetime import datetime, timezone as dt_timezone

import psycopg2
from django.core.management.base import BaseCommand, CommandError
from django.db import connection, transaction
from psycopg2.extras import Json

from search.models import ChapterParaphrase, ParaphrasePrompt

EPOCH = datetime(1970, 1, 1, tzinfo=dt_timezone.utc)


def _columns(model):
    return [f.column for f in model._meta.concrete_fields if not f.primary_key]


def _utc(value):
    """Timestamps as aware UTC. With USE_TZ off, Django's connection returns naive UTC
    while a raw psycopg2 connection returns aware values, and the two can't be compared."""
    if isinstance(value, datetime):
        return value.replace(tzinfo=dt_timezone.utc) if value.tzinfo is None else value.astimezone(dt_timezone.utc)
    return value


def _fetch(cursor, model, where=''):
    columns = _columns(model)
    cursor.execute(f'SELECT {", ".join(columns)} FROM {model._meta.db_table} {where}')
    rows = []
    for values in cursor.fetchall():
        row = {column: _utc(value) for column, value in zip(columns, values)}
        if 'uid' in row:
            row['uid'] = str(row['uid'])
        if 'batch_id' in row:
            row['batch_id'] = str(row['batch_id'])
        rows.append(row)
    return rows


def plan_paraphrases(source_rows, target_rows):
    """Rows to write to the target, and the uids that end up published there."""
    target = {row['uid']: row for row in target_rows}
    to_write = [
        row for row in source_rows
        if row['uid'] not in target or row['updated_at'] > target[row['uid']]['updated_at']
    ]
    merged = {**target, **{row['uid']: row for row in to_write}}
    winners = {}
    for row in merged.values():
        if not row['is_published']:
            continue
        key = (row['book'], row['chapter'], row['language_code'])
        if key not in winners or (row['published_at'] or EPOCH) > (winners[key]['published_at'] or EPOCH):
            winners[key] = row
    return to_write, {row['uid'] for row in winners.values()}


def plan_presets(source_rows, target_rows):
    """Presets to write to the target, and the name of the single default preset."""
    target = {row['name']: row for row in target_rows}
    to_write = [
        row for row in source_rows
        if row['name'] not in target or row['updated_at'] > target[row['name']]['updated_at']
    ]
    merged = {**target, **{row['name']: row for row in to_write}}
    defaults = [row for row in merged.values() if row['is_default']]
    default = max(defaults, key=lambda row: row['updated_at'])['name'] if defaults else None
    return to_write, default


def _apply(cursor, rows_to_write, published, presets_to_write, default_preset):
    table = ChapterParaphrase._meta.db_table
    # Unpublish first so the one-published-per-chapter index never sees two at once.
    cursor.execute(f'UPDATE {table} SET is_published = false WHERE is_published AND NOT (uid::text = ANY(%s))', [list(published)])
    _upsert(cursor, ChapterParaphrase, rows_to_write, 'uid')
    cursor.execute(f'UPDATE {table} SET is_published = true WHERE uid::text = ANY(%s) AND NOT is_published', [list(published)])
    if default_preset:
        cursor.execute(f'UPDATE {ParaphrasePrompt._meta.db_table} SET is_default = (name = %s)', [default_preset])
        for row in presets_to_write:
            row['is_default'] = row['name'] == default_preset
    _upsert(cursor, ParaphrasePrompt, presets_to_write, 'name')


def _upsert(cursor, model, rows, key):
    if not rows:
        return
    columns = _columns(model)
    updates = ', '.join(f'{c} = EXCLUDED.{c}' for c in columns if c != key)
    sql = (
        f'INSERT INTO {model._meta.db_table} ({", ".join(columns)}) VALUES ({", ".join(["%s"] * len(columns))}) '
        f'ON CONFLICT ({key}) DO UPDATE SET {updates}'
    )
    for row in rows:
        cursor.execute(sql, [Json(row[c]) if isinstance(row[c], (list, dict)) else row[c] for c in columns])


class Command(BaseCommand):
    help = 'Merge chapter paraphrases and paraphrase prompt presets with another database (no deletes).'

    def add_arguments(self, parser):
        parser.add_argument('direction', choices=['push', 'pull'], help='push: this DB -> remote. pull: remote -> this DB.')
        parser.add_argument('--remote', required=True, help='Remote Postgres URL, e.g. production.')
        parser.add_argument('--dry-run', action='store_true', help='Report what would change without writing.')

    def handle(self, *args, direction, remote, dry_run, **options):
        try:
            remote_conn = psycopg2.connect(remote, connect_timeout=30)
        except psycopg2.Error as exc:
            raise CommandError(f'Could not connect to the remote database: {exc}')

        try:
            with remote_conn.cursor() as remote_cursor, connection.cursor() as local_cursor:
                try:
                    remote_rows = _fetch(remote_cursor, ChapterParaphrase, "WHERE status NOT IN ('pending', 'running')")
                    remote_presets = _fetch(remote_cursor, ParaphrasePrompt)
                except psycopg2.errors.UndefinedTable:
                    raise CommandError('The remote database has no paraphrase tables yet. Deploy first so its migrations run.')
                local_rows = _fetch(local_cursor, ChapterParaphrase, "WHERE status NOT IN ('pending', 'running')")
                local_presets = _fetch(local_cursor, ParaphrasePrompt)

                if direction == 'push':
                    source_rows, target_rows, source_presets, target_presets = local_rows, remote_rows, local_presets, remote_presets
                    target_cursor = remote_cursor
                else:
                    source_rows, target_rows, source_presets, target_presets = remote_rows, local_rows, remote_presets, local_presets
                    target_cursor = local_cursor

                rows_to_write, published = plan_paraphrases(source_rows, target_rows)
                presets_to_write, default_preset = plan_presets(source_presets, target_presets)
                for row in rows_to_write:
                    row['is_published'] = row['uid'] in published
                target_published = {r['uid'] for r in target_rows if r['is_published']}

                self.stdout.write(
                    f'{direction}: {len(rows_to_write)} paraphrase(s) and {len(presets_to_write)} preset(s) to write; '
                    f'published after sync: {len(published)} chapter(s) '
                    f'({len(published - target_published)} newly published, {len(target_published - published)} unpublished).'
                )
                if dry_run:
                    self.stdout.write('Dry run: nothing written.')
                    return

                if direction == 'push':
                    with remote_conn:  # one transaction on the remote; rolled back on error
                        _apply(target_cursor, rows_to_write, published, presets_to_write, default_preset)
                else:
                    with transaction.atomic():
                        _apply(target_cursor, rows_to_write, published, presets_to_write, default_preset)
                self.stdout.write(self.style.SUCCESS('Done.'))
        finally:
            remote_conn.close()
