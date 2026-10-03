"""
JSON endpoints for the Paraphrase Studio (chapter-editor/src/ui/ParaphraseStudio.tsx).

Staff only. See search/paraphrase.py for how a generation runs.
"""
import json
import logging
import uuid
from datetime import timezone as dt_timezone

from django.db import transaction
from django.http import JsonResponse
from django.views.decorators.http import require_GET, require_POST

from search import paraphrase
from search.models import ChapterParaphrase, ParaphrasePrompt, PromptGlossaryTerm
from translate.chapter_editor_api import staff_json

logger = logging.getLogger(__name__)

# Candidates listed in the studio; older ones stay in the database.
HISTORY_LIMIT = 30


def _json_body(request):
    try:
        data = json.loads(request.body)
        return data if isinstance(data, dict) else None
    except (ValueError, UnicodeDecodeError):
        return None


def _chapter_params(source):
    book = source.get('book', '')
    try:
        chapter = int(source.get('chapter'))
    except (TypeError, ValueError):
        return None, None
    return (book, chapter) if paraphrase.nt_book_abbrev(book) else (None, None)


def _iso(value):
    """ISO time with an explicit UTC offset. USE_TZ is off, so stored times are naive
    UTC; without the offset browsers read them as local time."""
    if value is None:
        return None
    if value.tzinfo is None:
        value = value.replace(tzinfo=dt_timezone.utc)
    return value.isoformat()


def _cost(row, prices):
    price = prices.get(row.model_name)
    if not price or row.input_tokens is None or row.output_tokens is None:
        return None
    input_price, output_price = price
    return round((row.input_tokens * input_price + row.output_tokens * output_price) / 1_000_000, 4)


def _candidate(row, prices, current_hash):
    return {
        'uid': str(row.uid),
        'batch_id': str(row.batch_id),
        'provider': row.provider,
        'model': row.model_name,
        'status': row.status,
        'error': row.error,
        'prompt_name': row.prompt_name,
        'missing_verses': row.missing_verses,
        'input_tokens': row.input_tokens,
        'output_tokens': row.output_tokens,
        'thinking_tokens': row.thinking_tokens,
        'cost_usd': _cost(row, prices),
        'duration_ms': row.duration_ms,
        'is_published': row.is_published,
        'stale': bool(row.source_hash and current_hash and row.source_hash != current_hash),
        'created_by': row.created_by,
        'created_at': _iso(row.created_at),
        'started_at': _iso(row.started_at),
    }


def _preset(prompt):
    return {
        'name': prompt.name,
        'instructions': prompt.instructions,
        'word_guidance': prompt.word_guidance,
        'include_glossary': prompt.include_glossary,
        'is_default': prompt.is_default,
        'updated_by': prompt.updated_by,
        'updated_at': _iso(prompt.updated_at),
    }


@require_GET
@staff_json
def state(request):
    """Everything the studio shows for a chapter; polled while generations run."""
    book, chapter = _chapter_params(request.GET)
    if not book:
        return JsonResponse({'error': 'Unknown NT book or chapter.'}, status=400)

    paraphrase.expire_stale(book, chapter)
    paraphrase.default_prompt()
    current_hash = paraphrase.source_hash(paraphrase.chapter_verses(book, chapter))
    prices = paraphrase.model_prices()
    rows = ChapterParaphrase.objects.filter(book=book, chapter=chapter, language_code='en').defer('html', 'raw_output', 'system_prompt')
    history = list(rows[:HISTORY_LIMIT])
    published = next((r for r in history if r.is_published), None) or rows.filter(is_published=True).first()
    if published and published not in history:
        history.append(published)

    return JsonResponse({
        'candidates': [_candidate(row, prices, current_hash) for row in history],
        'presets': [_preset(p) for p in ParaphrasePrompt.objects.all()],
        'models': paraphrase.available_models(),
        'output_rules': paraphrase.OUTPUT_RULES,
        'glossary_terms': PromptGlossaryTerm.objects.filter(active=True).count(),
    })


@require_GET
@staff_json
def candidate(request):
    row = ChapterParaphrase.objects.filter(uid=request.GET.get('uid')).first() if _is_uuid(request.GET.get('uid')) else None
    if not row:
        return JsonResponse({'error': 'Not found.'}, status=404)
    return JsonResponse({'uid': str(row.uid), 'html': row.html, 'system_prompt': row.system_prompt, 'raw_output': row.raw_output})


def _is_uuid(value):
    try:
        uuid.UUID(str(value))
        return True
    except ValueError:
        return False


@require_POST
@staff_json
def generate(request):
    """POST {book, chapter, models: [[provider, model], ...], instructions, word_guidance, include_glossary, prompt_name}."""
    data = _json_body(request)
    if data is None:
        return JsonResponse({'error': 'Invalid JSON.'}, status=400)
    book, chapter = _chapter_params(data)
    if not book:
        return JsonResponse({'error': 'Unknown NT book or chapter.'}, status=400)

    models = []
    for pair in data.get('models') or []:
        if not (isinstance(pair, list) and len(pair) == 2):
            return JsonResponse({'error': 'models must be [provider, model] pairs.'}, status=400)
        provider, model_name = pair
        if not paraphrase.is_allowed_model(provider, model_name):
            return JsonResponse({'error': f'Model not allowed: {provider}/{model_name}'}, status=400)
        if (provider, model_name) not in models:
            models.append((provider, model_name))
    if not models:
        return JsonResponse({'error': 'Choose at least one model.'}, status=400)
    if len(models) > paraphrase.MAX_MODELS_PER_BATCH:
        return JsonResponse({'error': f'At most {paraphrase.MAX_MODELS_PER_BATCH} models at once.'}, status=400)

    configured = paraphrase.available_models()
    unconfigured = sorted({p for p, _ in models if not configured[p]['configured']})
    if unconfigured:
        return JsonResponse({'error': f'No API key configured for: {", ".join(unconfigured)}'}, status=400)

    instructions = str(data.get('instructions') or '').strip()
    if not instructions or len(instructions) > 20_000:
        return JsonResponse({'error': 'Instructions are required (up to 20,000 characters).'}, status=400)

    try:
        batch_id, rows = paraphrase.start_batch(
            book, chapter, models,
            instructions=instructions,
            word_guidance=str(data.get('word_guidance') or '')[:20_000],
            include_glossary=bool(data.get('include_glossary', True)),
            prompt_name=str(data.get('prompt_name') or '')[:100],
            username=request.user.username,
        )
    except ValueError as exc:
        return JsonResponse({'error': str(exc)}, status=400)
    logger.info('[PARAPHRASE] %s started %s %s with %s', request.user.username, book, chapter, models)
    return JsonResponse({'batch_id': str(batch_id), 'uids': [str(r.uid) for r in rows]})


