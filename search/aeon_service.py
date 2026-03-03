import hashlib
import json
import logging
import math
import os
import re
import sys
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from django.conf import settings
from django.utils import timezone
from bs4 import BeautifulSoup
from google import genai

from .models import AeonChunk, AeonCorpusSource

logger = logging.getLogger(__name__)

DEFAULT_CONVERSATION_TITLE = 'Aonic Logos Interpretations'
DEFAULT_SOURCE_FILE = 'conversations.json'
DEFAULT_EMBEDDING_MODELS = [
    'models/gemini-embedding-001',
    'gemini-embedding-001',
    'models/text-embedding-004',
    'text-embedding-004',
]
DEFAULT_GENERATION_MODELS = [
    'models/gemini-2.5-flash',
    'gemini-2.5-flash',
    'models/gemini-3-flash-preview',
]

ROLE_WHITELIST = {'user', 'assistant'}
TEXT_CONTENT_TYPES = {'text'}


@dataclass
class ConversationTurn:
    turn_number: int
    node_id: str
    role: str
    text: str


@dataclass
class TextChunk:
    chunk_index: int
    text: str
    role_mix: str
    start_turn: int
    end_turn: int
    metadata: dict[str, Any]


def _get_gemini_api_keys() -> list[str]:
    keys = os.getenv('GEMINI_API_KEYS', '')
    parsed = [item.strip() for item in keys.split(',') if item.strip()]
    single = os.getenv('GEMINI_API_KEY', '').strip()
    if single:
        parsed.append(single)

    unique: list[str] = []
    seen: set[str] = set()
    for key in parsed:
        if key not in seen:
            seen.add(key)
            unique.append(key)
    return unique


def _is_key_or_quota_error(message: str) -> bool:
    lowered = message.lower()
    indicators = [
        'api key',
        'api_key',
        'expired',
        'invalid',
        'quota',
        'rate limit',
        'resource exhausted',
        'permission denied',
    ]
    return any(item in lowered for item in indicators)


def _resolve_source_path(source_file: str) -> Path:
    candidate = Path(source_file)
    if candidate.is_absolute():
        return candidate
    return Path(settings.BASE_DIR) / source_file


def _read_conversations_file(source_file: str) -> list[dict[str, Any]]:
    source_path = _resolve_source_path(source_file)
    with source_path.open('r', encoding='utf-8') as handle:
        data = json.load(handle)
    if not isinstance(data, list):
        raise ValueError('Expected conversations JSON to be a top-level list')
    return data


def _find_conversation_by_title(source_file: str, title: str) -> dict[str, Any]:
    conversations = _read_conversations_file(source_file)
    for conversation in conversations:
        if isinstance(conversation, dict) and conversation.get('title') == title:
            return conversation
    raise ValueError(f'Conversation title not found: {title}')


def _collect_text_parts(content: dict[str, Any]) -> str:
    if not isinstance(content, dict):
        return ''

    content_type = content.get('content_type')
    if content_type not in TEXT_CONTENT_TYPES:
        return ''

    parts = content.get('parts', [])
    if isinstance(parts, list):
        text_parts: list[str] = []
        for part in parts:
            if isinstance(part, str):
                text_parts.append(part)
            elif isinstance(part, dict):
                text_part = part.get('text')
                if isinstance(text_part, str):
                    text_parts.append(text_part)
        return '\n'.join([p for p in text_parts if p]).strip()

    text = content.get('text')
    if isinstance(text, str):
        return text.strip()

    return ''


def _normalize_text(text: str) -> str:
    cleaned = re.sub(r'\r\n?', '\n', text)
    cleaned = re.sub(r'\n{3,}', '\n\n', cleaned)
    cleaned = re.sub(r'[ \t]+', ' ', cleaned)
    return cleaned.strip()


