"""
Normalise NT footnote HTML into one clean, consistent form.

Footnotes were written over years with different tools (TinyMCE, the add-footnote form,
copy-paste from Word, ChatGPT, Gemini, Logeion, a browser translation extension), so the
same kinds of content are marked up in many ways. This module turns any footnote into:

- block content as <p>, <ul>/<ol>/<li>, <h4>/<h5>, <blockquote>, <table>, <img>
  (no loose top-level text, no layout <div>s, no empty paragraphs);
- an optional heading as <p><span class="footnote_header">…</span></p>;
- <strong>/<em> for bold and italic, <a> links, <br> only inside a paragraph;
- Hebrew and Greek words marked <span class="hebrew"> / <span class="greek"> instead of
  inline font sizes and families, so pages style them consistently;
- no per-element "rbt_footnote" classes: pages style footnote text by where it is shown.

Inline formatting that carries meaning is kept: colour, indentation (padding-left),
small caps, alignment, links, tables and images. Rendered maths (KaTeX) is left untouched
and flagged for review. Nothing changes the wording: normalize() reports whether the
visible text differs (it should not) so a caller can refuse such changes.
"""
import functools
import re
import warnings
from dataclasses import dataclass, field

from bs4 import BeautifulSoup, Comment, MarkupResemblesLocatorWarning, NavigableString, Tag

# A one-line note that happens to look like a URL or file name is still a note.
warnings.filterwarnings('ignore', category=MarkupResemblesLocatorWarning)

# Classes with a meaning on the site; every other class is dropped.
KEEP_CLASSES = {
    'footnote_header', 'hebrew', 'greek', 'hayah', 'sun-icon', 'poetry-indent', 'last_center',
    'tooltip-container', 'tooltip', 'tooltip2', 'touch-indicator', 'sdfootnoteanc',
    'hebrew-header', 'greek-header',
}
RENAME_CLASSES = {'hebrew_footnote': 'hebrew', 'greek2': 'greek'}

# Inline style properties with a meaning; the rest (fonts, sizes, spacing, positioning,
# backgrounds pasted from other pages) are dropped.
KEEP_STYLE = {'color', 'text-align', 'padding-left', 'font-style', 'font-weight', 'font-variant',
              'text-decoration', 'vertical-align', 'list-style-type'}
KEEP_STYLE_SIZED = {'width', 'height', 'border', 'border-collapse', 'border-width', 'border-style',
                    'border-color', 'text-align', 'vertical-align', 'color', 'padding-left'}
SIZED_TAGS = {'img', 'table', 'td', 'th', 'col', 'video', 'iframe'}

KEEP_ATTRS = {'class', 'style', 'href', 'target', 'rel', 'title', 'src', 'alt', 'width', 'height',
              'colspan', 'rowspan', 'lang', 'start', 'type', 'controls', 'autoplay', 'muted',
              'loop', 'playsinline', 'allowfullscreen', 'frameborder'}

BLOCK_TAGS = {'p', 'ul', 'ol', 'li', 'h1', 'h2', 'h3', 'h4', 'h5', 'h6', 'blockquote', 'table',
              'thead', 'tbody', 'tfoot', 'tr', 'td', 'th', 'div', 'section', 'hr', 'figure',
              'center', 'pre'}
TOP_BLOCKS = {'p', 'ul', 'ol', 'h1', 'h2', 'h3', 'h4', 'h5', 'h6', 'blockquote', 'table', 'hr',
              'figure', 'pre', 'img', 'video', 'iframe'}
MEDIA_TAGS = {'img', 'video', 'iframe', 'audio', 'source', 'hr'}

ICON_CLASS_RE = re.compile(r'^fa[srbl]?$|^fa-')  # Font Awesome icons (e.g. the touch hint on images)
HEBREW_RE = re.compile('[\u0590-\u05FF]')
GREEK_RE = re.compile('[\u0370-\u03FF\u1F00-\u1FFF]')
LATIN_RE = re.compile('[A-Za-z]')


@dataclass
class Result:
    html: str
    changes: list = field(default_factory=list)  # human-readable, one entry per kind
    text_changed: bool = False                    # visible wording differs: do not apply blindly
    review: list = field(default_factory=list)    # things a person should look at

    @property
    def changed(self):
        return bool(self.changes)


