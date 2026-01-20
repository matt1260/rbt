import json
import os
import csv
import time
from django.conf import settings
from django.db import connection, transaction


def load_mapping_from_db_or_file(file_path: str | None = None):
    # Try explicit file first
    if file_path:
        if not os.path.exists(file_path):
            raise FileNotFoundError(file_path)
        with open(file_path, 'r', encoding='utf-8') as fh:
            raw = fh.read()
            raw = raw.replace("'", '"')
            if raw and raw[0] == '"' and raw[-1] == '"':
                raw = raw[1:-1]
            raw = raw.replace('\\', '')
            return json.loads(raw)

    # Fallback to DB config
    try:
        from search.models import InterlinearConfig
        cfg = InterlinearConfig.objects.order_by('-updated_at').first()
        if cfg and cfg.mapping:
            # mapping may be JSON string or dict
            mapping = cfg.mapping
            if isinstance(mapping, str):
                mapping = json.loads(mapping)
            return mapping
    except Exception:
        pass

    # Fallback to project file
    fallback = os.path.join(settings.BASE_DIR, 'interlinear_english.json')
    if os.path.exists(fallback):
        with open(fallback, 'r', encoding='utf-8') as fh:
            raw = fh.read()
            raw = raw.replace("'", '"')
            if raw and raw[0] == '"' and raw[-1] == '"':
                raw = raw[1:-1]
            raw = raw.replace('\\', '')
            return json.loads(raw)

    raise RuntimeError('No interlinear mapping found (DB/FILE).')


def apply_interlinear(mapping: dict, dry_run: bool = True, limit: int = 20, backup_dir: str | None = None, clear_mapping_on_commit: bool = False, user: str | None = None):
    """Apply mapping to rbt_greek.strongs_greek.

    Returns a dict:
      { 'total_candidates': int,
        'samples': [ (strongs, lemma, old, new), ... ],
        'applied': int (0 if dry_run),
        'backup_file': path or None,
        'cleared': bool }
    """
    if not isinstance(mapping, dict):
        raise ValueError('mapping must be a dict')

    def replace_func(strongs, lemma, english):
        for cond, replacement in mapping.items():
            try:
                cond_s = str(cond)
            except Exception:
                cond_s = cond
            if strongs == cond_s or (lemma is not None and lemma == cond_s):
                return replacement
        return english

    cur = connection.cursor()
    cur.execute("SELECT strongs, lemma, english FROM rbt_greek.strongs_greek")
    rows = cur.fetchall()

    candidates = []
    apply_rows = []
    total = 0
    for strongs, lemma, english in rows:
        new_english = replace_func(strongs, lemma, english)
        if new_english != english:
            total += 1
            if len(candidates) < limit:
                candidates.append((strongs, lemma, english, new_english))
            apply_rows.append((strongs, lemma, english, new_english))

    result = {'total_candidates': total, 'samples': candidates, 'applied': 0, 'backup_file': None, 'cleared': False}

    if dry_run:
        return result

    # Prepare backup
    if backup_dir is None:
        backup_dir = os.path.join(settings.BASE_DIR, 'reports')
    os.makedirs(backup_dir, exist_ok=True)
    ts = int(time.time())
    backup_file = os.path.join(backup_dir, f'interlinear_backup_{ts}.csv')

    with open(backup_file, 'w', newline='', encoding='utf-8') as csvfile:
        writer = csv.writer(csvfile)
        writer.writerow(['strongs', 'lemma', 'old_english', 'new_english'])
        for row in apply_rows:
            writer.writerow(row)

    # Apply changes in a transaction
    applied = 0
    with transaction.atomic():
        for strongs, lemma, old_english, new_english in apply_rows:
            cur.execute(
                "UPDATE rbt_greek.strongs_greek SET english = %s WHERE strongs = %s AND lemma = %s",
                (new_english, strongs, lemma)
            )
            applied += 1

    result['applied'] = applied
    result['backup_file'] = backup_file

    # Optionally clear the preferred mapping in InterlinearConfig
    if clear_mapping_on_commit:
        try:
            from search.models import InterlinearConfig
            cfg = InterlinearConfig.objects.order_by('-updated_at').first()
            if cfg:
                cfg.mapping = {}
                if user:
                    cfg.updated_by = user
                cfg.save()
                result['cleared'] = True
        except Exception:
            # Don't fail the operation just because clearing failed; log is outside scope
            result['cleared'] = False

    return result
