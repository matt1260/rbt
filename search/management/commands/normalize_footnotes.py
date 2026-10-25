"""
Clean the NT footnotes into one consistent HTML form (see translate/footnote_cleanup.py and
translate/footnote_maintenance.py; the same clean-up runs from /translate/footnotes/cleanup/).

    manage.py normalize_footnotes                       # dry run: summary only
    manage.py normalize_footnotes --report out.html     # dry run + before/after review page
    manage.py normalize_footnotes --book Mat --book Joh # limit to books (abbreviations)
    manage.py normalize_footnotes --apply --backup b.json [--print-backup]
    manage.py normalize_footnotes --restore b.json

--apply writes the backup first, then rewrites the footnotes, drops identical duplicate
rows, cleans and re-stamps their translations, and clears the reader cache, in one
transaction. Nothing is logged to translation_updates (it feeds the public updates page).
"""
import base64
import gzip
import html as html_lib
import json

from django.core.management.base import BaseCommand, CommandError

from translate.footnote_maintenance import PlanOutdated, apply_plan, make_backup, plan_cleanup, restore_backup


def _ids(items):
    return [i['fid'] if isinstance(i, dict) else str(i) for i in items]


class Command(BaseCommand):
    help = 'Normalise NT footnote HTML (dry run unless --apply).'

    def add_arguments(self, parser):
        parser.add_argument('--book', action='append', default=[], help='Book abbreviation (Mat, Joh, 1Co…); repeatable.')
        parser.add_argument('--report', help='Write an HTML review page (before/after) to this path.')
        parser.add_argument('--apply', action='store_true', help='Write the changes.')
        parser.add_argument('--backup', help='With --apply: write the original rows here first (required).')
        parser.add_argument('--print-backup', action='store_true', help='Also print the backup as gzip+base64 (for remote runs).')
        parser.add_argument('--skip-translations', action='store_true', help='Leave verse_translations alone.')
        parser.add_argument('--restore', help='Put back the rows saved in a backup file.')

    def handle(self, *args, **opts):
        if opts['restore']:
            with open(opts['restore'], encoding='utf-8') as fh:
                summary = restore_backup(json.load(fh))
            self.stdout.write(self.style.SUCCESS(
                f'Restored {summary["footnote_rows"]} footnote rows ({summary["ids"]} ids) and {summary["translations"]} '
                f'translations from {opts["restore"]}; {summary["cache_keys"]} cache keys cleared.'))
            return
        if opts['apply'] and not opts['backup']:
            raise CommandError('--apply needs --backup PATH (the original rows are saved there first).')

        plan = plan_cleanup(books=opts['book'] or None, translations=not opts['skip_translations'])
        if opts['book'] and not plan['tables']:
            raise CommandError(f'No footnote tables for {", ".join(opts["book"])}.')
        self._print_summary(plan)
        if opts['report']:
            self._write_report(plan, opts['report'])
            self.stdout.write(f'Review page: {opts["report"]}')
        if not opts['apply']:
            self.stdout.write(self.style.WARNING('Dry run: nothing written. Add --apply --backup PATH to write.'))
            return

        backup = make_backup(plan)
        with open(opts['backup'], 'w', encoding='utf-8') as fh:
            json.dump(backup, fh, ensure_ascii=False)
        self.stdout.write(f'Backup written: {opts["backup"]} ({len(backup["footnotes"])} footnote rows, {len(backup["translations"])} translations)')
        if opts['print_backup']:
            blob = base64.b64encode(gzip.compress(json.dumps(backup, ensure_ascii=False).encode('utf-8'))).decode('ascii')
            self.stdout.write('BACKUP-BEGIN\n' + blob + '\nBACKUP-END')
        try:
            summary = apply_plan(plan)
        except PlanOutdated as exc:
            raise CommandError(str(exc))
        self.stdout.write(self.style.SUCCESS(
            f'Applied: {summary["updated"]} footnotes rewritten, {summary["deleted"]} duplicate rows dropped, '
            f'{summary["translations"]} translations cleaned; {summary["cache_keys"]} cache keys cleared.'))

    def _print_summary(self, plan):
        w = self.stdout.write
        w(f'Tables: {len(plan["tables"])}   footnote rows: {plan["rows"]}')
        w(f'  to rewrite:             {len(plan["updates"])}')
        w(f'  already clean:          {plan["unchanged"]}')
        w(f'  duplicate rows to drop: {len(plan["deletes"])}')
        w(f'  translations to clean:  {len(plan["translations"])}')
        w(f'  reader cache entries:   {len(plan["cache"])} verses')
        if plan['kinds']:
            w('  changes by kind:')
            for k, n in plan['kinds'].most_common():
                w(f'    {n:5}  {k}')
        for label, items in (('Duplicate ids whose copies differ (not touched)', plan['conflicts']),
                             ('Wording would change (not touched)', plan['wording']),
                             ('Rendered maths left as is (check by eye)', plan['review']),
                             ('Placeholder ids', plan['placeholders']),
                             ('Footnotes no verse links to', plan['orphans'])):
            if items:
                ids = _ids(items)
                w(f'  {label}: {len(ids)}  {", ".join(ids[:12])}{" …" if len(ids) > 12 else ""}')

    # ------------------------------------------------------------------ report
    def _write_report(self, plan, path):
        esc = html_lib.escape
        rows = []
        for u in plan['updates']:
            rows.append(f'''
<section class="fn" id="{esc(u["fid"])}">
  <h2>{esc(u["fid"])} <small>{esc(u["table"])}</small></h2>
  <ul class="changes">{"".join(f"<li>{esc(c)}</li>" for c in u["changes"])}</ul>
  <div class="cols">
    <div class="col"><h3>Before</h3><div class="note rbt-notes">{u["old"]}</div></div>
    <div class="col"><h3>After</h3><div class="note rbt-notes">{u["new"]}</div></div>
  </div>
  <details><summary>HTML</summary><div class="cols"><pre>{esc(u["old"])}</pre><pre>{esc(u["new"])}</pre></div></details>
</section>''')
        lists = ''.join(
            f'<h3>{esc(label)} ({len(items)})</h3><p class="ids">{esc(", ".join(_ids(items))) or "—"}</p>'
            for label, items in (('Duplicate ids whose copies differ (not touched)', plan['conflicts']),
                                 ('Wording would change (not touched)', plan['wording']),
                                 ('Rendered maths left as is', plan['review']),
                                 ('Placeholder ids', plan['placeholders']),
                                 ('Footnotes no verse links to', plan['orphans'])))
        kinds = ''.join(f'<tr><td>{n}</td><td>{esc(k)}</td></tr>' for k, n in plan['kinds'].most_common())
        page = f'''<!doctype html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1"><title>Footnote cleanup review</title>
<style>
  :root {{ --ink:#1a1611; --stone:#8a7e70; --rule:rgba(183,133,80,.25); --gold:#b78550; --bg:#faf7f2; }}
  body {{ margin:0; padding:24px 16px 80px; background:var(--bg); color:var(--ink); font:15px/1.5 Georgia,serif; }}
  main {{ max-width:1400px; margin:0 auto; }}
  h1 {{ font-size:24px; }} h2 {{ font-size:16px; margin:0 0 6px; font-family:system-ui,sans-serif; }}
  h2 small {{ color:var(--stone); font-weight:400; }} h3 {{ font:600 11px/1.4 system-ui,sans-serif; letter-spacing:.08em; text-transform:uppercase; color:var(--stone); margin:0 0 6px; }}
  .summary {{ background:#fff; border:1px solid var(--rule); border-radius:10px; padding:14px 18px; margin-bottom:20px; }}
  .summary table td {{ padding:2px 10px 2px 0; }} .ids {{ font:12px/1.5 ui-monospace,monospace; color:#5a5044; }}
  .fn {{ background:#fff; border:1px solid var(--rule); border-radius:10px; padding:14px 16px; margin:0 0 14px; }}
  .changes {{ margin:0 0 10px 18px; padding:0; font:12px/1.5 system-ui,sans-serif; color:#5a5044; }}
  .cols {{ display:grid; grid-template-columns:minmax(0,1fr) minmax(0,1fr); gap:14px; }}
  .col {{ min-width:0; }} .note {{ position:relative; overflow:hidden; contain:paint; border:1px dashed var(--rule); border-radius:8px; padding:10px 12px; }}
  pre {{ white-space:pre-wrap; word-break:break-word; font:11px/1.45 ui-monospace,monospace; background:var(--bg); padding:8px; border-radius:6px; max-height:360px; overflow:auto; }}
  details summary {{ cursor:pointer; font:12px system-ui,sans-serif; color:var(--gold); margin-top:8px; }}
  /* The site's footnote styles (base.html), so "After" shows how pages render it. */
  .rbt-notes {{ font-size:15px; line-height:1.65; color:#333; }}
  .rbt-notes :is(p,li,td,th,blockquote) {{ font-size:inherit; color:inherit; line-height:inherit; }}
  .rbt-notes li {{ margin-bottom:.3em; }}
  .rbt-notes :is(.hebrew,.hebrew_footnote) {{ font-family:'SBL Hebrew','Ezra SIL','Times New Roman',serif; font-size:1.4em; line-height:1; }}
  .rbt-notes .greek {{ font-family:'SBL Greek','Gentium Plus','Palatino Linotype',serif; font-size:1.05em; }}
  .rbt-notes span.footnote_header {{ font-family:'Cormorant Garamond',serif; font-variant:small-caps; font-weight:bold; font-size:18pt; line-height:2.5em; }}
  @media (max-width:800px) {{ .cols {{ grid-template-columns:minmax(0,1fr); }} }}
</style></head><body><main>
<h1>Footnote cleanup review</h1>
<div class="summary">
  <p>{len(plan["updates"])} footnotes to rewrite · {plan["unchanged"]} already clean · {len(plan["deletes"])} duplicate rows to drop ·
     {len(plan["translations"])} translations to clean · {plan["rows"]} rows in {len(plan["tables"])} tables</p>
  <table>{kinds}</table>
  {lists}
</div>
{"".join(rows)}
</main></body></html>'''
        with open(path, 'w', encoding='utf-8') as fh:
            fh.write(page)