def _is_junk(tag):
    """Markup a browser extension injected into the page while the note was being edited."""
    if not isinstance(tag, Tag):
        return False
    if (tag.get('id') or '').startswith('simple-translate'):
        return True
    return any(cls.startswith('simple-translate') for cls in tag.get('class', []))


def visible_text(html):
    """The words a reader sees, whitespace collapsed (junk the editor never showed excluded)."""
    soup = BeautifulSoup(html or '', 'html.parser')
    for el in soup.find_all(_is_junk):
        el.decompose()
    for el in soup.find_all(['script', 'style']):
        el.decompose()
    for c in soup.find_all(string=lambda s: isinstance(s, Comment)):
        c.extract()
    return re.sub(r'\s+', ' ', soup.get_text(' ').replace('\xa0', ' ')).strip()


def _letters(html):
    """visible_text without any whitespace: what wording comparisons use (tag boundaries and
    spacing are not wording)."""
    return re.sub(r'\s+', '', visible_text(html))


def _has_content(tag):
    if tag.find(MEDIA_TAGS):
        return True
    return bool(tag.get_text().replace('\xa0', ' ').strip())


def _style_dict(style):
    out = {}
    for decl in (style or '').split(';'):
        if ':' in decl:
            key, _, value = decl.partition(':')
            key, value = key.strip().lower(), value.strip()
            if key and value:
                out[key] = value
    return out


def _style_str(d):
    return '; '.join(f'{k}: {v}' for k, v in d.items()) + (';' if d else '')


def _script_class(text):
    if HEBREW_RE.search(text) and not LATIN_RE.search(text):
        return 'hebrew'
    if GREEK_RE.search(text) and not HEBREW_RE.search(text) and len(LATIN_RE.findall(text)) <= 2:
        return 'greek'
    return None