def extract_main_path_turns(conversation: dict[str, Any]) -> list[ConversationTurn]:
    mapping = conversation.get('mapping', {})
    current_node = conversation.get('current_node')

    if not isinstance(mapping, dict) or not current_node:
        return []

    chain: list[str] = []
    seen: set[str] = set()
    node_id = current_node

    while node_id and node_id in mapping and node_id not in seen:
        seen.add(node_id)
        chain.append(node_id)
        parent_id = mapping[node_id].get('parent')
        if not parent_id or parent_id == node_id:
            break
        node_id = parent_id

    chain.reverse()

    turns: list[ConversationTurn] = []
    turn_index = 1

    for chain_node in chain:
        node = mapping.get(chain_node, {})
        message = node.get('message')
        if not isinstance(message, dict):
            continue

        author = message.get('author', {})
        role = author.get('role') if isinstance(author, dict) else None
        if role not in ROLE_WHITELIST:
            continue

        content = message.get('content', {})
        text = _collect_text_parts(content)
        text = _normalize_text(text)
        if not text:
            continue

        turns.append(
            ConversationTurn(
                turn_number=turn_index,
                node_id=chain_node,
                role=role,
                text=text,
            )
        )
        turn_index += 1

    return turns


def _chunk_turns(turns: list[ConversationTurn], max_words: int = 340, overlap_words: int = 60) -> list[TextChunk]:
    if not turns:
        return []

    chunks: list[TextChunk] = []
    current_tokens: list[str] = []
    current_roles: set[str] = set()
    current_start_turn = turns[0].turn_number
    current_end_turn = turns[0].turn_number
    current_turn_refs: list[int] = []

    def flush_chunk(chunk_index: int) -> None:
        nonlocal current_tokens, current_roles, current_start_turn, current_end_turn, current_turn_refs
        if not current_tokens:
            return
        role_mix = ','.join(sorted(current_roles)) if current_roles else ''
        text = ' '.join(current_tokens).strip()
        metadata = {'turns': current_turn_refs.copy(), 'word_count': len(current_tokens)}
        chunks.append(
            TextChunk(
                chunk_index=chunk_index,
                text=text,
                role_mix=role_mix,
                start_turn=current_start_turn,
                end_turn=current_end_turn,
                metadata=metadata,
            )
        )

    chunk_index = 0
    for turn in turns:
        turn_tokens = turn.text.split()
        if not turn_tokens:
            continue

        if not current_tokens:
            current_start_turn = turn.turn_number

        projected_size = len(current_tokens) + len(turn_tokens)
        if projected_size > max_words and current_tokens:
            flush_chunk(chunk_index)
            chunk_index += 1

            overlap_slice = current_tokens[-overlap_words:] if overlap_words > 0 else []
            current_tokens = overlap_slice.copy()
            current_roles = set(current_roles) if overlap_slice else set()
            current_turn_refs = []
            if overlap_slice:
                current_start_turn = current_end_turn

        current_tokens.extend(turn_tokens)
        current_roles.add(turn.role)
        current_end_turn = turn.turn_number
        current_turn_refs.append(turn.turn_number)

    flush_chunk(chunk_index)
    return chunks


def _chunk_plain_text(text: str, max_words: int = 340, overlap_words: int = 60) -> list[TextChunk]:
    tokens = text.split()
    if not tokens:
        return []

    chunks: list[TextChunk] = []
    start = 0
    chunk_index = 0

    while start < len(tokens):
        end = min(start + max_words, len(tokens))
        chunk_tokens = tokens[start:end]
        if not chunk_tokens:
            break

        chunks.append(
            TextChunk(
                chunk_index=chunk_index,
                text=' '.join(chunk_tokens),
                role_mix='document',
                start_turn=chunk_index + 1,
                end_turn=chunk_index + 1,
                metadata={
                    'turns': [chunk_index + 1],
                    'word_count': len(chunk_tokens),
                },
            )
        )

        chunk_index += 1
        if end >= len(tokens):
            break
        start = max(0, end - overlap_words)

    return chunks


def _extract_slug_from_url(url: str) -> str:
    parsed = urlparse(url)
    slug = parsed.path.strip('/').split('/')[-1]
    if not slug:
        raise ValueError(f'Unable to derive slug from URL: {url}')
    return slug


