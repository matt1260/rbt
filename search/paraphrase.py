"""
AI chapter paraphrases: the "Paraphrase" reader view on NT chapter pages.

Staff generate a whole chapter as flowing, readable English with one or more models at
once (translate/paraphrase_api.py, driven by the Paraphrase Studio in chapter-editor/),
compare the results and publish one. Every generation is kept in ChapterParaphrase.

Pipeline for one generation:
  1. prepare_source(): the chapter's stored RBT verse HTML (new_testament.nt.rbt) is
     reduced to text plus the colour/hayah spans worth keeping. Images, videos and
     tooltip blocks are pulled out as numbered media items with their captions.
  2. build_system_prompt(): the editable preset (style + word guidance + the shared
     translation glossary) followed by OUTPUT_RULES, which the page depends on and
     staff can't edit.
  3. The model runs in a background thread (a chapter takes minutes; gunicorn times
     requests out at 60s). The row's status moves pending -> running -> done/failed.
  4. finalize_output(): sanitise to an allowlist, turn each <rbt-media n=".."> marker into
     a small inline image cue (a round thumbnail at the end of the sentence; clicking it
     opens the image and its notes in a modal, static/reader-paraphrase.js), keep the
     original media HTML in inert <template>s (so a model can never alter an image URL and
     nothing loads until opened), add cues for media the model skipped, add #vN anchors,
     and list verses no data-v range covers.
"""
import hashlib
import logging
import os
import re
import threading
import time
import uuid
from dataclasses import dataclass
from datetime import timedelta

import nh3
from bs4 import BeautifulSoup
from django.db import close_old_connections, transaction
from django.utils import timezone

from search.db_utils import execute_query
from search.models import ChapterParaphrase, ParaphrasePrompt, PromptGlossaryTerm
from translate.translator import book_abbreviations, new_testament_books

logger = logging.getLogger(__name__)

# One model call may run this long before it's abandoned.
REQUEST_TIMEOUT_SECONDS = 600
# Rows still pending/running after this long were interrupted (e.g. a worker restart).
STALE_AFTER_SECONDS = REQUEST_TIMEOUT_SECONDS + 300
MAX_MODELS_PER_BATCH = 8

DEFAULT_GEMINI_MODELS = ['gemini-3.8-flash', 'gemini-3.1-pro-preview', 'gemini-3.6-flash', 'gemini-3.5-flash-lite']

DEFAULT_PROMPT_NAME = 'Default'
DEFAULT_INSTRUCTIONS = """
You are writing the Reader's Paraphrase of one chapter of the RBT (Real Bible Translation): a smooth, highly readable English page that a modern reader can read straight through, while staying faithful to the RBT's meaning and its distinctive vocabulary.

- Combine verses into natural paragraphs. Never present one verse per line.
- Smooth awkward literal word order and phrasing into fluent contemporary English.
- Keep the RBT's distinctive renderings of names and key terms (for example "the Logos Ratio") rather than replacing them with traditional wording.
- Where the source gives a traditional name in parentheses, e.g. ("Jerusalem"), keep it the first time the name appears in the chapter and drop it afterwards.
- Do not add headings. Mark a shift of subject with a new paragraph instead.
- Level of paraphrase: moderate. Clarify and smooth; do not reinterpret or add ideas.
""".strip()

# Appended to every system prompt. The reader page, the sanitiser and the coverage
# check all depend on this format, so it isn't part of the editable preset.
OUTPUT_RULES = """
OUTPUT FORMAT (required; the page depends on it):
- Return only an HTML fragment. No markdown, no code fences, no <html>, <head>, <body>, <style> or <script>.
- Allowed elements: p, blockquote, ul, ol, li, em, strong, span, br, hr, rbt-media. No headings of any kind: the page flows as paragraphs.
- Put data-v on every paragraph, blockquote or list that carries verse content, giving the verse range it covers: <p data-v="3-5">...</p> or <p data-v="7">...</p>. Together the ranges must cover every verse of the chapter.
- Keep the RBT colour coding where it still fits by reusing the source's spans exactly: <span style="color: blue;"> and <span style="color: #ff00aa;">. Keep <span class="hayah"> as it is.
- Optional classes: <p class="pp-lead"> for an opening paragraph, <p class="pp-indent"> for an indented paragraph, <blockquote class="pp-poetry"> for poetic or quoted lines (use <br> between lines).
- Mark every media item exactly once with an inline marker inside the paragraph, right after the sentence it best illustrates (after the sentence's closing punctuation): <rbt-media n="N"></rbt-media>. Readers see a small image cue there that opens the image and its notes, so the text itself stays uninterrupted; never put a marker between paragraphs.
- Do not invent content, add commentary or explain your choices.
""".strip()