def normalize(html):
    """Normalise one footnote. Returns a Result; Result.html is unchanged when nothing applies."""
    original = html or ''
    soup = BeautifulSoup(original, 'html.parser')
    changes = {}

    def note(kind, n=1):
        changes[kind] = changes.get(kind, 0) + n

    review = []

    # Rendered maths: leave its markup alone (it renders from its own spans). Tracked by
    # id(): a bs4 Tag hashes by serialising itself, which made set lookups quadratic.
    protected = set()
    for el in soup.find_all(class_=re.compile(r'^katex')):
        if not any(id(p) in protected for p in el.parents):
            protected.add(id(el))
    if protected:
        review.append('contains rendered maths (KaTeX); its markup was left as is')

    def is_protected(el):
        if not protected or el is None:
            return False
        return id(el) in protected or any(id(p) in protected for p in el.parents)

    # 1. Junk: browser-extension pop-ups, comments, Word's <o:p>, scripts.
    for el in soup.find_all(_is_junk):
        el.decompose()
        note('removed a browser translation pop-up pasted into the note')
    for c in soup.find_all(string=lambda s: isinstance(s, Comment)):
        c.extract()
        note('removed HTML comments')
    for el in soup.find_all(['script', 'style', 'meta', 'link']):
        el.decompose()
        note('removed scripts/styles')
    for el in soup.find_all(lambda t: isinstance(t, Tag) and ':' in t.name):
        el.unwrap()
        note('removed Word markup')

    # 2. Tags: <b>/<i> → <strong>/<em>; <font> unwrapped.
    for el in soup.find_all(['b', 'i']):
        if is_protected(el) or any(c.startswith('fa') for c in el.get('class', [])):
            continue
        el.name = 'strong' if el.name == 'b' else 'em'
        note('<b>/<i> → <strong>/<em>')
    for el in soup.find_all('font'):
        el.unwrap()
        note('removed <font> tags')

    # 3. Attributes, classes and inline styles.
    for el in soup.find_all(True):
        if is_protected(el):
            continue
        for attr in list(el.attrs):
            if attr not in KEEP_ATTRS:
                del el[attr]
                note('removed editor/paste attributes (data-*, id, dir…)')
        classes = el.get('class', [])
        if classes:
            kept = []
            for cls in classes:
                cls = RENAME_CLASSES.get(cls, cls)
                if (cls in KEEP_CLASSES or ICON_CLASS_RE.match(cls)) and cls not in kept:
                    kept.append(cls)
            if 'rbt_footnote' in classes:
                note('removed rbt_footnote classes')
            if [c for c in classes if c != 'rbt_footnote' and RENAME_CLASSES.get(c, c) not in KEEP_CLASSES and not ICON_CLASS_RE.match(c)]:
                note('removed classes pasted from other sites')
            if [c for c in classes if c in RENAME_CLASSES]:
                note('hebrew_footnote/greek2 → hebrew/greek')
            if kept:
                el['class'] = kept
            else:
                del el['class']
        if el.get('style') is not None:
            style = _style_dict(el['style'])
            keep = KEEP_STYLE_SIZED if el.name in SIZED_TAGS else KEEP_STYLE
            # A Hebrew or Greek word set in its own size or font becomes a hebrew/greek span.
            if el.name == 'span' and ({'font-size', 'font-family'} & set(style)):
                script = _script_class(el.get_text())
                if script and script not in el.get('class', []):
                    el['class'] = el.get('class', []) + [script]
                    note(f'sized/fonted {script} words → class "{script}"')
            dropped = [k for k in style if k not in keep]
            if dropped:
                note('removed pasted fonts, sizes and layout styles')
                style = {k: v for k, v in style.items() if k in keep}
            if style.get('font-variant', '').lower() == 'normal':
                style.pop('font-variant')
            if style:
                el['style'] = _style_str(style)
            else:
                del el['style']

    # 4. Unwrap spans that no longer carry anything (e.g. the old <span class="rbt_footnote">).
    for el in soup.find_all('span'):
        if not is_protected(el) and not el.attrs:
            el.unwrap()
            note('unwrapped empty <span>s')

    # 5. Layout <div>/<section>: a box of inline content becomes a paragraph, otherwise unwrap.
    for el in soup.find_all(['div', 'section', 'center', 'article']):
        if is_protected(el) or 'tooltip-container' in el.get('class', []) or 'tooltip' in el.get('class', []) \
                or 'tooltip2' in el.get('class', []) or 'sun-icon' in el.get('class', []):
            continue
        if el.find(BLOCK_TAGS - {'div', 'section', 'center', 'article'}) or el.find(['div', 'section']):
            el.unwrap()
        else:
            el.name = 'p'
        note('replaced layout <div>s')

    # 6. A list item holding a single paragraph: just the item (consistent list spacing).
    for li in soup.find_all('li'):
        kids = [k for k in li.contents if not (isinstance(k, NavigableString) and not k.strip())]
        if len(kids) == 1 and isinstance(kids[0], Tag) and kids[0].name == 'p' and not kids[0].attrs:
            kids[0].unwrap()
            note('unwrapped paragraphs inside list items')

    # 7. Paragraphs split at a double line break; trailing line breaks dropped.
    for p in list(soup.find_all('p')):
        if is_protected(p):
            continue
        parts, current, run = [], [], []
        for child in list(p.contents):
            if isinstance(child, Tag) and child.name == 'br':
                run.append(child)
                continue
            if isinstance(child, NavigableString) and not child.strip() and run:
                run.append(child)
                continue
            brs = [r for r in run if isinstance(r, Tag)]
            if len(brs) >= 2:
                parts.append(current)
                current = []
            else:
                current.extend(run)
            run = []
            current.append(child)
        parts.append(current)  # trailing <br>s (in `run`) are dropped
        if any(isinstance(r, Tag) for r in run):
            note('removed trailing line breaks')
        if len(parts) > 1:
            note('split paragraphs at double line breaks')
            for i, nodes in enumerate(parts):
                new_p = soup.new_tag('p', attrs=dict(p.attrs))
                for n in nodes:
                    new_p.append(n.extract())
                p.insert_before(new_p)
            p.decompose()
        elif run:
            for r in run:
                r.extract()

    # 7b. A line break ending a block, however deep (e.g. inside the heading span), shows nothing.
    for block in soup.find_all(['p', 'li', 'h1', 'h2', 'h3', 'h4', 'h5', 'h6', 'td', 'th']):
        if is_protected(block):
            continue
        while True:
            last = None
            for node in reversed(list(block.descendants)):
                if isinstance(node, NavigableString) and not isinstance(node, Comment):
                    if node.strip():
                        break
                    continue
                if isinstance(node, Tag) and node.name == 'br':
                    last = node
                    break
                if isinstance(node, Tag) and (node.name in MEDIA_TAGS):
                    break
            if last is None:
                break
            last.decompose()
            note('removed trailing line breaks')

    # 8. Empty headings, paragraphs and list items.
    for el in soup.find_all(['p', 'li', 'h1', 'h2', 'h3', 'h4', 'h5', 'h6', 'strong', 'em', 'span', 'blockquote']):
        if el.parent is None or is_protected(el):
            continue
        if not _has_content(el) and not el.find('br'):
            header = el.find('span', class_='footnote_header') or 'footnote_header' in el.get('class', [])
            el.decompose()
            note('removed empty headers' if header else 'removed empty paragraphs')
    for el in soup.find_all(['ul', 'ol']):
        if not el.find('li'):
            el.decompose()
            note('removed empty paragraphs')

    # 9. Loose top-level inline content goes into paragraphs.
    run = []

    def flush():
        if any((isinstance(n, NavigableString) and n.strip()) or isinstance(n, Tag) for n in run):
            if any((isinstance(n, NavigableString) and n.strip()) or (isinstance(n, Tag) and n.name != 'br') for n in run):
                p = soup.new_tag('p')
                run[0].insert_before(p)
                for n in run:
                    p.append(n.extract())
                note('wrapped loose text in paragraphs')
            else:
                for n in run:
                    n.extract()
        run.clear()

    for node in list(soup.contents):
        if isinstance(node, Tag) and (node.name in TOP_BLOCKS or node.name in BLOCK_TAGS or 'tooltip-container' in node.get('class', [])):
            flush()
        elif isinstance(node, NavigableString) and not node.strip():
            if run:
                run.append(node)
        else:
            run.append(node)
    flush()

    # 10. Spacing: runs of spaces/non-breaking spaces collapse; blocks are trimmed.
    soup.smooth()  # unwrapped spans leave neighbouring text in separate fragments
    # Whitespace directly inside list/table containers never shows; dropping it all at once
    # keeps a single pass final (trimming items one level at a time exposed more of it).
    for container in soup.find_all(['ul', 'ol', 'table', 'thead', 'tbody', 'tfoot', 'tr']):
        if is_protected(container):
            continue
        for child in list(container.children):
            if isinstance(child, NavigableString) and not isinstance(child, Comment) and not child.strip():
                child.extract()
    nbsp_fixed = 0
    for text in soup.find_all(string=True):
        if isinstance(text, Comment) or is_protected(text.parent) or text.parent.name in ('pre', 'code'):
            continue
        new = re.sub(r'[ \xa0\t]*\xa0[ \xa0\t]*', lambda m: '\xa0' if m.group(0) == '\xa0' else ' ', str(text))
        new = re.sub(r' {2,}', ' ', new)
        if new != str(text):
            text.replace_with(new)
            nbsp_fixed += 1
    for block in soup.find_all(['p', 'li', 'h4', 'h5', 'td', 'th']):
        if is_protected(block):
            continue
        # Trim from each end until real text: a fragment emptied by trimming exposes the next.
        for from_start in (True, False):
            texts = [t for t in block.find_all(string=True) if not isinstance(t, Comment) and str(t)]
            for t in (texts if from_start else reversed(texts)):
                value = str(t)
                stripped = value.lstrip(' \xa0\r\n\t') if from_start else value.rstrip(' \xa0\r\n\t')
                if stripped != value:
                    t.replace_with(stripped)
                    nbsp_fixed += 1
                if stripped:
                    break
    if nbsp_fixed:
        note('tidied spaces and non-breaking spaces', nbsp_fixed)

    # 11. One block per line.
    blocks = [str(n).strip() for n in soup.contents if not (isinstance(n, NavigableString) and not n.strip())]
    clean = '\n'.join(blocks)
    if clean.strip() == original.strip():
        return Result(html=original, changes=[], review=review)

    # Whitespace-only differences (line breaks between blocks) are not worth a write.
    if re.sub(r'\s+', '', clean) == re.sub(r'\s+', '', original) and not changes:
        return Result(html=original, changes=[], review=review)

    text_changed = _letters(original) != _letters(clean)
    if text_changed:
        review.append('the visible wording would change; check before applying')
    summary = [f'{k} ({n})' if n > 1 else k for k, n in changes.items()] or ['reformatted HTML']
    return Result(html=clean, changes=summary, text_changed=text_changed, review=review)


def normalize_html(html):
    """The normalised HTML only (for save paths)."""
    return normalize(html).html


@functools.lru_cache(maxsize=1024)
def normalize_cached(html):
    """normalize(), remembered per input (the clean-up page re-plans the same notes on every
    load). Bounded: the app container is short of memory. Callers must not modify the Result."""
    return normalize(html)