def _load_wordpress_connector() -> Any:
    scripts_dir = Path(settings.BASE_DIR) / 'scripts'
    scripts_str = str(scripts_dir)
    if scripts_str not in sys.path:
        sys.path.insert(0, scripts_str)

    from wordpress_db import WordPressDBConnector  # type: ignore

    return WordPressDBConnector()


def _fetch_wordpress_post_from_db(url: str) -> dict[str, Any] | None:
    slug = _extract_slug_from_url(url)
    connector = _load_wordpress_connector()

    query = """
    SELECT ID, post_title, post_content, post_modified, post_name, post_type
    FROM wplo_posts
    WHERE post_name = %s
      AND post_status = 'publish'
      AND post_type IN ('post', 'page')
    ORDER BY post_modified DESC
    LIMIT 1
    """

    row = connector.execute_query(query, (slug,), fetch='one')
    if not row:
        return None

    return {
        'id': row.get('ID'),
        'slug': row.get('post_name') or slug,
        'title': row.get('post_title') or slug,
        'html': row.get('post_content') or '',
        'post_type': row.get('post_type'),
        'post_modified': str(row.get('post_modified') or ''),
        'url': url,
        'fetch_method': 'wordpress_db',
    }


def _fetch_wordpress_post_from_web(url: str) -> dict[str, Any] | None:
    slug = _extract_slug_from_url(url)
    req = urllib.request.Request(
        url,
        headers={'User-Agent': 'Mozilla/5.0 (compatible; AeonBot/1.0)'},
    )
    with urllib.request.urlopen(req, timeout=20) as response:
        html = response.read().decode('utf-8', errors='replace')

    soup = BeautifulSoup(html, 'html.parser')
    title = ''
    title_tag = soup.find('h1') or soup.find('title')
    if title_tag:
        title = title_tag.get_text(' ', strip=True)

    article = soup.find('article')
    body_html = str(article) if article else html

    return {
        'id': None,
        'slug': slug,
        'title': title or slug,
        'html': body_html,
        'post_type': 'web',
        'post_modified': '',
        'url': url,
        'fetch_method': 'web_fallback',
    }


def _html_to_text(html: str) -> str:
    soup = BeautifulSoup(html or '', 'html.parser')
    for tag in soup(['script', 'style', 'noscript']):
        tag.decompose()
    text = soup.get_text('\n')
    return _normalize_text(text)


def _hash_text(text: str) -> str:
    return hashlib.sha256(text.encode('utf-8')).hexdigest()


def _embed_text(text: str, task_type: str) -> list[float]:
    api_keys = _get_gemini_api_keys()
    if not api_keys:
        raise RuntimeError('No Gemini API key found in GEMINI_API_KEYS/GEMINI_API_KEY')

    last_error: Exception | None = None
    for api_key in api_keys:
        client = genai.Client(api_key=api_key)
        for model_name in DEFAULT_EMBEDDING_MODELS:
            try:
                response = client.models.embed_content(
                    model=model_name,
                    contents=text,
                    config={
                        'task_type': task_type,
                    },
                )

                embeddings = getattr(response, 'embeddings', None)
                if not embeddings:
                    continue

                first_embedding = embeddings[0]
                values = getattr(first_embedding, 'values', None)
                if isinstance(values, list) and values:
                    return [float(value) for value in values]
            except Exception as exc:
                last_error = exc
                message = str(exc)
                lowered = message.lower()
                if 'not found' in lowered or 'not supported' in lowered:
                    continue
                if _is_key_or_quota_error(message):
                    break

    if last_error:
        raise RuntimeError(f'Embedding failed across available Gemini keys/models: {last_error}') from last_error
    raise RuntimeError('Embedding failed across available Gemini keys/models')


