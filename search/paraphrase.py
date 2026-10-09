"""
AI chapter paraphrases: the "Paraphrase" reader view on NT chapter pages.

Staff generate a whole chapter as flowing, readable English with one or more models at
once (translate/paraphrase_api.py, driven by the Paraphrase Studio in chapter-editor/),
compare the results and publish one. Every generation is kept in ChapterParaphrase.

Pipeline for one generation:
  1. prepare_source(): the chapter's stored RBT verse HTML (new_testament.nt.rbt) is
     reduced to text plus the color/hayah spans worth keeping. Images, videos and
     tooltip blocks are pulled out as numbered media items with their captions; notes
     that quote verses are sent whole so those verses are paraphrased too.
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
     and list verses no data-v range covers. Verses quoted in notes are swapped for their
     paraphrases only where the model copied the passage exactly (apply_note_edits).
"""
import hashlib
import logging
import os
import re
import threading
import time
import uuid
from dataclasses import dataclass, replace as replace_dataclass
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

# Appended to every system prompt, whatever the preset: fidelity requirements staff
# shouldn't be able to edit away, and the format the reader page, the sanitiser and the
# coverage check depend on.
OUTPUT_RULES = """
FIDELITY (required):
- Preserve the text's deliberate features even where ordinary English would trim or vary them: repetitions ("and he spoke the same, and he did not deny, and he spoke the same" keeps both "he spoke the same"), parallel lines, wordplay and emphatic word order. Smooth the grammar around them, never away.
- Never drop or merge a clause, a repeated phrase, or a named person or place.

OUTPUT FORMAT (required; the page depends on it):
- Return only an HTML fragment. No markdown, no code fences, no <html>, <head>, <body>, <style> or <script>.
- Allowed elements: p, blockquote, ul, ol, li, em, strong, span, br, hr, rbt-media, and rbt-note after the chapter (below). No headings of any kind: the page flows as paragraphs.
- Put data-v on every paragraph, blockquote or list that carries verse content, giving the verse range it covers: <p data-v="3-5">...</p> or <p data-v="7">...</p>. Together the ranges must cover every verse of the chapter.
- Keep the RBT color coding where it still fits by reusing the source's spans exactly: <span style="color: blue;"> and <span style="color: #ff00aa;">. Keep <span class="hayah"> as it is.
- Optional classes: <p class="pp-indent"> for an indented paragraph, <blockquote class="pp-poetry"> for poetic or quoted lines (use <br> between lines).
- Mark every media item exactly once with an inline marker inside the paragraph, right after the sentence it best illustrates (after the sentence's closing punctuation): <rbt-media n="N"></rbt-media>. Readers see a small image cue there that opens the image and its notes, so the text itself stays uninterrupted; never put a marker between paragraphs.
- If the input has a NOTES section: after the chapter, paraphrase the Bible verses quoted in those notes the same way as the chapter, one block per quoted passage: <rbt-note n="N"><rbt-find>the passage exactly as it appears in note N's HTML, copied character for character with its tags</rbt-find><rbt-replace>its paraphrase</rbt-replace></rbt-note>. Only verse text: leave commentary, titles, definitions and references such as (Revelation 21:3 RBT) out of rbt-find. Keep the color spans where they still fit. Skip notes that quote no verses.
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
    'span': {'hayah', 'sun-icon'},  # sun-icon: the glowing sun behind a word (base.html)
}
# The only styles kept: the two RBT colors, 'color: blue;' and 'color: #ff00aa;'. Other
# spellings of them (the page's color toggles leave rgb() behind, models drop spaces) are
# rewritten to those.
COLOR_SPELLINGS = {
    'blue': 'color: blue;', '#00f': 'color: blue;', '#0000ff': 'color: blue;', 'rgb(0,0,255)': 'color: blue;',
    '#ff00aa': 'color: #ff00aa;', '#f0a': 'color: #ff00aa;', 'rgb(255,0,170)': 'color: #ff00aa;',
}
VERSE_RANGE = re.compile(r'^(\d+)(?:-(\d+))?$')

# Media notes worth sending whole, for the verses they quote: RBT color spans or a reference.
NOTE_VERSE_HINT = re.compile(r'color:\s*(?:blue|#ff00aa)|\b\d+:\d+\b|\bRBT\b', re.I)
NOTE_EDIT = re.compile(r'<rbt-note\s+n="(\d+)"\s*>(.*?)</rbt-note>', re.S | re.I)
NOTE_FIND = re.compile(r'<rbt-find>(.*?)</rbt-find>', re.S | re.I)
NOTE_REPLACE = re.compile(r'<rbt-replace>(.*?)</rbt-replace>', re.S | re.I)
# A shorter passage could match the wrong words.
MIN_NOTE_FIND_CHARS = 12


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


def _color_style(value):
    """The canonical RBT color style for a style attribute that only sets one, else None."""
    match = re.fullmatch(r'\s*color\s*:\s*([^;]+?)\s*;?\s*', value or '', re.I)
    return COLOR_SPELLINGS.get(re.sub(r'\s+', '', match.group(1).lower())) if match else None


def _keep_source_attr(tag, attr, value):
    if attr == 'style':
        return _color_style(value)
    if attr == 'class':
        return 'hayah' if 'hayah' in value.split() else None
    return value


def media_item(el, n, verse=''):
    """A Media item for a tooltip block or a bare image/video element."""
    caption_el = el.select_one('.tooltip, .tooltip2') if el.name == 'div' else None
    caption = ' '.join((caption_el.get_text(' ', strip=True) if caption_el else el.get('alt', '')).split())
    heading = caption_el.find(['b', 'strong']) if caption_el else None
    title = ' '.join(heading.get_text(' ', strip=True).split()) if heading else re.split(r'(?<=[.!?])\s', caption, 1)[0]
    kind = 'video' if (el.name == 'video' or el.find('video')) else 'image'
    return Media(n=n, verse=verse, html=str(el), kind=kind, caption=caption[:400], title=title.strip(' .:')[:90])


def prepare_source(verses):
    """Model input text for the chapter, and the media items pulled out of it."""
    media = []
    lines = []
    for verse, html in verses:
        soup = BeautifulSoup(html, 'html.parser')
        containers = soup.select('.tooltip-container')
        loose = [el for el in soup.find_all(['img', 'video']) if not el.find_parent(class_='tooltip-container')]
        for el in containers + loose:
            media.append(media_item(el, len(media) + 1, verse))
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
        notes = [(item.n, note) for item in media if (note := prompt_note(item))]
        if notes:
            parts += ['', 'NOTES (the notes shown with media items; paraphrase the verses they quote with rbt-note blocks):']
            for n, note in notes:
                parts += [f'NOTE {n}:', note]
    else:
        parts += ['', 'MEDIA: none']
    return '\n'.join(parts)


def _canonical(html):
    """HTML as BeautifulSoup writes it, whitespace runs collapsed: the form notes are
    shown to the model in and the form its copied passages are matched in."""
    return ' '.join(str(BeautifulSoup(html, 'html.parser')).split())


def _note_element(soup):
    return soup.select_one('.tooltip, .tooltip2')


def prompt_note(item):
    """The note's HTML for the prompt, or '' when it quotes no verses."""
    note = _note_element(BeautifulSoup(item.html, 'html.parser'))
    if note is None:
        return ''
    html = _canonical(note.decode_contents())
    return html if NOTE_VERSE_HINT.search(html) else ''


