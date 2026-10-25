"""
The footnote clean-up page (/translate/footnotes/cleanup/?book=Mat), staff only.

It shows, for one book (or all), what the clean-up would change and the problems a person
should look at, and applies it per footnote or for the whole book. It also renumbers a book's
footnotes 1, 2, 3… in reading order (translate/footnote_renumber.py). Every apply returns a
backup of what it overwrote: the page downloads it and can put it back (restore).
"""
import json
import logging

from django.contrib.auth.decorators import login_required, user_passes_test
from django.db import connection
from django.http import JsonResponse
from django.shortcuts import render
from django.views.decorators.http import require_POST

from translate import footnote_renumber
from translate.chapter_editor_api import staff_json
from translate.footnote_maintenance import (
    PlanOutdated, abbrev_of, apply_plan, footnote_tables, full_book, make_backup, per_book, plan_cleanup,
    restore_backup, translation_count,
)
from translate.translator import book_abbreviations

logger = logging.getLogger(__name__)
MAX_BACKUP_BYTES = 20 * 1024 * 1024


def _books():
    with connection.cursor() as cur:
        abbrevs = [abbrev_of(t) for t in footnote_tables(cur)]
    # In reading order (book_abbreviations lists the canon in order).
    order = {code: i for i, code in enumerate(dict.fromkeys(book_abbreviations.values()))}
    return sorted(({'abbrev': a, 'name': full_book(a)} for a in abbrevs), key=lambda b: order.get(b['abbrev'], 999))


def _resolve_book(value, books):
    """'Mat', 'mat' or 'Matthew' → 'Mat'; 'all' → 'all'; anything else → None."""
    if not value:
        return None
    if value.lower() == 'all':
        return 'all'
    for b in books:
        if value.lower() in (b['abbrev'].lower(), b['name'].lower(), b['name'].replace(' ', '').lower()):
            return b['abbrev']
    code = book_abbreviations.get(value)
    return code if code and any(b['abbrev'] == code for b in books) else None


@login_required
@user_passes_test(lambda u: u.is_staff)
def page(request):
    books = _books()
    book = _resolve_book(request.GET.get('book'), books)
    context = {'books': books, 'book': book, 'plan': None}
    if book:
        # Translations are only counted here; apply() plans them in full.
        plan = plan_cleanup(books=None if book == 'all' else [book], translations=False)
        context.update({
            'plan': plan,
            'translations': translation_count(plan),
            'per_book': per_book(plan) if book == 'all' else None,
            'book_name': 'all books' if book == 'all' else full_book(book),
            'kinds': plan['kinds'].most_common(),
            'issues': [
                ('Footnotes no verse links to', 'They may be left over from deleted markers; check before removing anything.', plan['orphans']),
                ('Placeholder ids', 'Ids like “xx” from the old add-footnote form.', plan['placeholders']),
                ('Repeated ids with different text', 'Several stored copies of one id that differ; not cleaned until one is chosen.', plan['conflicts']),
                ('Wording would change', 'The clean-up would change the text a reader sees, so it is left alone.', plan['wording']),
                ('Rendered maths', 'Formulas pasted as rendered maths are left as they are; check them by eye.', plan['review']),
            ],
            'duplicate_ids': sorted({d['fid'] for d in plan['deletes']}),
        })
        context['has_issues'] = any(items for _, _, items in context['issues'])
        if book == 'all':
            for row in context['per_book']:
                row['renumber'] = len(footnote_renumber.plan_renumber(row['abbrev'], translations=False)['changes'])
        else:
            context['renumber'] = footnote_renumber.plan_renumber(book)
    return render(request, 'footnote_cleanup.html', context)


@require_POST
@staff_json
def apply(request):
    """POST {book, ids?} → {summary, backup}: clean the book (or just these footnote ids)."""
    try:
        payload = json.loads(request.body or b'{}')
    except (ValueError, UnicodeDecodeError):
        return JsonResponse({'error': 'Invalid JSON.'}, status=400)
    books = _books()
    book = _resolve_book(payload.get('book'), books)
    ids = payload.get('ids')
    if not book or book == 'all':
        return JsonResponse({'error': 'Choose one book to clean up.'}, status=400)
    if ids is not None and (not isinstance(ids, list) or not all(isinstance(i, str) for i in ids)):
        return JsonResponse({'error': 'ids must be a list of footnote ids.'}, status=400)
    plan = plan_cleanup(books=[book], only_ids=set(ids) if ids else None)
    if not plan['updates'] and not plan['deletes']:
        return JsonResponse({'summary': {'updated': 0, 'deleted': 0, 'translations': 0, 'cache_keys': 0}, 'backup': None})
    backup = make_backup(plan)
    try:
        summary = apply_plan(plan)
    except PlanOutdated as exc:
        return JsonResponse({'error': str(exc)}, status=409)
    logger.info('[FOOTNOTE CLEANUP] %s cleaned %s: %s', request.user.username, ', '.join(ids) if ids else full_book(book), summary)
    return JsonResponse({'summary': summary, 'backup': backup,
                         'ids': sorted({u['fid'] for u in plan['updates']} | {d['fid'] for d in plan['deletes']})})


@require_POST
@staff_json
def renumber(request):
    """POST {book, token} → {summary, backup}: renumber the book as the page showed it (token)."""
    try:
        payload = json.loads(request.body or b'{}')
    except (ValueError, UnicodeDecodeError):
        return JsonResponse({'error': 'Invalid JSON.'}, status=400)
    book = _resolve_book(payload.get('book'), _books())
    if not book or book == 'all' or not isinstance(payload.get('token'), str):
        return JsonResponse({'error': 'book and token are required.'}, status=400)
    try:
        summary, backup = footnote_renumber.apply_renumber(book, payload['token'])
    except PlanOutdated as exc:
        return JsonResponse({'error': str(exc)}, status=409)
    logger.info('[FOOTNOTE RENUMBER] %s renumbered %s: %s', request.user.username, full_book(book), summary)
    return JsonResponse({'summary': summary, 'backup': backup})


@require_POST
@staff_json
def restore(request):
    """POST a backup (as returned by apply or renumber, or the downloaded file) → {summary}."""
    if len(request.body or b'') > MAX_BACKUP_BYTES:
        return JsonResponse({'error': 'That backup is too large.'}, status=400)
    try:
        backup = json.loads(request.body or b'{}')
        if isinstance(backup, dict) and backup.get('kind') == footnote_renumber.BACKUP_KIND:
            summary = footnote_renumber.restore_renumber(backup)
        else:
            summary = restore_backup(backup)
    except PlanOutdated as exc:
        return JsonResponse({'error': str(exc)}, status=409)
    except (ValueError, UnicodeDecodeError, KeyError, TypeError) as exc:
        return JsonResponse({'error': f'Not a footnote backup: {exc}'}, status=400)
    logger.info('[FOOTNOTE CLEANUP] %s restored a backup: %s', request.user.username, summary)
    return JsonResponse({'summary': summary})