def ingest_conversation_title(
    title: str = DEFAULT_CONVERSATION_TITLE,
    source_file: str = DEFAULT_SOURCE_FILE,
) -> dict[str, Any]:
    conversation = _find_conversation_by_title(source_file=source_file, title=title)
    source_identifier = str(conversation.get('id') or conversation.get('conversation_id') or title)

    source, _ = AeonCorpusSource.objects.get_or_create(
        source_type='conversation',
        source_identifier=source_identifier,
        defaults={'title': title},
    )

    source.title = title
    source.status = 'processing'
    source.error_message = None
    source.metadata = {
        'conversation_id': conversation.get('conversation_id'),
        'current_node': conversation.get('current_node'),
        'source_file': str(_resolve_source_path(source_file)),
    }
    source.save(update_fields=['title', 'status', 'error_message', 'metadata', 'updated_at'])

    turns = extract_main_path_turns(conversation)
    chunks = _chunk_turns(turns)

    AeonChunk.objects.filter(source=source).delete()

    chunk_count = 0
    embedded_count = 0

    for chunk in chunks:
        embedding: list[float] | None = None
        try:
            embedding = _embed_text(chunk.text, task_type='retrieval_document')
            embedded_count += 1
        except Exception as exc:
            logger.warning('Aeon chunk embedding failed for chunk %s: %s', chunk.chunk_index, exc)

        AeonChunk.objects.create(
            source=source,
            chunk_index=chunk.chunk_index,
            role_mix=chunk.role_mix,
            start_turn=chunk.start_turn,
            end_turn=chunk.end_turn,
            text=chunk.text,
            text_hash=_hash_text(chunk.text),
            embedding=embedding,
            metadata=chunk.metadata,
        )
        chunk_count += 1

    source.last_ingested_at = timezone.now()
    source.status = 'ready' if embedded_count > 0 else 'failed'
    if embedded_count == 0:
        source.error_message = 'No embeddings were created; verify Gemini API key and quota.'
    source.save(update_fields=['status', 'last_ingested_at', 'error_message', 'updated_at'])

    return {
        'source_id': source.pk,
        'source_identifier': source.source_identifier,
        'title': source.title,
        'turn_count': len(turns),
        'chunk_count': chunk_count,
        'embedded_chunk_count': embedded_count,
        'status': source.status,
    }


def ingest_wordpress_urls(urls: list[str]) -> dict[str, Any]:
    if not urls:
        raise ValueError('At least one URL is required')

    per_source_results: list[dict[str, Any]] = []
    total_chunks = 0
    total_embedded_chunks = 0

    for raw_url in urls:
        url = raw_url.strip()
        if not url:
            continue

        try:
            post = _fetch_wordpress_post_from_db(url)
        except Exception as exc:
            logger.warning('WordPress DB fetch failed for %s: %s', url, exc)
            post = None

        if not post:
            post = _fetch_wordpress_post_from_web(url)
        if not post:
            raise ValueError(f'Unable to fetch content for URL: {url}')

        text = _html_to_text(post.get('html') or '')
        if not text:
            raise ValueError(f'No textual content extracted for URL: {url}')

        source_identifier = f"wp:{post['slug']}"
        source, _ = AeonCorpusSource.objects.get_or_create(
            source_type='wordpress_post',
            source_identifier=source_identifier,
            defaults={'title': post.get('title') or post['slug']},
        )

        source.title = post.get('title') or post['slug']
        source.status = 'processing'
        source.error_message = None
        source.metadata = {
            'url': post.get('url'),
            'slug': post.get('slug'),
            'wp_post_id': post.get('id'),
            'post_type': post.get('post_type'),
            'post_modified': post.get('post_modified'),
            'fetch_method': post.get('fetch_method'),
        }
        source.save(update_fields=['title', 'status', 'error_message', 'metadata', 'updated_at'])

        chunks = _chunk_plain_text(text)
        AeonChunk.objects.filter(source=source).delete()

        chunk_count = 0
        embedded_count = 0
        for chunk in chunks:
            embedding: list[float] | None = None
            try:
                embedding = _embed_text(chunk.text, task_type='retrieval_document')
                embedded_count += 1
            except Exception as exc:
                logger.warning('WordPress chunk embedding failed for %s chunk %s: %s', post.get('slug'), chunk.chunk_index, exc)

            chunk_metadata = {
                **chunk.metadata,
                'url': post.get('url'),
                'slug': post.get('slug'),
            }

            AeonChunk.objects.create(
                source=source,
                chunk_index=chunk.chunk_index,
                role_mix=chunk.role_mix,
                start_turn=chunk.start_turn,
                end_turn=chunk.end_turn,
                text=chunk.text,
                text_hash=_hash_text(chunk.text),
                embedding=embedding,
                metadata=chunk_metadata,
            )
            chunk_count += 1

        source.last_ingested_at = timezone.now()
        source.status = 'ready' if embedded_count > 0 else 'failed'
        if embedded_count == 0:
            source.error_message = 'No embeddings were created; verify Gemini API keys and quota.'
        source.save(update_fields=['status', 'last_ingested_at', 'error_message', 'updated_at'])

        total_chunks += chunk_count
        total_embedded_chunks += embedded_count
        per_source_results.append(
            {
                'source_id': source.pk,
                'source_identifier': source.source_identifier,
                'title': source.title,
                'status': source.status,
                'url': post.get('url'),
                'fetch_method': post.get('fetch_method'),
                'chunk_count': chunk_count,
                'embedded_chunk_count': embedded_count,
            }
        )

    return {
        'source_count': len(per_source_results),
        'chunk_count': total_chunks,
        'embedded_chunk_count': total_embedded_chunks,
        'sources': per_source_results,
    }