@require_POST
@staff_json
def publish(request):
    data = _json_body(request) or {}
    if not _is_uuid(data.get('uid')):
        return JsonResponse({'error': 'uid is required.'}, status=400)
    try:
        row = paraphrase.publish(data['uid'])
    except ChapterParaphrase.DoesNotExist:
        return JsonResponse({'error': 'Not found.'}, status=404)
    except ValueError as exc:
        return JsonResponse({'error': str(exc)}, status=400)
    logger.info('[PARAPHRASE] %s published %s %s (%s)', request.user.username, row.book, row.chapter, row.model_name)
    return JsonResponse({'uid': str(row.uid), 'html': row.html, 'hash': paraphrase.html_hash(row.html)})


@require_POST
@staff_json
def unpublish(request):
    data = _json_body(request) or {}
    book, chapter = _chapter_params(data)
    if not book:
        return JsonResponse({'error': 'Unknown NT book or chapter.'}, status=400)
    count = ChapterParaphrase.objects.filter(book=book, chapter=chapter, language_code='en', is_published=True).update(is_published=False)
    return JsonResponse({'unpublished': count})


@require_POST
@staff_json
def delete(request):
    data = _json_body(request) or {}
    if not _is_uuid(data.get('uid')):
        return JsonResponse({'error': 'uid is required.'}, status=400)
    row = ChapterParaphrase.objects.filter(uid=data['uid']).first()
    if not row:
        return JsonResponse({'error': 'Not found.'}, status=404)
    if row.is_published:
        return JsonResponse({'error': 'Unpublish it before deleting.'}, status=400)
    if row.status in ('pending', 'running'):
        return JsonResponse({'error': 'Still generating.'}, status=400)
    row.delete()
    return JsonResponse({'deleted': True})


@require_POST
@staff_json
def save_preset(request):
    """POST {name, instructions, word_guidance, include_glossary, is_default} — create or update by name."""
    data = _json_body(request) or {}
    name = str(data.get('name') or '').strip()[:100]
    instructions = str(data.get('instructions') or '').strip()
    if not name or not instructions:
        return JsonResponse({'error': 'A name and instructions are required.'}, status=400)
    with transaction.atomic():
        prompt, _ = ParaphrasePrompt.objects.update_or_create(name=name, defaults={
            'instructions': instructions[:20_000],
            'word_guidance': str(data.get('word_guidance') or '')[:20_000],
            'include_glossary': bool(data.get('include_glossary', True)),
            'updated_by': request.user.username,
        })
        if data.get('is_default'):
            ParaphrasePrompt.objects.exclude(pk=prompt.pk).update(is_default=False)
            ParaphrasePrompt.objects.filter(pk=prompt.pk).update(is_default=True)
            prompt.refresh_from_db()
    return JsonResponse({'preset': _preset(prompt)})


@require_POST
@staff_json
def edit_block(request):
    """
    POST JSON {uid, index, html, base_hash} → {hash, html}: replace the contents of one
    paragraph (the index-th top-level <p>/<blockquote>) of a paraphrase, edited inline on
    the chapter page. A leading <h5> in html is the heading above that paragraph. base_hash is the hash of the paraphrase HTML the edit started from;
    if it has changed since (republished, or edited in another tab) nothing is written and
    a 409 is returned.
    """
    data = _json_body(request) or {}
    if not _is_uuid(data.get('uid')):
        return JsonResponse({'error': 'uid is required.'}, status=400)
    index, html, base_hash = data.get('index'), data.get('html'), data.get('base_hash')
    if not isinstance(index, int) or isinstance(index, bool) or not isinstance(html, str) or not isinstance(base_hash, str):
        return JsonResponse({'error': 'index, html and base_hash are required.'}, status=400)
    if len(html) > 100_000:
        return JsonResponse({'error': 'Paragraph is too long.'}, status=400)

    with transaction.atomic():
        row = ChapterParaphrase.objects.select_for_update().filter(uid=data['uid']).first()
        if not row:
            return JsonResponse({'error': 'Not found.'}, status=404)
        if paraphrase.html_hash(row.html) != base_hash:
            return JsonResponse({'error': 'This paraphrase was changed elsewhere.', 'hash': paraphrase.html_hash(row.html)}, status=409)
        try:
            new_html, block_html = paraphrase.replace_block(row.html, index, html)
        except IndexError as exc:
            return JsonResponse({'error': str(exc)}, status=400)
        if new_html != row.html:
            row.html = new_html
            row.save(update_fields=['html', 'updated_at'])
    logger.info('[PARAPHRASE] %s edited %s %s paragraph %s', request.user.username, row.book, row.chapter, index)
    return JsonResponse({'hash': paraphrase.html_hash(row.html), 'html': block_html})