ALLOWED_TAGS = {'p', 'blockquote', 'ul', 'ol', 'li', 'em', 'strong', 'span', 'br', 'hr', 'rbt-media'}
ALLOWED_ATTRIBUTES = {
    'p': {'data-v', 'class'},
    'blockquote': {'data-v', 'class'},
    'ul': {'data-v'},
    'ol': {'data-v'},
    'li': {'data-v'},
    'span': {'style', 'class'},
    'rbt-media': {'n'},
}
ALLOWED_CLASSES = {
    'p': {'pp-lead', 'pp-indent'},
    'blockquote': {'pp-poetry'},
    'span': {'hayah'},
}
ALLOWED_STYLES = {'color: blue;', 'color: #ff00aa;'}
VERSE_RANGE = re.compile(r'^(\d+)(?:-(\d+))?$')


# ---------------------------------------------------------------------------
# Models available to the studio

def available_models():
    """{'gemini': [...], 'openai': [...]} plus whether each provider has an API key."""
    gemini = [m.strip() for m in os.getenv('PARAPHRASE_GEMINI_MODELS', '').split(',') if m.strip()] or DEFAULT_GEMINI_MODELS
    from translate.views import CHATGPT_MODEL_CHOICES  # env-driven list shared with the verse editor
    return {
        'gemini': {'models': gemini, 'configured': bool(_gemini_key())},
        'openai': {'models': list(CHATGPT_MODEL_CHOICES), 'configured': bool(os.getenv('CHATGPT_KEY'))},
    }


def is_allowed_model(provider, model_name):
    info = available_models().get(provider)
    return bool(info and model_name in info['models'])


def model_prices():
    """Optional USD prices per million tokens from PARAPHRASE_MODEL_PRICES, e.g.
    'gemini-3.8-flash=0.3/2.5,gpt-5.6-terra=1.25/10' (input/output)."""
    prices = {}
    for item in os.getenv('PARAPHRASE_MODEL_PRICES', '').split(','):
        name, _, pair = item.partition('=')
        try:
            input_price, output_price = (float(x) for x in pair.split('/'))
        except ValueError:
            continue
        prices[name.strip()] = (input_price, output_price)
    return prices


# ---------------------------------------------------------------------------
# Source

@dataclass
class Media:
    n: int
    verse: str
    html: str
    kind: str
    caption: str
    title: str = ''


def nt_book_abbrev(book):
    return book_abbreviations.get(book, book) if book in new_testament_books else None


def chapter_verses(book, chapter):
    """[(verse, stored RBT html)] for an NT chapter, in order."""
    rows = execute_query(
        "SELECT startVerse, rbt FROM new_testament.nt WHERE book = %s AND chapter = %s ORDER BY startVerse",
        (nt_book_abbrev(book), chapter),
        fetch='all',
    ) or []
    return [(str(verse), html or '') for verse, html in rows]


def source_hash(verses):
    """Fingerprint of the chapter text, to flag a paraphrase whose source has since changed."""
    digest = hashlib.sha256()
    for verse, html in verses:
        digest.update(f'{verse}\x1f{html}\x1e'.encode('utf-8'))
    return digest.hexdigest()


def _keep_source_attr(tag, attr, value):
    if attr == 'style':
        return value if value.strip() in ALLOWED_STYLES else None
    if attr == 'class':
        return 'hayah' if 'hayah' in value.split() else None
    return value