def _cosine_similarity(vec_a: list[float], vec_b: list[float]) -> float:
    if not vec_a or not vec_b or len(vec_a) != len(vec_b):
        return -1.0

    dot_product = sum(a * b for a, b in zip(vec_a, vec_b))
    norm_a = math.sqrt(sum(a * a for a in vec_a))
    norm_b = math.sqrt(sum(b * b for b in vec_b))
    if norm_a == 0 or norm_b == 0:
        return -1.0
    return dot_product / (norm_a * norm_b)


def _build_context(snippets: list[dict[str, Any]]) -> str:
    context_blocks = []
    for item in snippets:
        context_blocks.append(
            f"[source:{item['source_title']} chunk:{item['chunk_index']} turns:{item['start_turn']}-{item['end_turn']}]\n{item['text']}"
        )
    return '\n\n'.join(context_blocks)


def _generate_answer(question: str, context: str) -> str:
    api_keys = _get_gemini_api_keys()
    if not api_keys:
        raise RuntimeError('No Gemini API key found in GEMINI_API_KEYS/GEMINI_API_KEY')

    system_prompt = (
        'You are Aeon Bot. Ground answers in the provided context only. '
        'If context is insufficient, say so briefly and ask for clarification. '
        'Maintain conceptual continuity with Aonic Logos terminology without inventing facts.'
    )
    prompt = (
        f"{system_prompt}\n\n"
        f"Context:\n{context}\n\n"
        f"Question:\n{question}\n\n"
        'Answer with concise, direct prose and include a short evidence note listing relevant chunk ids.'
    )

    last_error: Exception | None = None
    for api_key in api_keys:
        client = genai.Client(api_key=api_key)
        for model_name in DEFAULT_GENERATION_MODELS:
            try:
                response = client.models.generate_content(
                    model=model_name,
                    contents=prompt,
                )
                text = getattr(response, 'text', '') or ''
                text_value = str(text).strip()
                if text_value:
                    return text_value
            except Exception as exc:
                last_error = exc
                message = str(exc)
                lowered = message.lower()
                if 'not found' in lowered or 'not supported' in lowered:
                    continue
                if _is_key_or_quota_error(message):
                    break

    if last_error:
        raise RuntimeError(f'Generation failed across available Gemini keys/models: {last_error}') from last_error
    raise RuntimeError('Generation failed across available Gemini keys/models')


