/**
 * NT verse editor (/edit/?book=…&chapter=…&verse=…): the verse text and its footnotes,
 * edited in place. The interlinear above it is unchanged (static/interlinear-editor.js).
 *
 * - The verse: contenteditable with a toolbar, autosave and a conflict check (a verse
 *   changed elsewhere is never overwritten); Reset returns it to how it was on page load.
 * - Image blocks (.tooltip-container) show as compact rows; clicking one opens the image
 *   pop-up (URL and notes).
 * - Footnotes: every note the verse links to, edited in place with its own toolbar,
 *   autosave and Reset; "Clean up" puts a note in the one consistent form. "Add footnote"
 *   writes a note, numbers it for its place in the book and puts its marker at the caret.
 * - window.updateReader(html) loads an AI suggestion (the Gemini/ChatGPT scripts on the
 *   page call it); suggestions are never autosaved.
 */
(function () {
  'use strict';

  const root = document.getElementById('nve');
  if (!root) return;
  const api = root.dataset;
  const $ = (sel, ctx) => (ctx || document).querySelector(sel);
  const $$ = (sel, ctx) => Array.from((ctx || document).querySelectorAll(sel));

  // ------------------------------------------------------------------ utilities
  function csrf() {
    const input = document.querySelector('[name=csrfmiddlewaretoken]');
    if (input && input.value) return input.value;
    const m = document.cookie.match(/(^|;\s*)csrftoken=([^;]+)/);
    return m ? decodeURIComponent(m[2]) : '';
  }

  async function call(url, { method = 'GET', body, query } = {}) {
    if (query) url += (url.includes('?') ? '&' : '?') + new URLSearchParams(query).toString();
    const init = { method, headers: { 'X-CSRFToken': csrf(), 'X-Requested-With': 'XMLHttpRequest' }, credentials: 'same-origin' };
    if (body !== undefined) { init.headers['Content-Type'] = 'application/json'; init.body = JSON.stringify(body); }
    const response = await fetch(url, init);
    const text = await response.text();
    let data = null;
    try { data = text ? JSON.parse(text) : {}; } catch (e) { data = null; }
    if (!response.ok) {
      const err = new Error((data && data.error) || `Server error ${response.status}`);
      err.status = response.status; err.data = data;
      throw err;
    }
    if (data === null) throw new Error('The server did not answer with JSON.');
    return data;
  }

  const escapeHtml = (s) => String(s == null ? '' : s).replace(/[&<>"']/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));

  let toastTimer = null;
  function toast(message, isError) {
    const el = $('#nveToast');
    el.textContent = message;
    el.classList.toggle('is-error', !!isError);
    el.hidden = false;
    clearTimeout(toastTimer);
    toastTimer = setTimeout(() => { el.hidden = true; }, isError ? 5000 : 2800);
  }

  function debounce(fn, ms) {
    let t = null;
    const wrapped = (...args) => { clearTimeout(t); t = setTimeout(() => fn(...args), ms); };
    wrapped.cancel = () => clearTimeout(t);
    return wrapped;
  }

  // ------------------------------------------------------------------ selection + formatting
  const savedRanges = new WeakMap(); // editable → its last selection
  let activeEditable = null;

  document.addEventListener('selectionchange', () => {
    const sel = window.getSelection();
    if (!sel.rangeCount) return;
    const node = sel.anchorNode;
    const editable = node && (node.nodeType === 1 ? node : node.parentElement)?.closest('.nve-editable');
    if (editable) {
      savedRanges.set(editable, sel.getRangeAt(0).cloneRange());
      activeEditable = editable;
    }
  });

  function rangeIn(editor) {
    const sel = window.getSelection();
    if (sel.rangeCount) {
      const range = sel.getRangeAt(0);
      if (editor.contains(range.commonAncestorContainer)) return range;
    }
    const saved = savedRanges.get(editor);
    if (saved && editor.contains(saved.commonAncestorContainer)) return saved.cloneRange();
    return null;
  }

  function endRange(editor) {
    const range = document.createRange();
    range.selectNodeContents(editor);
    range.collapse(false);
    return range;
  }

  function remember(range) {
    const sel = window.getSelection(); sel.removeAllRanges(); sel.addRange(range);
    const node = range.commonAncestorContainer;
    const editable = (node.nodeType === 1 ? node : node.parentElement)?.closest('.nve-editable');
    if (editable) savedRanges.set(editable, range.cloneRange());
  }

  function selectContents(node) {
    const range = document.createRange();
    range.selectNodeContents(node);
    remember(range);
  }

  function matches(el, spec) {
    if (!el || el.nodeType !== 1 || el.tagName.toLowerCase() !== spec.tag) return false;
    if (spec.className && !el.classList.contains(spec.className)) return false;
    if (spec.style) return Object.keys(spec.style).every((k) => (el.style[k] || '').toLowerCase().replace(/\s/g, '') === String(spec.style[k]).toLowerCase().replace(/\s/g, ''));
    if (!spec.className && !spec.style && spec.tag === 'span') return !el.className && !el.getAttribute('style');
    return true;
  }

  function closestMatch(node, editor, spec) {
    let el = node.nodeType === 1 ? node : node.parentElement;
    while (el && el !== editor) {
      if (matches(el, spec)) return el;
      el = el.parentElement;
    }
    return null;
  }

  function unwrap(el) {
    const parent = el.parentNode;
    const first = el.firstChild, last = el.lastChild;
    while (el.firstChild) parent.insertBefore(el.firstChild, el);
    parent.removeChild(el);
    if (first && last) {
      const range = document.createRange();
      range.setStartBefore(first); range.setEndAfter(last);
      remember(range);
    }
  }

  function makeNode(spec) {
    const el = document.createElement(spec.tag);
    if (spec.className) el.className = spec.className;
    if (spec.style) Object.assign(el.style, spec.style);
    if (spec.attrs) Object.entries(spec.attrs).forEach(([k, v]) => el.setAttribute(k, v));
    return el;
  }

  /** Wrap the selection in `spec`, or unwrap a matching ancestor (toggle). */
  function toggleWrap(editor, spec) {
    const range = rangeIn(editor);
    if (!range) { toast('Click into the text first, then select the words to format.', true); return false; }
    const existing = closestMatch(range.commonAncestorContainer, editor, spec);
    if (existing) { unwrap(existing); return true; }
    if (range.collapsed) { toast('Select some text first.', true); return false; }
    const wrapper = makeNode(spec);
    try {
      wrapper.appendChild(range.extractContents());
      range.insertNode(wrapper);
    } catch (err) {
      toast('That selection cannot be wrapped as one piece. Try a smaller selection.', true);
      return false;
    }
    selectContents(wrapper);
    return true;
  }

  /** Remove the nearest formatting element around the selection (keeps its text). */
  function clearFormatting(editor) {
    const range = rangeIn(editor);
    if (!range) { toast('Click into the text first.', true); return false; }
    const FORMAT = /^(strong|b|em|i|span|h5|a|u|font)$/i;
    let el = range.commonAncestorContainer;
    el = el.nodeType === 1 ? el : el.parentElement;
    while (el && el !== editor && !FORMAT.test(el.tagName)) el = el.parentElement;
    if (!el || el === editor) {
      if (range.collapsed) { toast('Nothing to clear here.', true); return false; }
      const frag = range.extractContents();
      range.insertNode(document.createTextNode(frag.textContent));
      return true;
    }
    unwrap(el);
    return true;
  }

  function insertHtml(editor, html, range) {
    range = range || rangeIn(editor) || endRange(editor);
    range.deleteContents();
    const tpl = document.createElement('template');
    tpl.innerHTML = html;
    const nodes = Array.from(tpl.content.childNodes);
    range.insertNode(tpl.content);
    const last = nodes[nodes.length - 1];
    if (last) {
      const after = document.createRange();
      after.setStartAfter(last); after.collapse(true);
      remember(after);
      nodes.filter((n) => n.nodeType === 1).forEach((n) => { n.classList.add('nve-flash'); setTimeout(() => n.classList.remove('nve-flash'), 900); });
    }
  }

  // ------------------------------------------------------------------ paragraphs: align, indent
  // Paragraph-level formatting for footnotes and image notes. A line of loose text (straight
  // inside the editor, ended by a <br>) first becomes a <p>, so it can carry the style.
  const BLOCK_SEL = 'p, li, h1, h2, h3, h4, h5, h6, blockquote, div';
  const INDENT_EM = 2;
  const MAX_INDENT_EM = 8;

  function isBlock(node) { return node.nodeType === 1 && /^(P|LI|H[1-6]|BLOCKQUOTE|DIV|UL|OL|TABLE)$/.test(node.tagName); }

  function blockFor(node, editor) {
    let el = node.nodeType === 1 ? node : node.parentElement;
    while (el && el !== editor) {
      if (el.matches(BLOCK_SEL) && !el.matches('.tooltip-container, .tooltip, .tooltip2')) return el;
      el = el.parentElement;
    }
    return null;
  }

  function wrapLine(node, editor) {
    let top = node;
    while (top.parentNode !== editor) top = top.parentNode;
    let first = top, last = top;
    while (first.previousSibling && !isBlock(first.previousSibling) && first.previousSibling.nodeName !== 'BR') first = first.previousSibling;
    while (last.nextSibling && !isBlock(last.nextSibling) && last.nextSibling.nodeName !== 'BR') last = last.nextSibling;
    const p = document.createElement('p');
    editor.insertBefore(p, first);
    for (let n = first; n;) {
      const next = n === last ? null : n.nextSibling;
      p.appendChild(n);
      n = next;
    }
    if (p.nextSibling && p.nextSibling.nodeName === 'BR') p.nextSibling.remove();
    return p;
  }

  /** The paragraphs, list items and headings the selection touches, in order. */
  function selectedBlocks(editor) {
    const range = rangeIn(editor);
    if (!range) { toast('Click into the text first.', true); return []; }
    const saved = [range.startContainer, range.startOffset, range.endContainer, range.endOffset];
    const nodes = [];
    const walker = document.createTreeWalker(editor, NodeFilter.SHOW_TEXT);
    for (let t = walker.nextNode(); t; t = walker.nextNode()) {
      if (range.intersectsNode(t) && (t.textContent.trim() || blockFor(t, editor))) nodes.push(t);
    }
    if (!nodes.length) {
      const c = range.startContainer;
      const at = c.nodeType === 1 ? (c.childNodes[range.startOffset] || c) : c;
      if (at !== editor && editor.contains(at)) nodes.push(at);
    }
    const blocks = [];
    nodes.forEach((n) => {
      const block = blockFor(n, editor) || wrapLine(n, editor);
      if (!blocks.includes(block)) blocks.push(block);
    });
    try {
      const r = document.createRange();
      r.setStart(saved[0], saved[1]); r.setEnd(saved[2], saved[3]);
      remember(r);
    } catch (err) { /* the selection moved with its text */ }
    if (!blocks.length) toast('Click into the text first.', true);
    return blocks;
  }

  function dropEmptyStyle(el) { if (!el.getAttribute('style')) el.removeAttribute('style'); }

  function alignBlocks(editor, value) {
    const blocks = selectedBlocks(editor);
    blocks.forEach((b) => { b.style.textAlign = value === 'left' ? '' : value; dropEmptyStyle(b); });
    return blocks.length > 0;
  }

  function padBlock(el, step) {
    const v = el.style.paddingLeft;
    const now = v.endsWith('px') ? parseFloat(v) / 16 : (parseFloat(v) || 0);
    const next = Math.max(0, Math.min(MAX_INDENT_EM, now + step * INDENT_EM));
    if (next === now) return false;
    el.style.paddingLeft = next ? `${next}em` : '';
    dropEmptyStyle(el);
    return true;
  }

  function childList(li, tag) {
    const last = li.lastElementChild;
    return last && last.tagName === tag ? last : null;
  }

  /** A list item one level in (under the item above it) or out (out of the list, as a <p>). */
  function shiftItem(li, step, editor) {
    const list = li.parentElement;
    if (step > 0) {
      const prev = li.previousElementSibling;
      if (!prev || prev.tagName !== 'LI') { toast('Only an item below another item can go in a level.', true); return false; }
      let sub = childList(prev, list.tagName);
      if (!sub) { sub = document.createElement(list.tagName); prev.appendChild(sub); }
      sub.appendChild(li);
      return true;
    }
    // The items after it stay below it: they become its own sub-list.
    const after = [];
    for (let n = li.nextElementSibling; n; n = n.nextElementSibling) after.push(n);
    const parentLi = list.parentElement.closest('li');
    if (parentLi && editor.contains(parentLi)) {
      if (after.length) {
        let sub = childList(li, list.tagName);
        if (!sub) { sub = document.createElement(list.tagName); li.appendChild(sub); }
        after.forEach((n) => sub.appendChild(n));
      }
      parentLi.after(li);
    } else {
      // Out of a top-level list: a paragraph; the items after it start a new list.
      const p = document.createElement('p');
      const nested = [];
      Array.from(li.childNodes).forEach((n) => (n.nodeType === 1 && /^(UL|OL)$/.test(n.tagName) ? nested.push(n) : p.appendChild(n)));
      if (li.getAttribute('style')) p.setAttribute('style', li.getAttribute('style'));
      list.after(p);
      let at = p;
      nested.forEach((n) => { at.after(n); at = n; });
      if (after.length) {
        const rest = list.cloneNode(false);
        after.forEach((n) => rest.appendChild(n));
        at.after(rest);
      }
      li.remove();
    }
    if (!list.children.length) list.remove();
    return true;
  }

  /** Chrome makes a list from paragraphs inside a <p> (<p><ul>…</ul></p>); lift it out. */
  function liftLists(editor) {
    const lists = $$('p > ul, p > ol', editor);
    if (!lists.length) return;
    const sel = window.getSelection();
    const r0 = sel.rangeCount ? sel.getRangeAt(0) : null;
    const saved = r0 && [r0.startContainer, r0.startOffset, r0.endContainer, r0.endOffset];
    lists.forEach((list) => {
      const p = list.parentElement;
      const rest = document.createRange();
      rest.selectNodeContents(p);
      rest.setStartAfter(list);
      const tail = rest.extractContents();
      p.after(list);
      if (tail.textContent.trim()) { const q = p.cloneNode(false); q.appendChild(tail); list.after(q); }
      if (!p.textContent.trim() && !p.querySelector('img, video')) p.remove();
    });
    if (!saved) return;
    try {
      const r = document.createRange();
      r.setStart(saved[0], saved[1]); r.setEnd(saved[2], saved[3]);
      remember(r);
    } catch (err) { /* the selection moved with its text */ }
  }

  function indentBlocks(editor, step) {
    const items = [];
    selectedBlocks(editor).forEach((b) => {
      const li = b.closest('li');
      const el = li && editor.contains(li) ? li : b;
      if (!items.includes(el)) items.push(el);
    });
    let changed = false;
    // In, top to bottom (each item joins the one above); out, bottom to top (keeps the order).
    (step > 0 ? items : items.slice().reverse()).forEach((el) => {
      changed = (el.tagName === 'LI' ? shiftItem(el, step, editor) : padBlock(el, step)) || changed;
    });
    return changed;
  }

  const SPECS = {
    bold: { tag: 'strong' },
    italic: { tag: 'em' },
    hayah: { tag: 'span', className: 'hayah' },
    h5: { tag: 'h5' },
    'hebrew-header': { tag: 'span', className: 'hebrew-header' },
    'greek-header': { tag: 'span', className: 'greek-header' },
    center: { tag: 'span', style: { display: 'block', textAlign: 'center' } },
    'center-last': { tag: 'span', className: 'last_center' },
    sun: { tag: 'div', className: 'sun-icon' },
    hebrew: { tag: 'span', className: 'hebrew' },
    greek: { tag: 'span', className: 'greek' },
    'note-heading': { tag: 'span', className: 'footnote_header' },
    paragraph: { tag: 'p' },
  };

  function runCommand(cmd, editor, button) {
    if (!editor) return;
    let changed = false;
    if (cmd === 'color') changed = toggleWrap(editor, { tag: 'span', style: { color: button.dataset.color } });
    else if (cmd === 'clear') changed = clearFormatting(editor);
    else if (cmd === 'link') {
      const range = rangeIn(editor);
      if (!range || range.collapsed) { toast('Select the link text first.', true); return; }
      const href = window.prompt('Link URL');
      if (!href) return;
      changed = toggleWrap(editor, { tag: 'a', attrs: { href, target: '_blank', rel: 'noopener' } });
    } else if (cmd === 'ul' || cmd === 'ol') {
      const range = rangeIn(editor);
      if (!range) { toast('Click into the text first.', true); return; }
      remember(range);
      editor.focus();
      document.execCommand(cmd === 'ul' ? 'insertUnorderedList' : 'insertOrderedList');
      liftLists(editor);
      changed = true;
    } else if (cmd === 'undo' || cmd === 'redo') { editor.focus(); document.execCommand(cmd); changed = true; }
    else if (cmd === 'align') changed = alignBlocks(editor, button.dataset.align);
    else if (cmd === 'indent' || cmd === 'outdent') changed = indentBlocks(editor, cmd === 'indent' ? 1 : -1);
    else if (SPECS[cmd]) changed = toggleWrap(editor, SPECS[cmd]);
    if (changed) editor.dispatchEvent(new Event('input', { bubbles: true }));
  }

  // Toolbar buttons keep the selection: mousedown is prevented, click runs the command on
  // the editable the toolbar belongs to (a footnote's own bar, or the verse).
  document.addEventListener('mousedown', (e) => {
    if (e.target.closest('#nve [data-cmd], #nve [data-insert], #nveMediaModal [data-cmd]')) e.preventDefault();
  });
  document.addEventListener('click', (e) => {
    const button = e.target.closest('#nve [data-cmd], #nveMediaModal [data-cmd]');
    if (!button) return;
    const scope = button.closest('.nve-note, .nve-composer, .nve-media-dialog');
    const editor = scope ? $('.nve-editable', scope) : verse.el;
    runCommand(button.dataset.cmd, editor, button);
  });

  // ⌘B / ⌘I use the site's <strong>/<em> rather than the browser's <b>/<i>.
  document.addEventListener('keydown', (e) => {
    const editable = e.target.closest && e.target.closest('.nve-editable');
    if (!editable || !(e.metaKey || e.ctrlKey) || e.shiftKey || e.altKey) return;
    const key = e.key.toLowerCase();
    if (key === 'b' || key === 'i') { e.preventDefault(); runCommand(key === 'b' ? 'bold' : 'italic', editable); }
  });

  // Tab / Shift+Tab move a list item in or out a level (footnotes and image notes).
  document.addEventListener('keydown', (e) => {
    if (e.key !== 'Tab' || e.metaKey || e.ctrlKey || e.altKey) return;
    const editable = e.target.closest && e.target.closest('.nve-editable');
    if (!editable || editable.id === 'nveVerse') return;
    const range = rangeIn(editable);
    const node = range && range.startContainer;
    const li = node && (node.nodeType === 1 ? node : node.parentElement).closest('li');
    if (!li || !editable.contains(li)) return;
    e.preventDefault();
    runCommand(e.shiftKey ? 'outdent' : 'indent', editable);
  });

  // Enter starts a <p> in footnotes and image notes (the site's paragraphs); the verse keeps
  // the browser's default.
  document.addEventListener('focusin', (e) => {
    const editable = e.target.closest && e.target.closest('.nve-editable');
    if (editable) document.execCommand('defaultParagraphSeparator', false, editable.id === 'nveVerse' ? 'div' : 'p');
  });

  // ------------------------------------------------------------------ serialising
  // Attributes the editor or other page scripts add to live content (base.html's tooltip
  // set-up marks every .tooltip-container); never saved.
  const FOREIGN_ATTRS = ['contenteditable', 'spellcheck', 'draggable', 'data-tooltip-init', 'data-nve-label'];

  function cleanHtml(rootEl) {
    $$('.nve-flash', rootEl).forEach((n) => n.classList.remove('nve-flash'));
    $$('.is-selected', rootEl).forEach((n) => n.classList.remove('is-selected'));
    FOREIGN_ATTRS.forEach((a) => $$(`[${a}]`, rootEl).forEach((n) => n.removeAttribute(a)));
    $$('[class=""]', rootEl).forEach((n) => n.removeAttribute('class'));
    return rootEl.innerHTML.trim().replace(/(<br\s*\/?>)+$/i, '').trim();
  }

  // ------------------------------------------------------------------ image blocks
  function mediaBlocks(rootEl) {
    return $$('.tooltip-container', rootEl).filter((b) => !b.parentElement.closest('.tooltip, .tooltip2'));
  }
  function mediaOf(block) { return $('img, video', block); }
  function notesOf(block) { return $('.tooltip, .tooltip2', block); }
  function mediaSrc(block) {
    const media = mediaOf(block);
    if (!media) return '';
    if (media.tagName === 'IMG') return media.getAttribute('src') || '';
    const source = $('source', media);
    return (source && source.getAttribute('src')) || media.getAttribute('src') || '';
  }
  function labelMedia(block) {
    const kind = mediaOf(block) && mediaOf(block).tagName === 'VIDEO' ? 'Video' : 'Image';
    const notes = (notesOf(block) ? notesOf(block).textContent : '').replace(/\s+/g, ' ').trim();
    block.setAttribute('data-nve-label', `${kind} · ${notes || 'no notes yet'}`);
  }
  function prepareMedia(rootEl) {
    mediaBlocks(rootEl).forEach((block) => {
      block.setAttribute('contenteditable', 'false');
      block.setAttribute('draggable', 'false');
      labelMedia(block);
    });
  }

  // A media block is a block element: never inside a heading, paragraph or inline element.
  function blockInsertionRange(editor, range) {
    if (!range || !editor.contains(range.commonAncestorContainer)) return endRange(editor);
    let node = range.startContainer;
    if (node === editor) return range;
    while (node.parentNode && node.parentNode !== editor) node = node.parentNode;
    if (node.nodeType === 3) return range;
    const before = document.createRange();
    before.selectNodeContents(node);
    before.setEnd(range.startContainer, range.startOffset);
    const target = document.createRange();
    if (before.toString().length === 0 && !before.cloneContents().querySelector('img, video')) target.setStartBefore(node);
    else target.setStartAfter(node);
    target.collapse(true);
    return target;
  }

  const mediaModal = $('#nveMediaModal');
  $$('[data-format-toolbar]').forEach((bar) => { bar.innerHTML = formatToolbar({ noteHeading: bar.dataset.formatToolbar === 'footnote' }); });
  const mediaUrl = $('#nveMediaUrl');
  const mediaNotes = $('#nveMediaNotes');
  const mediaPreview = $('#nveMediaPreview');
  let mediaCtx = null;

  function toggleModal(modal, show) { modal.classList.toggle('is-visible', !!show); modal.setAttribute('aria-hidden', String(!show)); }

  function renderMediaPreview(kind, url) {
    if (!url) { mediaPreview.innerHTML = `<p class="nve-muted">Paste the ${kind} URL to see it here.</p>`; return; }
    mediaPreview.innerHTML = kind === 'video'
      ? `<video src="${escapeHtml(url)}" controls muted loop autoplay playsinline></video>`
      : `<img src="${escapeHtml(url)}" alt="">`;
  }

  function openMedia(ctx) {
    mediaCtx = ctx;
    const kind = ctx.block ? (mediaOf(ctx.block) && mediaOf(ctx.block).tagName === 'VIDEO' ? 'video' : 'image') : ctx.kind;
    ctx.kind = kind;
    $('#nveMediaTitle').textContent = `${ctx.block ? 'Edit' : 'Add'} ${kind}`;
    $('#nveMediaUrlLabel').firstChild.textContent = kind === 'video' ? 'Video URL ' : 'Image URL ';
    mediaUrl.value = ctx.block ? mediaSrc(ctx.block) : '';
    const notes = ctx.block && notesOf(ctx.block);
    mediaNotes.innerHTML = notes ? notes.innerHTML.trim() : '';
    $('#nveMediaRemove').hidden = !ctx.block;
    $('#nveMediaApply').textContent = ctx.block ? 'Apply' : `Insert ${kind}`;
    renderMediaPreview(kind, mediaUrl.value.trim());
    $$('.tooltip-container.is-selected').forEach((b) => b.classList.remove('is-selected'));
    if (ctx.block) ctx.block.classList.add('is-selected');
    toggleModal(mediaModal, true);
    (ctx.block ? mediaNotes : mediaUrl).focus();
  }

  function closeMedia() {
    if (mediaCtx && mediaCtx.block) mediaCtx.block.classList.remove('is-selected');
    mediaPreview.innerHTML = '';
    mediaCtx = null;
    toggleModal(mediaModal, false);
  }

  function applyMedia() {
    if (!mediaCtx) return;
    const { text, block, kind, range } = mediaCtx;
    const url = mediaUrl.value.trim();
    if (!url) { toast(`Enter the ${kind} URL.`, true); mediaUrl.focus(); return; }
    let notesHtml = cleanHtml(mediaNotes.cloneNode(true));
    if (block) {
      const media = mediaOf(block);
      if (media && media.tagName === 'IMG') media.setAttribute('src', url);
      else if (media) {
        const source = $('source', media);
        if (source) source.setAttribute('src', url); else media.setAttribute('src', url);
        media.load();
      }
      let notes = notesOf(block);
      if (!notes) { notes = document.createElement('div'); notes.className = 'tooltip'; block.appendChild(notes); }
      notes.innerHTML = notesHtml;
      labelMedia(block);
    } else {
      if (kind === 'video' && notesHtml && !/^<(p|div|ul|ol|h\d)[\s>]/i.test(notesHtml)) notesHtml = `<p>${notesHtml}</p>`;
      const html = kind === 'video'
        ? `<div class="tooltip-container"><video autoplay muted loop playsinline style="width:500px;display:block;margin:0 auto;border-radius:8px;"><source src="${escapeHtml(url)}" type="video/mp4">Your browser does not support the video tag.</video><i class="touch-indicator fas fa-hand-pointer"></i><div class="tooltip">${notesHtml}</div></div>`
        : `<div class="tooltip-container"><img src="${escapeHtml(url)}" style="width: 500px; display: block; margin: 0 auto;">  <i class="touch-indicator fas fa-hand-pointer"></i><div class="tooltip">${notesHtml}</div></div>`;
      insertHtml(text.el, html, blockInsertionRange(text.el, range));
      prepareMedia(text.el);
    }
    closeMedia();
    text.el.dispatchEvent(new Event('input', { bubbles: true }));
  }

  function removeMedia() {
    if (!mediaCtx || !mediaCtx.block) return;
    if (!window.confirm(`Remove this ${mediaCtx.kind} and its notes?`)) return;
    const { text, block } = mediaCtx;
    closeMedia();
    block.remove();
    text.el.dispatchEvent(new Event('input', { bubbles: true }));
  }

  $('#nveMediaApply').addEventListener('click', applyMedia);
  $('#nveMediaRemove').addEventListener('click', removeMedia);
  $$('[data-action="close"]', mediaModal).forEach((b) => b.addEventListener('click', closeMedia));
  mediaUrl.addEventListener('input', debounce(() => { if (mediaCtx) renderMediaPreview(mediaCtx.kind, mediaUrl.value.trim()); }, 400));
  mediaUrl.addEventListener('keydown', (e) => { if (e.key === 'Enter') { e.preventDefault(); applyMedia(); } });
  mediaModal.addEventListener('keydown', (e) => {
    if (e.key === 'Escape') { e.stopPropagation(); closeMedia(); }
    if ((e.metaKey || e.ctrlKey) && e.key === 'Enter') { e.preventDefault(); applyMedia(); }
  });
  mediaModal.addEventListener('mousedown', (e) => { if (e.target === mediaModal) closeMedia(); });

  // ------------------------------------------------------------------ editable texts
  /**
   * One saved text (the verse, or a footnote): contenteditable + an HTML view, autosave,
   * a conflict check, Reset to the page-load version. `save(html, baseHash)` returns
   * {hash, html?}; a 409 error carries {html, hash} of what is stored now.
   */
  function makeText({ section, label, html, hash, save, onSaved }) {
    const t = {
      section, label, save, onSaved,
      el: $('.nve-editable', section),
      source: $('.nve-source', section),
      status: $('.nve-status', section),
      conflictBar: $('.nve-conflict', section),
      resetBtn: $('[data-act="reset"]', section),
      sourceToggle: $('[data-act="source"]', section),
      baseHash: hash,
      saving: false, suppressAutosave: false, pendingConflict: null,
    };
    setHtml(t, html);
    t.lastSavedHtml = serialize(t);
    t.loadedHtml = html;                 // Reset returns to this, exactly
    t.loadedRendered = t.lastSavedHtml;
    t.autosave = debounce(() => { if (!t.suppressAutosave && !t.pendingConflict) saveText(t); }, 1500);

    t.el.addEventListener('click', (e) => {
      const block = e.target.closest('.tooltip-container');
      if (!block || !t.el.contains(block) || block.parentElement.closest('.tooltip, .tooltip2')) return;
      e.preventDefault(); e.stopPropagation();
      openMedia({ text: t, block });
    }, true);
    t.el.addEventListener('input', () => {
      if (!t.source.hidden) return;
      t.source.value = cleanHtml(t.el.cloneNode(true));
      refresh(t); t.autosave();
    });
    t.source.addEventListener('input', () => {
      t.el.innerHTML = t.source.value; prepareMedia(t.el);
      refresh(t); t.autosave();
    });
    if (t.sourceToggle) t.sourceToggle.addEventListener('click', () => {
      const showingSource = !t.source.hidden;
      if (showingSource) {
        const unchanged = t.source.value.trim() === t.lastSavedHtml;
        t.el.innerHTML = t.source.value; prepareMedia(t.el);
        t.source.hidden = true; t.el.hidden = false;
        if (unchanged) t.lastSavedHtml = serialize(t);
        refresh(t); t.el.focus();
      } else {
        t.source.value = cleanHtml(t.el.cloneNode(true));
        t.el.hidden = true; t.source.hidden = false; t.source.focus();
      }
      t.sourceToggle.setAttribute('aria-pressed', String(!showingSource));
    });
    if (t.resetBtn) t.resetBtn.addEventListener('click', () => {
      if (!changedSinceLoad(t)) { toast(`No changes to the ${t.label} since you opened the page.`); return; }
      const saved = t.lastSavedHtml !== t.loadedRendered;
      if (!window.confirm(`Reset the ${t.label} to how it was when you opened this page?` +
        (saved ? '\n\nYour edits were already saved, so the original is saved back.' : ''))) return;
      t.autosave.cancel(); t.suppressAutosave = false;
      setHtml(t, t.loadedHtml);
      if (saved) saveText(t, t.loadedHtml);
      else { t.lastSavedHtml = serialize(t); refresh(t); }
    });
    if (t.conflictBar) {
      $('[data-act="conflict-load"]', t.conflictBar).addEventListener('click', () => {
        if (!t.pendingConflict) return;
        setHtml(t, t.pendingConflict.html || '');
        t.baseHash = t.pendingConflict.hash;
        t.lastSavedHtml = serialize(t);
        t.pendingConflict = null; t.conflictBar.hidden = true; t.suppressAutosave = false;
        refresh(t); toast(`Loaded the stored ${t.label}.`);
      });
      $('[data-act="conflict-keep"]', t.conflictBar).addEventListener('click', () => {
        if (!t.pendingConflict) return;
        t.baseHash = t.pendingConflict.hash;
        t.pendingConflict = null; t.conflictBar.hidden = true;
        saveText(t);
      });
    }
    refresh(t);
    return t;
  }

  /** What to save: in the HTML view exactly what was typed, otherwise the rendered text. */
  function serialize(t) {
    if (!t.source.hidden) return t.source.value.trim();
    return cleanHtml(t.el.cloneNode(true));
  }

  function setHtml(t, html) {
    t.el.innerHTML = html;
    prepareMedia(t.el);
    t.source.value = html;
  }

  function changedSinceLoad(t) {
    return t.lastSavedHtml !== t.loadedRendered || serialize(t) !== t.loadedRendered;
  }

  function setStatus(t, kind, text) {
    if (!t.status) return;
    t.status.className = `nve-status nve-status--${kind}`;
    t.status.textContent = text;
  }

  function refresh(t) {
    if (t.resetBtn) {
      t.resetBtn.disabled = !t.pendingConflict && !changedSinceLoad(t);
      t.resetBtn.title = t.resetBtn.disabled ? 'No changes since you opened the page' : 'Reset to how it was when you opened the page';
    }
    if (t.saving) return;
    if (t.pendingConflict) { setStatus(t, 'conflict', 'Conflict'); return; }
    if (serialize(t) !== t.lastSavedHtml) setStatus(t, 'dirty', t.suppressAutosave ? 'Unsaved · press Save to keep the suggestion' : 'Unsaved');
    else setStatus(t, 'saved', 'Saved');
  }

  async function saveText(t, exactHtml) {
    if (t.saving) return;
    const html = exactHtml === undefined ? serialize(t) : exactHtml;
    if (exactHtml === undefined && html === t.lastSavedHtml) { refresh(t); return; }
    t.saving = true; t.autosave.cancel();
    setStatus(t, 'saving', 'Saving…');
    try {
      const data = await t.save(html, t.baseHash);
      t.baseHash = data.hash;
      // The server stores footnotes in the clean form; show it once the note isn't in use.
      if (data.html !== undefined && data.html !== html && document.activeElement !== t.el && t.source.hidden) {
        setHtml(t, data.html);
      }
      t.lastSavedHtml = exactHtml === undefined && (data.html === undefined || data.html === html) ? html : serialize(t);
      t.suppressAutosave = false; t.saving = false;
      refresh(t);
      if (t.onSaved) t.onSaved(t, data);
      if (exactHtml !== undefined) toast(`The ${t.label} is back to how it was when you opened the page.`);
    } catch (err) {
      t.saving = false;
      if (err.status === 409 && err.data) {
        t.pendingConflict = err.data; if (t.conflictBar) t.conflictBar.hidden = false;
        setStatus(t, 'conflict', 'Conflict');
      } else {
        setStatus(t, 'error', `Not saved: ${err.message}`);
        toast(`The ${t.label} was not saved: ${err.message}`, true);
      }
    }
  }

  // ------------------------------------------------------------------ the verse
  const verseSection = $('#nveVerseSection');
  let verse = null;
  const notes = new Map(); // ref → footnote text
  let notesState = [];

  function verseSave(html, baseHash) {
    return call(api.apiVerse, { method: 'POST', body: { book: api.book, chapter: Number(api.chapter), verse: Number(api.verse), html, base_hash: baseHash } });
  }

  function markersIn(el) {
    return $$('a.sdfootnoteanc, a[href*="footnote="]', el).map((a) => {
      const m = (a.getAttribute('href') || '').match(/footnote=\d+-\d+-([0-9A-Za-z]+)/);
      return m ? m[1] : null;
    }).filter(Boolean);
  }

  function refreshMarkers() {
    const inVerse = new Set(markersIn(verse.el));
    notes.forEach((t, ref) => {
      const missing = !inVerse.has(ref);
      t.section.classList.toggle('is-unlinked', missing);
      const flag = $('.nve-note__unlinked', t.section);
      if (flag) flag.hidden = !missing;
    });
  }

  // ------------------------------------------------------------------ footnotes
  const notesList = $('#nveNotes');

  function noteCard(entry) {
    const card = document.createElement('article');
    card.className = 'nve-note';
    card.id = 'footnote-' + entry.ref;
    card.dataset.ref = entry.ref;
    card.innerHTML = `
      <header class="nve-note__head">
        <span class="nve-note__num">${escapeHtml(entry.ref)}</span>
        <code class="nve-note__id">${escapeHtml(entry.footnote_id)}</code>
        ${entry.copies > 1 ? `<span class="nve-tag nve-tag--warn" title="This id is stored ${entry.copies} times; the first non-empty copy is shown and saved">${entry.copies} copies</span>` : ''}
        ${entry.exists ? '' : '<span class="nve-tag nve-tag--warn" title="The verse links to a footnote that is not stored">missing</span>'}
        <span class="nve-tag nve-tag--clean"${entry.needs_cleanup ? '' : ' hidden'} title="${escapeHtml((entry.cleanup || []).join(' · '))}">needs cleanup</span>
        <span class="nve-note__unlinked nve-tag" hidden title="The verse no longer links to this footnote">not in the verse</span>
        <span class="nve-status nve-status--saved" aria-live="polite">Saved</span>
        <span class="nve-note__tools">
          <button type="button" class="tb-btn tb-btn--sm" data-act="cleanup" title="Put this note in the one consistent form (preview; it autosaves)">Clean up</button>
          <button type="button" class="tb-btn tb-btn--sm" data-act="source" aria-pressed="false" title="Edit the HTML directly">&lt;/&gt;</button>
          <button type="button" class="tb-btn tb-btn--sm tb-btn--ghost" data-act="reset">Reset</button>
          <button type="button" class="tb-btn tb-btn--sm tb-btn--ghost" data-act="collapse" aria-expanded="true" title="Show or hide this note">▾</button>
        </span>
      </header>
      <div class="nve-note__body">
        <div class="nve-minibar" role="toolbar" aria-label="Footnote formatting">${formatToolbar({ noteHeading: true })}</div>
        <div class="nve-conflict" hidden>This footnote was changed elsewhere since the page loaded.
          <button type="button" class="tb-btn" data-act="conflict-load">Load the stored version</button>
          <button type="button" class="tb-btn tb-btn--ghost" data-act="conflict-keep">Keep mine and overwrite</button></div>
        <div class="nve-editable nve-note__text rbt-notes tex2jax_ignore" contenteditable="true" spellcheck="true" aria-label="Footnote ${escapeHtml(entry.ref)}"></div>
        <textarea class="nve-source" hidden spellcheck="false" aria-label="Footnote ${escapeHtml(entry.ref)} HTML"></textarea>
        <p class="nve-note__cleanup" hidden></p>
      </div>`;
    return card;
  }

  /** The formatting bar for footnotes and image notes (noteHeading: the footnote-heading button). */
  function formatToolbar({ noteHeading = false } = {}) {
    return `<span class="nve-minibar__group">
      <button type="button" class="tb-btn" data-cmd="bold" title="Bold (⌘B)"><b>B</b></button>
      <button type="button" class="tb-btn" data-cmd="italic" title="Italic (⌘I)"><i>I</i></button>
      <button type="button" class="tb-btn" data-cmd="hebrew" title="Mark Hebrew words"><span class="hdr-icon hebrew">א</span></button>
      <button type="button" class="tb-btn" data-cmd="greek" title="Mark Greek words"><span class="hdr-icon greek">Ω</span></button>
      <button type="button" class="tb-btn tb-btn--swatch tb-btn--pink" data-cmd="color" data-color="#ff00aa" title="Pink"><i class="fas fa-circle"></i></button>
      <button type="button" class="tb-btn tb-btn--swatch tb-btn--blue" data-cmd="color" data-color="blue" title="Blue"><i class="fas fa-circle"></i></button>
      <button type="button" class="tb-btn" data-cmd="link" title="Link"><i class="fas fa-link"></i></button>
      </span><span class="nve-minibar__group">
      ${noteHeading ? '<button type="button" class="tb-btn" data-cmd="note-heading" title="Footnote heading">H</button>' : ''}
      <button type="button" class="tb-btn" data-cmd="paragraph" title="Paragraph">¶</button>
      <button type="button" class="tb-btn" data-cmd="ul" title="Bulleted list"><i class="fas fa-list-ul"></i></button>
      <button type="button" class="tb-btn" data-cmd="ol" title="Numbered list"><i class="fas fa-list-ol"></i></button>
      <button type="button" class="tb-btn" data-cmd="outdent" title="Indent less (in a list: ⇧Tab)"><i class="fas fa-outdent"></i></button>
      <button type="button" class="tb-btn" data-cmd="indent" title="Indent more (in a list: Tab)"><i class="fas fa-indent"></i></button>
      </span><span class="nve-minibar__group">
      <button type="button" class="tb-btn" data-cmd="align" data-align="left" title="Align left"><i class="fas fa-align-left"></i></button>
      <button type="button" class="tb-btn" data-cmd="align" data-align="center" title="Center"><i class="fas fa-align-center"></i></button>
      <button type="button" class="tb-btn" data-cmd="align" data-align="right" title="Align right"><i class="fas fa-align-right"></i></button>
      <button type="button" class="tb-btn" data-cmd="align" data-align="justify" title="Justify"><i class="fas fa-align-justify"></i></button>
      </span><span class="nve-minibar__group">
      <button type="button" class="tb-btn" data-cmd="clear" title="Remove the formatting around the selection">Tx</button></span>`;
  }

  function addNote(entry, { prepend = false } = {}) {
    const card = noteCard(entry);
    if (prepend) notesList.prepend(card); else notesList.appendChild(card);
    const t = makeText({
      section: card,
      label: `footnote ${entry.ref}`,
      html: entry.html,
      hash: entry.hash,
      save: (html, baseHash) => call(api.apiFootnote, { method: 'POST', body: {
        book: api.book, chapter: Number(api.chapter), verse: Number(api.verse), ref: entry.ref, html, base_hash: baseHash } }),
      onSaved: () => { $('.nve-tag--clean', card).hidden = true; },
    });
    notes.set(entry.ref, t);
    $('[data-act="collapse"]', card).addEventListener('click', (e) => {
      const collapsed = card.classList.toggle('is-collapsed');
      e.currentTarget.setAttribute('aria-expanded', String(!collapsed));
      e.currentTarget.textContent = collapsed ? '▸' : '▾';
    });
    $('[data-act="cleanup"]', card).addEventListener('click', async () => {
      const line = $('.nve-note__cleanup', card);
      try {
        const data = await call(api.apiNormalize, { method: 'POST', body: { html: serialize(t) } });
        if (!data.changes.length) { line.hidden = false; line.textContent = 'Already clean.'; return; }
        if (data.text_changed && !window.confirm('Cleaning up would change the wording of this note. Apply anyway?')) return;
        setHtml(t, data.html);
        line.hidden = false;
        line.textContent = 'Cleaned up: ' + data.changes.join(' · ') + (data.review.length ? ' — ' + data.review.join(' · ') : '');
        t.el.dispatchEvent(new Event('input', { bubbles: true }));
        if (!t.source.hidden) { t.source.value = data.html; t.source.dispatchEvent(new Event('input', { bubbles: true })); }
      } catch (err) { toast(`Clean-up failed: ${err.message}`, true); }
    });
    return t;
  }

  function focusNote(ref) {
    const t = notes.get(ref);
    if (!t) { toast(`Footnote ${ref} is not loaded on this page.`, true); return; }
    t.section.classList.remove('is-collapsed');
    t.section.scrollIntoView({ behavior: 'smooth', block: 'center' });
    t.section.classList.add('is-flash');
    setTimeout(() => t.section.classList.remove('is-flash'), 1400);
    setTimeout(() => t.el.focus({ preventScroll: true }), 350);
  }

  // ------------------------------------------------------------------ add a footnote
  const composer = $('#nveComposer');
  const composerText = $('#nveComposerText');
  const composerHeading = $('#nveComposerHeading');
  let composerRange = null;

  function openComposer() {
    const range = rangeIn(verse.el);
    if (!range) { toast('Click in the verse where the footnote marker should go, then press Footnote.', true); return; }
    composerRange = range.cloneRange();
    composerHeading.value = '';
    composerText.innerHTML = '';
    composer.hidden = false;
    const before = document.createRange();
    before.selectNodeContents(verse.el);
    before.setEnd(composerRange.startContainer, composerRange.startOffset);
    composer.dataset.index = String(markersIn(before.cloneContents()).length);
    composer.scrollIntoView({ behavior: 'smooth', block: 'center' });
    setTimeout(() => composerText.focus(), 300);
  }

  function closeComposer() { composer.hidden = true; composerRange = null; }

  async function createNote() {
    const body = cleanHtml(composerText.cloneNode(true));
    if (!body.replace(/<[^>]+>/g, '').trim()) { toast('Write the footnote first.', true); composerText.focus(); return; }
    const button = $('#nveComposerCreate');
    button.disabled = true;
    try {
      const data = await call(api.apiFootnoteCreate, { method: 'POST', body: {
        book: api.book, chapter: Number(api.chapter), verse: Number(api.verse),
        index: Number(composer.dataset.index || 0), heading: composerHeading.value.trim(), html: body } });
      const range = composerRange && verse.el.contains(composerRange.commonAncestorContainer) ? composerRange : endRange(verse.el);
      closeComposer();
      insertHtml(verse.el, data.marker, range);
      verse.el.dispatchEvent(new Event('input', { bubbles: true }));
      saveText(verse);
      const t = addNote({ ref: data.ref, footnote_id: data.footnote_id, exists: true, copies: 1, html: data.html, hash: data.hash, needs_cleanup: false, cleanup: [] });
      orderNotes();
      focusNote(data.ref);
      toast(`Footnote ${data.ref} added and linked in the verse.`);
      return t;
    } catch (err) {
      toast(`The footnote was not added: ${err.message}`, true);
    } finally { button.disabled = false; }
  }

  function orderNotes() {
    const order = markersIn(verse.el);
    [...notes.values()].sort((a, b) => {
      const ia = order.indexOf(a.section.dataset.ref), ib = order.indexOf(b.section.dataset.ref);
      return (ia < 0 ? 999 : ia) - (ib < 0 ? 999 : ib);
    }).forEach((t) => notesList.appendChild(t.section));
    $('#nveNotesEmpty').hidden = notes.size > 0;
  }

  $('#nveComposerCreate').addEventListener('click', createNote);
  $('#nveComposerCancel').addEventListener('click', closeComposer);
  composerText.addEventListener('keydown', (e) => { if ((e.metaKey || e.ctrlKey) && e.key === 'Enter') { e.preventDefault(); createNote(); } });

  // ------------------------------------------------------------------ toolbar: insert
  $$('[data-insert]', root).forEach((button) => button.addEventListener('click', () => {
    const kind = button.dataset.insert;
    if (kind === 'footnote') { openComposer(); return; }
    if (kind === 'literal') {
      insertHtml(verse.el, escapeHtml(api.literal || ''));
      verse.el.dispatchEvent(new Event('input', { bubbles: true }));
      return;
    }
    if (kind === 'image' || kind === 'video') {
      const range = rangeIn(verse.el);
      openMedia({ text: verse, kind, range: range ? range.cloneRange() : null });
    }
  }));

  $('#nveSave').addEventListener('click', saveAll);
  function saveAll() { [verse, ...notes.values()].forEach((t) => saveText(t)); }
  document.addEventListener('keydown', (e) => {
    if ((e.metaKey || e.ctrlKey) && e.key.toLowerCase() === 's' && !e.target.closest('#nveComposer')) { e.preventDefault(); saveAll(); }
  });
  window.addEventListener('beforeunload', (e) => {
    const dirty = [verse, ...notes.values()].some((t) => t && serialize(t) !== t.lastSavedHtml);
    if (dirty || (!composer.hidden && composerText.textContent.trim())) { e.preventDefault(); e.returnValue = ''; }
  });

  // ------------------------------------------------------------------ AI suggestions
  // The page's Gemini/ChatGPT scripts write into #editor-texto and call updateReader().
  window.updateReader = function (html) {
    if (!verse) return;
    const value = html === undefined ? verse.source.value : html;
    verse.el.innerHTML = value; prepareMedia(verse.el);
    verse.source.value = value;
    verse.suppressAutosave = true;
    refresh(verse);
  };

  // ------------------------------------------------------------------ start
  async function start() {
    const initialHtml = $('#nveVerse').innerHTML;
    verse = makeText({
      section: verseSection, label: 'verse',
      html: initialHtml.trim(), hash: '',
      save: verseSave,
      onSaved: () => refreshMarkers(),
    });
    verse.el.addEventListener('input', debounce(refreshMarkers, 400));
    // A click on a footnote marker in the verse opens that note (it never navigates).
    verse.el.addEventListener('click', (e) => {
      const a = e.target.closest('a[href*="footnote="]');
      if (!a) return;
      e.preventDefault();
      const m = (a.getAttribute('href') || '').match(/footnote=\d+-\d+-([0-9A-Za-z]+)/);
      if (m) focusNote(m[1]);
    });

    try {
      const state = await call(api.apiState, { query: { book: api.book, chapter: api.chapter, verse: api.verse } });
      // The page may come from the reader cache; the database copy is what saves are checked
      // against and what Reset returns to. Swap it in only if it renders differently.
      const probe = document.createElement('div');
      probe.innerHTML = state.html; prepareMedia(probe);
      if (cleanHtml(probe) !== verse.lastSavedHtml && serialize(verse) === verse.lastSavedHtml) {
        setHtml(verse, state.html);
        verse.lastSavedHtml = serialize(verse);
      }
      verse.baseHash = state.hash;
      verse.loadedHtml = state.html;
      verse.loadedRendered = verse.lastSavedHtml;
      refresh(verse);
      notesState = state.footnotes;
      notesState.forEach((entry) => addNote(entry));
      orderNotes();
      refreshMarkers();
      const wanted = new URLSearchParams(window.location.search).get('footnote');
      if (wanted) focusNote(wanted.split('-').pop());
    } catch (err) {
      toast(`Could not load the footnotes: ${err.message}`, true);
      $('#nveNotesEmpty').hidden = false;
      $('#nveNotesEmpty').textContent = `Could not load the footnotes: ${err.message}`;
    }
  }
  start();
})();