def prepare_source(verses):
    """Model input text for the chapter, and the media items pulled out of it."""
    media = []
    lines = []
    for verse, html in verses:
        soup = BeautifulSoup(html, 'html.parser')
        containers = soup.select('.tooltip-container')
        loose = [el for el in soup.find_all(['img', 'video']) if not el.find_parent(class_='tooltip-container')]
        for el in containers + loose:
            caption_el = el.select_one('.tooltip, .tooltip2') if el.name == 'div' else None
            caption = ' '.join((caption_el.get_text(' ', strip=True) if caption_el else el.get('alt', '')).split())
            heading = caption_el.find(['b', 'strong']) if caption_el else None
            title = ' '.join(heading.get_text(' ', strip=True).split()) if heading else re.split(r'(?<=[.!?])\s', caption, 1)[0]
            kind = 'video' if (el.name == 'video' or el.find('video')) else 'image'
            media.append(Media(n=len(media) + 1, verse=verse, html=str(el), kind=kind, caption=caption[:400],
                               title=title.strip(' .:')[:90]))
            el.decompose()
        for anchor in soup.select('a.sdfootnoteanc, a[href*="footnote="]'):
            anchor.decompose()
        text = nh3.clean(
            str(soup),
            tags={'span', 'strong', 'b', 'em', 'i', 'br'},
            # Section headings are editorial, not verse text; the paraphrase has none.
            clean_content_tags={'h5', 'h4', 'h6', 'script', 'style'},
            attributes={'span': {'style', 'class'}},
            attribute_filter=_keep_source_attr,
            strip_comments=True,
            link_rel=None,
        )
        text = ' '.join(text.split())
        if text:
            lines.append(f'[{verse}] {text}')
    return '\n'.join(lines), media


def build_user_prompt(book, chapter, source_text, media):
    parts = [f'CHAPTER: {book} {chapter}', '', 'SOURCE (RBT, one line per verse, verse number in brackets):', source_text]
    if media:
        parts += ['', 'MEDIA (mark each exactly once with <rbt-media n="N"></rbt-media> right after the sentence it illustrates):']
        for item in media:
            caption = f': "{item.caption}"' if item.caption else ''
            parts.append(f'{item.n}. {item.kind}, originally after verse {item.verse}{caption}')
    else:
        parts += ['', 'MEDIA: none']
    return '\n'.join(parts)


def glossary_block():
    lines = []
    for term in PromptGlossaryTerm.objects.filter(active=True):
        line = f'- "{term.term}": {term.sense}'
        if term.avoid:
            line += f' Avoid: {term.avoid}'
        lines.append(line)
    return '\n'.join(lines)


def build_system_prompt(instructions, word_guidance='', include_glossary=True):
    parts = [instructions.strip() or DEFAULT_INSTRUCTIONS]
    if word_guidance.strip():
        parts.append('WORD AND USAGE GUIDANCE:\n' + word_guidance.strip())
    if include_glossary:
        glossary = glossary_block()
        if glossary:
            parts.append('RBT TERMS (keep these senses):\n' + glossary)
    parts.append(OUTPUT_RULES)
    return '\n\n'.join(parts)


def default_prompt():
    """The default preset, created from DEFAULT_INSTRUCTIONS on first use."""
    prompt = ParaphrasePrompt.objects.filter(is_default=True).first()
    if prompt:
        return prompt
    prompt, _ = ParaphrasePrompt.objects.get_or_create(
        name=DEFAULT_PROMPT_NAME,
        defaults={'instructions': DEFAULT_INSTRUCTIONS, 'is_default': True},
    )
    if not prompt.is_default:
        prompt.is_default = True
        prompt.save(update_fields=['is_default'])
    return prompt


# ---------------------------------------------------------------------------
# Output

def _keep_output_attr(tag, attr, value):
    if attr == 'class':
        kept = [c for c in value.split() if c in ALLOWED_CLASSES.get(tag, ())]
        return ' '.join(kept) or None
    if attr == 'style':
        return value.strip() if value.strip() in ALLOWED_STYLES else None
    if attr == 'data-v':
        return value.strip() if VERSE_RANGE.match(value.strip()) else None
    if attr == 'n':
        return value if value.isdigit() else None
    return value


def _strip_fences(text):
    text = text.strip()
    text = re.sub(r'^```[a-zA-Z]*\s*', '', text)
    return re.sub(r'\s*```$', '', text).strip()


def verse_range(value):
    match = VERSE_RANGE.match(value or '')
    if not match:
        return []
    start = int(match.group(1))
    end = int(match.group(2) or start)
    return list(range(start, end + 1)) if start <= end <= start + 200 else []