def extract_note_edits(raw):
    """(raw without the rbt-note blocks, [(n, find, replace)]) from model output."""
    edits = []
    for match in NOTE_EDIT.finditer(raw):
        find, replace = NOTE_FIND.search(match.group(2)), NOTE_REPLACE.search(match.group(2))
        if find and replace:
            edits.append((int(match.group(1)), _canonical(find.group(1)), replace.group(1)))
    return NOTE_EDIT.sub('', raw), edits


def apply_note_edits(media, edits):
    """Media with the quoted verses in their notes replaced by the model's paraphrases.
    A passage is replaced only where it matches the note exactly (once), so commentary,
    titles and images can't be altered; the rest are skipped and logged."""
    by_n = {item.n: item for item in media}
    updated = {}
    for n, find, replace in edits:
        item = updated.get(n) or by_n.get(n)
        if item is None or len(BeautifulSoup(find, 'html.parser').get_text().strip()) < MIN_NOTE_FIND_CHARS or re.search(r'<(img|video|iframe)\b', find):
            logger.info('[PARAPHRASE] note edit for media %s skipped', n)
            continue
        soup = BeautifulSoup(item.html, 'html.parser')
        note = _note_element(soup)
        current = _canonical(note.decode_contents()) if note is not None else ''
        if find not in current:
            logger.info('[PARAPHRASE] note edit for media %s did not match the note', n)
            continue
        clean = nh3.clean(
            replace, tags={'span', 'em', 'strong', 'b', 'i', 'br'}, attributes={'span': {'style', 'class'}},
            attribute_filter=_keep_source_attr, strip_comments=True, link_rel=None,
            clean_content_tags={'script', 'style'},
        )
        note.clear()
        note.append(BeautifulSoup(current.replace(find, clean, 1), 'html.parser'))
        updated[n] = replace_dataclass(item, html=str(soup))
    return [updated.get(item.n, item) for item in media]


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
        return _color_style(value)
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


