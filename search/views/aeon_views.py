import json

from django.contrib.auth.decorators import login_required
from django.http import JsonResponse
from django.shortcuts import render
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_GET, require_POST

from ..aeon_service import (
    DEFAULT_CONVERSATION_TITLE,
    DEFAULT_SOURCE_FILE,
    get_corpus_dashboard,
    ingest_conversation_title,
    ingest_wordpress_urls,
    list_corpus_sources,
    query_aeon,
)


@require_GET
def aeon_status(request):
    return JsonResponse({'ok': True, 'sources': list_corpus_sources()})


@login_required
@require_GET
def aeon_dashboard(request):
    return JsonResponse({'ok': True, 'dashboard': get_corpus_dashboard()})


@login_required
@require_GET
def aeon_dashboard_page(request):
    dashboard = get_corpus_dashboard()
    context = {
        'dashboard': dashboard,
        'totals': dashboard.get('totals', {}),
        'by_status': dashboard.get('by_status', {}),
        'by_type': dashboard.get('by_type', {}),
        'latest_source': dashboard.get('latest_source'),
        'failed_sources': dashboard.get('failed_sources', []),
        'sources': dashboard.get('sources', []),
    }
    return render(request, 'aeon_dashboard.html', context)


@csrf_exempt
@require_POST
def aeon_ingest(request):
    try:
        payload = json.loads(request.body.decode('utf-8')) if request.body else {}
    except json.JSONDecodeError:
        return JsonResponse({'ok': False, 'error': 'Invalid JSON body'}, status=400)

    title = payload.get('title') or DEFAULT_CONVERSATION_TITLE
    source_file = payload.get('source_file') or DEFAULT_SOURCE_FILE

    try:
        result = ingest_conversation_title(title=title, source_file=source_file)
        return JsonResponse({'ok': True, 'result': result})
    except Exception as exc:
        return JsonResponse({'ok': False, 'error': str(exc)}, status=500)


@csrf_exempt
@require_POST
def aeon_query(request):
    try:
        payload = json.loads(request.body.decode('utf-8')) if request.body else {}
    except json.JSONDecodeError:
        return JsonResponse({'ok': False, 'error': 'Invalid JSON body'}, status=400)

    question = payload.get('question', '')
    top_k = int(payload.get('top_k', 6))

    try:
        result = query_aeon(question=question, top_k=top_k)
        return JsonResponse({'ok': True, 'result': result})
    except ValueError as exc:
        return JsonResponse({'ok': False, 'error': str(exc)}, status=400)
    except Exception as exc:
        return JsonResponse({'ok': False, 'error': str(exc)}, status=500)


@csrf_exempt
@require_POST
def aeon_ingest_wordpress(request):
    try:
        payload = json.loads(request.body.decode('utf-8')) if request.body else {}
    except json.JSONDecodeError:
        return JsonResponse({'ok': False, 'error': 'Invalid JSON body'}, status=400)

    urls = payload.get('urls', [])
    if not isinstance(urls, list) or not urls:
        return JsonResponse({'ok': False, 'error': 'Provide a non-empty `urls` array'}, status=400)

    try:
        result = ingest_wordpress_urls(urls=urls)
        return JsonResponse({'ok': True, 'result': result})
    except ValueError as exc:
        return JsonResponse({'ok': False, 'error': str(exc)}, status=400)
    except Exception as exc:
        return JsonResponse({'ok': False, 'error': str(exc)}, status=500)