PLAY_ICON = (
    '<svg class="pp-cue__icon" viewBox="-3 -3 30 30" aria-hidden="true" focusable="false">'
    '<path d="M9.5 6.8v10.4l8-5.2z" fill="currentColor"/></svg>'
)
IMAGE_ICON = (
    '<svg class="pp-cue__icon" viewBox="-3 -3 30 30" aria-hidden="true" focusable="false">'
    '<rect x="4" y="5" width="16" height="14" rx="2" fill="none" stroke="currentColor" stroke-width="2"/>'
    '<path d="M6.5 16.5l3.5-4.5 2.8 3 1.9-2 2.8 3.5z" fill="currentColor"/></svg>'
)


def _cue(soup, item):
    """Small round thumbnail button that opens the media in the reader's modal."""
    label = f'View {"video" if item.kind == "video" else "image"}' + (f': {item.title}' if item.title else '')
    cue = soup.new_tag('button', attrs={
        'type': 'button', 'class': f'pp-cue pp-cue--{item.kind}', 'data-media': str(item.n),
        'aria-label': label, 'title': item.title or label,
    })
    source = BeautifulSoup(item.html, 'html.parser')
    img = source.find('img')
    if item.kind == 'image' and img and img.get('src'):
        cue.append(soup.new_tag('img', attrs={
            'class': 'pp-cue__thumb', 'src': img['src'], 'alt': '', 'loading': 'lazy', 'decoding': 'async',
        }))
    else:
        # An SVG, not a text glyph: a glyph sits on its font baseline, several pixels lower
        # than the thumbnails, and may render as an emoji. Like a thumbnail it fills the whole
        # cue (the drawing is inset by the viewBox), so every cue aligns the same way.
        cue.append(BeautifulSoup(PLAY_ICON if item.kind == 'video' else IMAGE_ICON, 'html.parser'))
    return cue


def _store(soup, media):
    """The original media HTML, inert until the reader opens a cue (templates don't load images)."""
    store = soup.new_tag('div', attrs={'class': 'pp-media-store', 'hidden': ''})
    for item in media:
        template = soup.new_tag('template', attrs={'data-media': str(item.n)})
        template.append(BeautifulSoup(item.html, 'html.parser'))
        store.append(template)
    return store


def _attach_cue(block, cue):
    """Put a cue at the end of a block's text (before any trailing whitespace)."""
    block.append(' ')
    block.append(cue)


def finalize_output(raw, media, verse_numbers):
    """Sanitised reader HTML and the list of verses no data-v range covers."""
    clean = nh3.clean(
        _strip_fences(raw),
        tags=ALLOWED_TAGS,
        attributes=ALLOWED_ATTRIBUTES,
        attribute_filter=_keep_output_attr,
        strip_comments=True,
        link_rel=None,
        # Headings are dropped with their text: the paraphrase flows as paragraphs.
        clean_content_tags={'script', 'style', 'h1', 'h2', 'h3', 'h4', 'h5', 'h6'},
    )
    soup = BeautifulSoup(clean, 'html.parser')
    by_number = {item.n: item for item in media}
    placed = set()

    for placeholder in soup.find_all('rbt-media'):
        n = int(placeholder.get('n') or 0)
        item = by_number.get(n)
        if not item or n in placed:
            placeholder.decompose()
            continue
        placed.add(n)
        cue = _cue(soup, item)
        if placeholder.parent is not soup:
            placeholder.replace_with(cue)
            continue
        # A marker left between paragraphs joins the end of the paragraph before it
        # (or the start of the one after, at the very top).
        previous = placeholder.find_previous_sibling(lambda tag: tag.name in ('p', 'blockquote', 'ul', 'ol'))
        following = placeholder.find_next_sibling(lambda tag: tag.name in ('p', 'blockquote', 'ul', 'ol'))
        placeholder.decompose()
        if previous:
            _attach_cue(previous.find_all('li')[-1] if previous.name in ('ul', 'ol') and previous.find('li') else previous, cue)
        elif following:
            following.insert(0, cue)
        else:
            soup.append(cue)

    blocks = soup.find_all(attrs={'data-v': True})
    covered = set()
    for block in blocks:
        verses = verse_range(block['data-v'])
        covered.update(verses)
        # Anchors so /john/1/#v12 links land on the paragraph holding verse 12.
        for verse in reversed(verses):
            if not soup.find(id=f'v{verse}'):
                block.insert(0, soup.new_tag('span', attrs={'id': f'v{verse}', 'class': 'pp-anchor'}))

    # Media the model left out: a cue at the end of the paragraph covering its verse.
    for item in media:
        if item.n in placed:
            continue
        target = next((b for b in reversed(blocks) if item.verse.isdigit() and int(item.verse) in verse_range(b['data-v'])), None)
        target = target or (blocks[-1] if blocks else None)
        if target:
            _attach_cue(target, _cue(soup, item))
        else:
            soup.append(_cue(soup, item))

    if media:
        soup.append(_store(soup, media))

    missing = sorted(int(v) for v in verse_numbers if v.isdigit() and int(v) not in covered)
    return str(soup).strip(), missing


