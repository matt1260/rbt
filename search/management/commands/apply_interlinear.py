from django.core.management.base import BaseCommand, CommandError
from django.db import connection, transaction
from django.conf import settings
from search.models import InterlinearConfig, InterlinearApplyLog
from search import utils
import json
import os


class Command(BaseCommand):
    help = (
        'Apply interlinear mapping to rbt_greek.strongs_greek. By default performs a dry-run. '
        'Use --commit to write changes. Use --limit to show sample changes.'
    )

    def add_arguments(self, parser):
        parser.add_argument('--dry-run', action='store_true', default=False, help='Perform a dry-run (default behavior unless --commit provided).')
        parser.add_argument('--commit', action='store_true', default=False, help='Apply changes to the DB.')
        parser.add_argument('--limit', type=int, default=20, help='Maximum number of sample replacements to show.')
        parser.add_argument('--file', type=str, default='', help='Optional path to an interlinear JSON file to use instead of DB.')
        parser.add_argument('--yes', action='store_true', default=False, help='Skip confirmation prompt when using --commit.')

    def handle(self, *args, **options):
        dry_run = options.get('dry_run') and not options.get('commit')
        commit = options.get('commit')
        limit = options.get('limit')
        file_path = options.get('file')

        if commit and dry_run:
            # shouldn't happen because we derived dry_run accordingly, but guard
            dry_run = False

        self.stdout.write(f"Reading mapping (source={'file' if file_path else 'db/file fallback'})...")

        # Load mapping (DB preferred, fallback to file)
        try:
            mapping = utils.load_mapping_from_db_or_file(file_path if file_path else None)
        except Exception as exc:
            raise CommandError(f"Failed to load interlinear mapping: {exc}")

        if not isinstance(mapping, dict):
            raise CommandError('Interlinear mapping must be a JSON object (dict).')

        # Prepare replacement function
        def replace_func(strongs, lemma, english):
            for cond, replacement in mapping.items():
                # exact match on strongs or lemma
                try:
                    cond_s = str(cond)
                except Exception:
                    cond_s = cond
                if strongs == cond_s or (lemma is not None and lemma == cond_s):
                    return replacement
            return english

        # Use shared utils to compute/apply replacements
        result = utils.apply_interlinear(mapping, dry_run=not commit, limit=limit, clear_mapping_on_commit=commit, user='CLI') # type: ignore

        total = result.get('total_candidates')
        samples = result.get('samples', [])

        self.stdout.write(f"Found {total} potential replacements.")

        if not commit:
            # dry-run: show samples and exit
            if samples:
                self.stdout.write('\nSample replacements:')
                for s, lem, old, new in samples:
                    self.stdout.write(f" - {s} | {lem} : '{old}' -> '{new}'")
            else:
                self.stdout.write('No replacements to show.')
            self.stdout.write('\nDry-run complete. Use --commit to apply changes.')

            # create audit log entry for dry-run
            InterlinearApplyLog.objects.create(
                user='CLI', committed=False, total_candidates=total, applied_count=0,
                sample='\n'.join([f"{s}|{lem}:'{old}'->'{new}'" for s, lem, old, new in samples])
            )
            return

        # commit path
        yes = options.get('yes')
        if not yes:
            answer = input('About to apply changes to rbt_greek.strongs_greek. Proceed? [y/N]: ').strip().lower()
            if answer not in ('y', 'yes'):
                self.stdout.write('Aborted by user. No changes made.')
                return

        # result already applied by utils.apply_interlinear
        applied = result.get('applied', 0)
        backup_file = result.get('backup_file')

        InterlinearApplyLog.objects.create(
            user='CLI', committed=True, total_candidates=total, applied_count=applied,
            sample='\n'.join([f"{s}|{lem}:'{old}'->'{new}'" for s, lem, old, new in samples]),
            backup_file=backup_file
        )

        self.stdout.write(f"Applied {applied} replacements successfully. Backup: {backup_file}")
        self.stdout.write('Done.')
