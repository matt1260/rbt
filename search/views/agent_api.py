"""
Private agent API: the reader side of the WordPress rbt/ abilities.

The RBT Translator MCP Bridge plugin (WordPress) registers abilities such as
rbt/get-source-content; for chapters, paraphrases and titles it calls this endpoint
server-to-server:

    POST /api/agent/
    Authorization: Bearer <token>        (its SHA-256 is in settings.RBT_AGENT_TOKEN_SHA256)
    {"ability": "get-source-content", "input": {...}}
 -> {"ok": true, "result": {...}}  |  {"ok": false, "error": "..."}

The work itself is in search/agent_translation.py. Off (404) until a token digest is configured.
"""
import hashlib
import hmac
import json
import logging

from django.conf import settings
from django.core.serializers.json import DjangoJSONEncoder
from django.http import JsonResponse
from django.views.decorators.csrf import csrf_exempt

from search import agent_translation as at
from search import scholarship as sch

logger = logging.getLogger(__name__)


class _Encoder(DjangoJSONEncoder):
    def default(self, o):
        if isinstance(o, (set, frozenset)):
            return sorted(o)
        return super().default(o)


def _agent(a):
    return str(a.get('agent') or 'agent')[:40]


ABILITIES = {
    'list-languages': lambda a: {'languages': at.list_languages()},
    'get-untranslated': lambda a: at.get_untranslated(a.get('kind'), a.get('language'), a.get('limit')),
    'get-outdated': lambda a: at.get_outdated(a.get('kind'), a.get('language'), a.get('limit')),
    'get-source-content': lambda a: at.get_source_content(
        a.get('kind'), a.get('book'), a.get('chapter'), a.get('language'), a.get('job_id'), _agent(a),
        a.get('claim_token'), a.get('request_key')),
    'validate-translation': lambda a: at.validate_translation(
        a.get('kind'), a.get('job_id'), a.get('verses'), a.get('footnotes'), a.get('titles'),
        a.get('extras'), a.get('blocks'), a.get('notes'), a.get('language')),
    'save-translation': lambda a: at.save_translation(
        a.get('kind'), a.get('job_id'), a.get('verses'), a.get('footnotes'), a.get('titles'),
        a.get('extras'), a.get('blocks'), a.get('notes'), a.get('publish', True) is not False, _agent(a),
        a.get('claim_token'), a.get('language')),
    'release-job': lambda a: at.release(a.get('kind'), a.get('job_id'), a.get('reason', ''), bool(a.get('failed')),
                                        a.get('claim_token'), a.get('language')),
    'publish-translation': lambda a: at.publish_translation(
        a.get('kind'), a.get('book'), a.get('chapter'), a.get('language'), a.get('job_id')),
    'get-translation': lambda a: at.get_translation(a.get('kind'), a.get('book'), a.get('chapter'), a.get('language')),
    'get-glossary': lambda a: at.get_glossary(a.get('language')),
    'update-glossary': lambda a: at.update_glossary(a.get('terms'), a.get('remove'), a.get('rules')),
    'get-progress': lambda a: at.get_progress(bool(a.get('detail')), a.get('book'), a.get('language')),
    # Read-only scholarship lookups (search/scholarship.py): independent of the translation queue.
    'get-verse': lambda a: sch.get_verse(a.get('book'), a.get('chapter'), a.get('verse'),
                                         a.get('parallels', True) is not False, a.get('interlinear', True) is not False),
    'get-chapter': lambda a: sch.get_chapter(a.get('book'), a.get('chapter'), a.get('format') or 'text',
                                             a.get('original', True) is not False),
    'search-hebrew': lambda a: sch.search_hebrew(a.get('query'), a.get('field') or 'form', a.get('book'),
                                                 a.get('limit'), a.get('offset')),
    'search-greek': lambda a: sch.search_greek(a.get('query'), a.get('field') or 'form', a.get('book'),
                                               a.get('limit'), a.get('offset')),
    'get-lexeme': lambda a: sch.get_lexeme(a.get('strongs')),
    'get-occurrences': lambda a: sch.get_occurrences(a.get('strongs'), a.get('limit'), a.get('offset')),
    'get-footnotes': lambda a: sch.get_footnotes(a.get('book'), a.get('chapter'), a.get('verse')),
    'get-revisions': lambda a: sch.get_revisions(a.get('book'), a.get('chapter'), a.get('verse'), a.get('version'),
                                                 a.get('since'), a.get('limit'), a.get('offset')),
}


def _authorised(request):
    header = request.META.get('HTTP_AUTHORIZATION', '')
    token = header[7:].strip() if header[:7].lower() == 'bearer ' else ''
    if not token:
        return False
    digest = hashlib.sha256(token.encode('utf-8')).hexdigest()
    return any(hmac.compare_digest(digest, d) for d in settings.RBT_AGENT_TOKEN_SHA256)


def _reply(payload, status=200):
    return JsonResponse(payload, status=status, encoder=_Encoder, json_dumps_params={'ensure_ascii': False})


@csrf_exempt
def agent_api(request):
    if not getattr(settings, 'RBT_AGENT_TOKEN_SHA256', None):
        return _reply({'ok': False, 'error': 'The agent API is switched off.'}, status=404)
    if request.method != 'POST':
        return _reply({'ok': False, 'error': 'POST only'}, status=405)
    if not _authorised(request):
        return _reply({'ok': False, 'error': 'Not authorised'}, status=401)
    try:
        body = json.loads(request.body.decode('utf-8') or '{}')
    except (ValueError, UnicodeDecodeError) as exc:
        return _reply({'ok': False, 'error': f'Invalid JSON: {exc}'}, status=400)
    name = body.get('ability') if isinstance(body, dict) else None
    data = body.get('input') or {} if isinstance(body, dict) else {}
    handler = ABILITIES.get(name)
    if not handler:
        return _reply({'ok': False, 'error': f'Unknown ability {name!r}', 'abilities': sorted(ABILITIES)}, status=404)
    if not isinstance(data, dict):
        return _reply({'ok': False, 'error': '"input" must be an object'}, status=400)
    try:
        result = handler(data)
    except at.ClaimConflict as exc:
        return _reply({'ok': False, 'error': str(exc), 'conflict': True}, status=409)
    except (ValueError, KeyError, TypeError) as exc:
        return _reply({'ok': False, 'error': str(exc)}, status=400)
    except Exception as exc:  # noqa: BLE001 - reported to the agent, logged in full here
        from search.translation_worker import TranslationQueueFull
        if isinstance(exc, TranslationQueueFull):
            return _reply({'ok': False, 'error': str(exc)}, status=503)
        logger.exception('[AGENT API] %s failed', name)
        return _reply({'ok': False, 'error': f'Internal error ({type(exc).__name__}); see the server log'}, status=500)
    logger.info('[AGENT API] %s by %s', name, _agent(data))
    return _reply({'ok': True, 'result': result})