# ---------------------------------------------------------------------------
# Providers

def _gemini_keys():
    """The GEMINI_API_KEYS pool (as the page translator uses), then GEMINI_API_KEY."""
    keys = [k.strip() for k in os.getenv('GEMINI_API_KEYS', '').split(',') if k.strip()]
    single = os.getenv('GEMINI_API_KEY', '').strip()
    if single and single not in keys:
        keys.append(single)
    return keys


def _gemini_key():
    keys = _gemini_keys()
    return keys[0] if keys else ''


# Waits before retrying when the model is overloaded (503 "high demand" and similar).
TRANSIENT_BACKOFF_SECONDS = (10, 30, 60)


def _is_transient(exc):
    text = str(exc)
    return any(marker in text for marker in ('503', 'UNAVAILABLE', '500 INTERNAL', 'DEADLINE_EXCEEDED', 'overloaded', 'high demand'))


def _is_key_problem(exc):
    """Invalid, revoked or rate-limited key: worth retrying with the next key."""
    text = str(exc)
    return any(marker in text for marker in ('API_KEY_INVALID', 'API key not valid', 'PERMISSION_DENIED', '429', 'RESOURCE_EXHAUSTED'))


def _call_gemini(model_name, system_prompt, user_prompt):
    from google import genai
    from google.genai import types
    from translate.views import get_ipv4_transport

    keys = _gemini_keys()
    if not keys:
        raise RuntimeError('No Gemini API key is configured (GEMINI_API_KEYS or GEMINI_API_KEY).')
    # Spread simultaneous generations across the pool; move to the next key when one is
    # rejected or rate-limited, and wait and retry when the model is overloaded.
    key_index = threading.get_ident() % len(keys)
    keys_tried = 0
    transient_retries = 0
    while True:
        client = genai.Client(
            api_key=keys[key_index % len(keys)],
            http_options=types.HttpOptions(
                timeout=REQUEST_TIMEOUT_SECONDS * 1000,
                client_args={'transport': get_ipv4_transport()},
            ),
        )
        try:
            response = client.models.generate_content(
                model=model_name,
                contents=user_prompt,
                config=types.GenerateContentConfig(system_instruction=system_prompt),
            )
            break
        except Exception as exc:
            if _is_key_problem(exc) and keys_tried < len(keys) - 1:
                keys_tried += 1
                key_index += 1
                logger.warning('Gemini key rejected or rate-limited for paraphrase; trying the next key')
            elif _is_transient(exc) and transient_retries < len(TRANSIENT_BACKOFF_SECONDS):
                time.sleep(TRANSIENT_BACKOFF_SECONDS[transient_retries])
                transient_retries += 1
                logger.warning('Gemini overloaded (%s); retry %d', type(exc).__name__, transient_retries)
            else:
                raise
    usage = response.usage_metadata
    return response.text or '', {
        'input_tokens': getattr(usage, 'prompt_token_count', None),
        'output_tokens': getattr(usage, 'candidates_token_count', None),
        'thinking_tokens': getattr(usage, 'thoughts_token_count', None),
    }