def _add_anchors(soup, block):
    """Anchors so /john/1/#v12 links land on the paragraph holding verse 12."""
    for verse in reversed(verse_range(block.get('data-v', ''))):
        if not soup.find(id=f'v{verse}'):
            block.insert(0, soup.new_tag('span', attrs={'id': f'v{verse}', 'class': 'pp-anchor'}))


def _attach_cue(block, cue):
    """Put a cue at the end of a block's text (before any trailing whitespace)."""
    block.append(' ')
    block.append(cue)


def finalize_output(raw, media, verse_numbers):
    """Sanitised reader HTML and the list of verses no data-v range covers."""
    raw, note_edits = extract_note_edits(_strip_fences(raw))
    media = apply_note_edits(media, note_edits)
    clean = nh3.clean(
        raw,
        tags=ALLOWED_TAGS,
        attributes=ALLOWED_ATTRIBUTES,
        attribute_filter=_keep_output_attr,
        strip_comments=True,
        link_rel=None,
        # Headings are dropped with their text: the paraphrase flows as paragraphs. A
        # malformed rbt-note block goes too rather than leaking into the chapter.
        clean_content_tags={'script', 'style', 'h1', 'h2', 'h3', 'h4', 'h5', 'h6', 'rbt-note'},
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
        covered.update(verse_range(block['data-v']))
        _add_anchors(soup, block)

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
# Editing a paraphrase in place

EDITABLE_BLOCKS = ('p', 'blockquote')


def html_hash(html):
    return hashlib.sha1((html or '').encode('utf-8')).hexdigest()


def editable_blocks(soup):
    """Top-level paragraphs and quotes, in order; the reader page indexes them the same way."""
    return [node for node in soup.children if getattr(node, 'name', None) in EDITABLE_BLOCKS]


def stored_media(soup):
    """{n: Media} from the paraphrase's inert template store."""
    media = {}
    for template in soup.select('.pp-media-store template[data-media]'):
        element = BeautifulSoup(template.decode_contents(), 'html.parser').find(True)
        n = template['data-media']
        if element is not None and n.isdigit():
            media[int(n)] = media_item(element, int(n))
    return media


def _clean_edit(soup, edit_html):
    """Inline HTML typed in the editor, sanitised like model output, with image cues rebuilt
    from the stored media (so an edit can't alter them) and verse anchors dropped."""
    edit = BeautifulSoup(edit_html, 'html.parser')
    # A word colored while the page's Blue/Magenta toggle hid it: style is "color: inherit".
    for span in edit.select('span[data-orig-color-magenta], span[data-orig-color-blue]'):
        span['style'] = 'color: #ff00aa;' if span.has_attr('data-orig-color-magenta') else 'color: blue;'
    for cue in edit.select('button.pp-cue'):
        n = cue.get('data-media', '')
        cue.replace_with(edit.new_tag('rbt-media', attrs={'n': n}) if n.isdigit() else '')
    for anchor in edit.select('span.pp-anchor'):
        anchor.decompose()
    clean = BeautifulSoup(nh3.clean(
        str(edit), tags=ALLOWED_TAGS, attributes=ALLOWED_ATTRIBUTES, attribute_filter=_keep_output_attr,
        strip_comments=True, link_rel=None, clean_content_tags={'script', 'style'},
    ), 'html.parser')
    media = stored_media(soup)
    for placeholder in clean.find_all('rbt-media'):
        item = media.get(int(placeholder.get('n') or 0))
        placeholder.replace_with(_cue(clean, item) if item else '')
    return list(clean.contents)


def _heading_before(block):
    """The <h5> directly above a paragraph, if it has one."""
    previous = block.previous_sibling
    while isinstance(previous, str) and not previous.strip():
        previous = previous.previous_sibling
    return previous if getattr(previous, 'name', None) == 'h5' else None


def _leading_heading(edit_html):
    """(heading inner HTML or None, the rest): an edit may open with <h5>, the paragraph's heading."""
    edit = BeautifulSoup(edit_html, 'html.parser')
    first = next((node for node in edit.contents if not (isinstance(node, str) and not node.strip())), None)
    if getattr(first, 'name', None) != 'h5':
        return None, edit_html
    heading = first.extract()
    return heading.decode_contents(), str(edit)


def editor_html(block):
    """A paragraph as the inline editor edits it: its heading (if any), then its contents."""
    heading = _heading_before(block)
    return (str(heading) if heading else '') + block.decode_contents()


def _set_heading(soup, block, heading_html):
    """Give `block` the heading heading_html (sanitised) above it, or none if that's empty."""
    heading = _heading_before(block)
    contents = _clean_edit(soup, heading_html) if heading_html is not None else []
    if ''.join(node.get_text() if hasattr(node, 'get_text') else str(node) for node in contents).strip():
        if heading is None:
            heading = soup.new_tag('h5')
            block.insert_before(heading)
        heading.clear()
        for node in contents:
            heading.append(node)
    elif heading is not None:
        heading.decompose()


def replace_block(html, index, new_inner_html):
    """The paraphrase HTML with block `index`'s contents replaced by an edit, and the block
    as the editor now sees it (editor_html). The edit is sanitised like model output; image
    cues in it are rebuilt from the stored media and verse anchors are re-added. A leading
    <h5> in the edit sets the heading above the paragraph; without one (or with an empty
    one) the paragraph has no heading. (The form editors before replace_blocks sent.)"""
    soup = BeautifulSoup(html, 'html.parser')
    blocks = editable_blocks(soup)
    if not 0 <= index < len(blocks):
        raise IndexError(f'No paragraph {index}.')
    block = blocks[index]
    heading_html, body_html = _leading_heading(new_inner_html)

    block.clear()
    for node in _clean_edit(soup, body_html):
        block.append(node)
    _add_anchors(soup, block)
    _set_heading(soup, block, heading_html)
    return str(soup).strip(), editor_html(block)


def replace_blocks(html, index, count, unit_html):
    """
    Replace `count` consecutive paragraphs/quotes from `index` (and the heading above the
    first) with an edited unit: an optional <h5>, then one or more <p>/<blockquote> blocks,
    so an edit can turn a paragraph into a quote or split part of it out. Blocks keep their
    allowed classes and data-v (a block without a valid one takes the first replaced
    block's); loose inline content becomes a paragraph. Returns the new HTML, the unit as
    the editor now sees it (heading + blocks), and how many blocks it has.
    """
    soup = BeautifulSoup(html, 'html.parser')
    blocks = editable_blocks(soup)
    if count < 1 or not 0 <= index or index + count > len(blocks):
        raise IndexError(f'No paragraphs {index}-{index + count - 1}.')
    old = blocks[index:index + count]
    default_v = old[0].get('data-v', '')
    heading_html, body_html = _leading_heading(unit_html)

    new_blocks = []
    loose = []

    def add(tag, classes, data_v, inner, keep_empty=False):
        block = soup.new_tag(tag)
        kept = [c for c in (classes or []) if c in ALLOWED_CLASSES.get(tag, ())]
        if kept:
            block['class'] = ' '.join(kept)
        data_v = (data_v or '').strip()
        data_v = data_v if VERSE_RANGE.match(data_v) else default_v
        if data_v:
            block['data-v'] = data_v
        for node in _clean_edit(soup, inner):
            block.append(node)
        # A piece left with no text (only spaces or line breaks) after a split is dropped.
        if keep_empty or block.get_text().strip() or block.find('button'):
            new_blocks.append(block)

    def flush_loose():
        if ''.join(str(node) for node in loose).strip():
            add('p', None, '', ''.join(str(node) for node in loose))
        loose.clear()

    for node in list(BeautifulSoup(body_html, 'html.parser').contents):
        if getattr(node, 'name', None) in EDITABLE_BLOCKS:
            flush_loose()
            add(node.name, node.get('class'), node.get('data-v'), node.decode_contents())
        else:
            loose.append(node)
    flush_loose()
    if not new_blocks:
        add('p', None, '', '', keep_empty=True)

    heading = _heading_before(old[0])
    if heading is not None:
        heading.decompose()
    for block in new_blocks:
        old[0].insert_before(block)
    for block in old:
        block.decompose()
    for block in new_blocks:
        _add_anchors(soup, block)
    _set_heading(soup, new_blocks[0], heading_html)
    heading = _heading_before(new_blocks[0])
    unit = (str(heading) if heading else '') + ''.join(str(block) for block in new_blocks)
    return str(soup).strip(), unit, len(new_blocks)


# Notes are staff-written verse HTML (images, lists, centred lines), so an edited note keeps
# that markup; scripts, event handlers and unknown elements are removed.
NOTE_TAGS = {
    'a', 'b', 'big', 'blockquote', 'br', 'center', 'code', 'div', 'em', 'font', 'h3', 'h4', 'h5', 'h6', 'hr',
    'i', 'img', 'li', 'mark', 'ol', 'p', 'q', 's', 'small', 'source', 'span', 'strong', 'sub', 'sup',
    'table', 'tbody', 'td', 'th', 'thead', 'tr', 'u', 'ul', 'video',
}
NOTE_ATTRIBUTES = {
    '*': {'class', 'style', 'title'},
    'a': {'href', 'target'},
    'font': {'color', 'size'},
    'img': {'src', 'alt', 'width', 'height', 'loading'},
    'video': {'src', 'controls', 'width', 'height', 'poster', 'autoplay', 'loop', 'muted', 'playsinline'},
    'source': {'src', 'type'},
    'td': {'colspan', 'rowspan'},
    'th': {'colspan', 'rowspan'},
}


def replace_note(html, n, new_html):
    """The paraphrase HTML with media item `n`'s notes replaced by an edit, and the new notes."""
    soup = BeautifulSoup(html, 'html.parser')
    template = soup.select_one(f'.pp-media-store template[data-media="{int(n)}"]')
    note = _note_element(template) if template is not None else None
    if note is None:
        raise LookupError(f'Media {n} has no notes.')
    clean = nh3.clean(
        new_html, tags=NOTE_TAGS, attributes=NOTE_ATTRIBUTES, strip_comments=True, link_rel=None,
        clean_content_tags={'script', 'style'},
    )
    note.clear()
    note.append(BeautifulSoup(clean, 'html.parser'))
    return str(soup).strip(), note.decode_contents()


# ---------------------------------------------------------------------------
# Providers

def _gemini_key():
    """GEMINI_API_KEY only; the GEMINI_API_KEYS pool is left to the page translator."""
    return os.getenv('GEMINI_API_KEY', '').strip()


# Waits before retrying when the model is overloaded (503 "high demand" and similar).
TRANSIENT_BACKOFF_SECONDS = (10, 30, 60)


def _is_transient(exc):
    text = str(exc)
    return any(marker in text for marker in ('503', 'UNAVAILABLE', '500 INTERNAL', 'DEADLINE_EXCEEDED', 'overloaded', 'high demand'))


def _call_gemini(model_name, system_prompt, user_prompt):
    from google import genai
    from google.genai import types
    from translate.views import get_ipv4_transport

    api_key = _gemini_key()
    if not api_key:
        raise RuntimeError('No Gemini API key is configured (GEMINI_API_KEY).')
    client = genai.Client(
        api_key=api_key,
        http_options=types.HttpOptions(
            timeout=REQUEST_TIMEOUT_SECONDS * 1000,
            client_args={'transport': get_ipv4_transport()},
        ),
    )
    # Wait and retry when the model is overloaded.
    transient_retries = 0
    while True:
        try:
            response = client.models.generate_content(
                model=model_name,
                contents=user_prompt,
                config=types.GenerateContentConfig(system_instruction=system_prompt),
            )
            break
        except Exception as exc:
            if _is_transient(exc) and transient_retries < len(TRANSIENT_BACKOFF_SECONDS):
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