def query_aeon(question: str, top_k: int = 6) -> dict[str, Any]:
    if not question or not question.strip():
        raise ValueError('Question is required')

    ready_source_count = AeonCorpusSource.objects.filter(status='ready').count()
    if ready_source_count == 0:
        raise ValueError('No Aeon corpus is ready. Run ingestion first.')

    query_embedding = _embed_text(question.strip(), task_type='retrieval_query')

    candidates = []
    for chunk in AeonChunk.objects.filter(source__status='ready').select_related('source').only(
        'chunk_index', 'text', 'embedding', 'start_turn', 'end_turn', 'role_mix', 'metadata',
        'source__id', 'source__title', 'source__source_type', 'source__source_identifier', 'source__last_ingested_at'
    ):
        if not isinstance(chunk.embedding, list):
            continue
        similarity = _cosine_similarity(query_embedding, chunk.embedding)
        if similarity < -0.5:
            continue
        candidates.append((similarity, chunk))

    candidates.sort(key=lambda item: item[0], reverse=True)
    top_chunks = candidates[:max(1, top_k)]

    snippets: list[dict[str, Any]] = []
    for score, chunk in top_chunks:
        snippets.append(
            {
                'source_id': chunk.source_id,
                'source_title': chunk.source.title,
                'source_type': chunk.source.source_type,
                'source_identifier': chunk.source.source_identifier,
                'chunk_index': chunk.chunk_index,
                'score': round(float(score), 6),
                'start_turn': chunk.start_turn,
                'end_turn': chunk.end_turn,
                'role_mix': chunk.role_mix,
                'text': chunk.text,
            }
        )

    context = _build_context(snippets)
    answer = _generate_answer(question=question.strip(), context=context)

    source_list = []
    seen_sources: set[int] = set()
    for item in snippets:
        source_id = item['source_id']
        if source_id in seen_sources:
            continue
        seen_sources.add(source_id)
        source_list.append(
            {
                'id': source_id,
                'title': item['source_title'],
                'type': item['source_type'],
                'identifier': item['source_identifier'],
            }
        )

    primary_source = source_list[0] if source_list else None

    return {
        'source': primary_source,
        'sources': source_list,
        'question': question.strip(),
        'answer': answer,
        'snippets': snippets,
    }


def list_corpus_sources() -> list[dict[str, Any]]:
    rows = (
        AeonCorpusSource.objects
        .all()
        .order_by('-updated_at')
        .values('id', 'source_type', 'source_identifier', 'title', 'status', 'last_ingested_at', 'updated_at', 'error_message')
    )

    result = []
    for row in rows:
        chunk_count = AeonChunk.objects.filter(source_id=row['id']).count()
        result.append(
            {
                **row,
                'chunk_count': chunk_count,
                'last_ingested_at': row['last_ingested_at'].isoformat() if row['last_ingested_at'] else None,
                'updated_at': row['updated_at'].isoformat() if row['updated_at'] else None,
            }
        )
    return result


def get_corpus_dashboard() -> dict[str, Any]:
    sources = list_corpus_sources()

    total_sources = len(sources)
    total_chunks = sum(int(item.get('chunk_count') or 0) for item in sources)

    by_status: dict[str, int] = {}
    by_type: dict[str, int] = {}
    failed_sources: list[dict[str, Any]] = []

    for source in sources:
        status = str(source.get('status') or 'unknown')
        source_type = str(source.get('source_type') or 'unknown')

        by_status[status] = by_status.get(status, 0) + 1
        by_type[source_type] = by_type.get(source_type, 0) + 1

        if status == 'failed':
            failed_sources.append(
                {
                    'id': source.get('id'),
                    'title': source.get('title'),
                    'source_type': source_type,
                    'source_identifier': source.get('source_identifier'),
                    'error_message': source.get('error_message'),
                    'updated_at': source.get('updated_at'),
                }
            )

    latest_source = sources[0] if sources else None

    return {
        'totals': {
            'sources': total_sources,
            'chunks': total_chunks,
        },
        'by_status': by_status,
        'by_type': by_type,
        'latest_source': latest_source,
        'failed_sources': failed_sources[:10],
        'sources': sources,
    }