def _call_openai(model_name, system_prompt, user_prompt):
    from openai import OpenAI

    # The OpenAI SDK retries overloaded/rate-limited requests itself with backoff.
    client = OpenAI(api_key=os.getenv('CHATGPT_KEY'), timeout=REQUEST_TIMEOUT_SECONDS, max_retries=4)
    response = client.chat.completions.create(
        model=model_name,
        messages=[{'role': 'system', 'content': system_prompt}, {'role': 'user', 'content': user_prompt}],
    )
    usage = response.usage
    details = getattr(usage, 'completion_tokens_details', None)
    return response.choices[0].message.content or '', {
        'input_tokens': getattr(usage, 'prompt_tokens', None),
        'output_tokens': getattr(usage, 'completion_tokens', None),
        'thinking_tokens': getattr(details, 'reasoning_tokens', None),
    }


PROVIDERS = {'gemini': _call_gemini, 'openai': _call_openai}


# ---------------------------------------------------------------------------
# Running generations

def start_batch(book, chapter, models, instructions, word_guidance, include_glossary, prompt_name, username):
    """Create one row per (provider, model) and generate them all in parallel threads."""
    verses = chapter_verses(book, chapter)
    if not verses:
        raise ValueError(f'No verses found for {book} {chapter}.')
    source_text, media = prepare_source(verses)
    user_prompt = build_user_prompt(book, chapter, source_text, media)
    system_prompt = build_system_prompt(instructions, word_guidance, include_glossary)
    verse_numbers = [verse for verse, _ in verses]
    batch_id = uuid.uuid4()

    def start_threads():
        for row in rows:
            threading.Thread(
                target=run_generation, args=(row.pk, user_prompt, media, verse_numbers),
                name=f'paraphrase-{row.uid}', daemon=True,
            ).start()

    # The threads use their own DB connections, so the rows must be committed first.
    with transaction.atomic():
        rows = [
            ChapterParaphrase.objects.create(
                batch_id=batch_id, book=book, chapter=chapter, provider=provider, model_name=model_name,
                prompt_name=prompt_name, system_prompt=system_prompt, source_hash=source_hash(verses),
                created_by=username,
            )
            for provider, model_name in models
        ]
        transaction.on_commit(start_threads)
    return batch_id, rows


def run_generation(pk, user_prompt, media, verse_numbers):
    close_old_connections()
    started = time.monotonic()
    try:
        row = ChapterParaphrase.objects.get(pk=pk)
        ChapterParaphrase.objects.filter(pk=pk).update(status='running', started_at=timezone.now())
        raw, usage = PROVIDERS[row.provider](row.model_name, row.system_prompt, user_prompt)
        if not raw.strip():
            raise RuntimeError('The model returned no text.')
        html, missing = finalize_output(raw, media, verse_numbers)
        ChapterParaphrase.objects.filter(pk=pk).update(
            status='done', raw_output=raw, html=html, missing_verses=missing,
            duration_ms=int((time.monotonic() - started) * 1000), finished_at=timezone.now(), **usage,
        )
    except Exception as exc:
        logger.exception('Paraphrase generation %s failed', pk)
        ChapterParaphrase.objects.filter(pk=pk).update(
            status='failed', error=f'{type(exc).__name__}: {exc}'[:2000],
            duration_ms=int((time.monotonic() - started) * 1000), finished_at=timezone.now(),
        )
    finally:
        close_old_connections()


def expire_stale(book, chapter):
    """Fail generations whose thread died (worker restart, deploy) so they don't spin forever."""
    cutoff = timezone.now() - timedelta(seconds=STALE_AFTER_SECONDS)
    ChapterParaphrase.objects.filter(
        book=book, chapter=chapter, status__in=['pending', 'running'], created_at__lt=cutoff,
    ).update(status='failed', error='Interrupted: the server restarted before this finished. Generate again.', finished_at=timezone.now())


@transaction.atomic
def publish(uid):
    row = ChapterParaphrase.objects.select_for_update().get(uid=uid)
    if row.status != 'done':
        raise ValueError('Only finished paraphrases can be published.')
    ChapterParaphrase.objects.filter(
        book=row.book, chapter=row.chapter, language_code=row.language_code, is_published=True,
    ).exclude(pk=row.pk).update(is_published=False)
    row.is_published = True
    row.published_at = timezone.now()
    row.save(update_fields=['is_published', 'published_at', 'updated_at'])
    return row


def published_for(book, chapter, language_code='en'):
    return ChapterParaphrase.objects.filter(
        book=book, chapter=chapter, language_code=language_code, is_published=True,
    ).first()
