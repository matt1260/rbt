/**
 * Old Testament verse editor (/translate/ot/).
 *
 * - Word cards: gloss and morphology are edited in place and saved on Enter/blur; gender
 *   colour saves on change; a footnote drawer per word.
 * - Paraphrase: contenteditable with a toolbar, autosave with optimistic concurrency
 *   (a 409 from the server means the verse changed elsewhere; nothing is overwritten).
 * - Slide-out panels: chapter (left), lexicon / consonantal search / lexicon mapping (right).
 */
(function () {
  'use strict';

  const root = document.getElementById('ote');
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
  const stripVowels = (s) => (s || '').replace(/[֑-ְ֯-ֽֿׁ-ׂׄ-ׇׅ]/g, '');

  let toastTimer = null;
  function toast(message, isError) {
    const el = $('#oteToast');
    el.textContent = message;
    el.classList.toggle('is-error', !!isError);
    el.hidden = false;
    clearTimeout(toastTimer);
    toastTimer = setTimeout(() => { el.hidden = true; }, isError ? 5000 : 2600);
  }

  function debounce(fn, ms) {
    let t = null;
    const wrapped = (...args) => { clearTimeout(t); t = setTimeout(() => fn(...args), ms); };
    wrapped.cancel = () => clearTimeout(t);
    return wrapped;
  }

  function copyText(text) {
    if (navigator.clipboard && navigator.clipboard.writeText) return navigator.clipboard.writeText(text);
    const ta = document.createElement('textarea');
    ta.value = text; document.body.appendChild(ta); ta.select();
    try { document.execCommand('copy'); } finally { document.body.removeChild(ta); }
    return Promise.resolve();
  }

  // ------------------------------------------------------------------ niqqud toggle
  const niqqud = $('#oteNiqqud');
  function applyNiqqud(on) { root.classList.toggle('show-niqqud', on); }
  try {
    // Off unless chosen. New key: an 'on' saved while on was the default shouldn't carry over.
    const stored = localStorage.getItem('oteNiqqudChoice');
    if (stored !== null) niqqud.checked = stored === '1';
  } catch (e) { /* ignore */ }
  applyNiqqud(niqqud.checked);
  niqqud.addEventListener('change', () => {
    applyNiqqud(niqqud.checked);
    try { localStorage.setItem('oteNiqqudChoice', niqqud.checked ? '1' : '0'); } catch (e) { /* ignore */ }
  });

  // ------------------------------------------------------------------ hebrew line ↔ cards
  const cardOf = (id) => document.getElementById('token-' + id);
  function activateCard(id, scroll) {
    $$('.ote-card.is-active, .ote-hebrew__word.is-active').forEach((el) => el.classList.remove('is-active'));
    const card = cardOf(id);
    const word = $(`.ote-hebrew__word[data-token="${id}"]`);
    if (card) card.classList.add('is-active');
    if (word) word.classList.add('is-active');
    if (card && scroll) card.scrollIntoView({ behavior: 'smooth', block: 'center' });
  }
  $$('.ote-hebrew__word').forEach((word) => {
    word.addEventListener('click', () => {
      activateCard(word.dataset.token, true);
      const gloss = $('.ote-gloss', cardOf(word.dataset.token));
      if (gloss) setTimeout(() => gloss.focus(), 350);
    });
    word.addEventListener('mouseenter', () => cardOf(word.dataset.token)?.classList.add('is-active'));
    word.addEventListener('mouseleave', () => { if (!word.classList.contains('is-active')) cardOf(word.dataset.token)?.classList.remove('is-active'); });
  });
  $$('.ote-card').forEach((card) => {
    card.addEventListener('focusin', () => activateCard(card.dataset.token, false));
  });

  // ------------------------------------------------------------------ balanced card rows
  // As many columns as fit, then evened out so the last row isn't a lone card
  // (7 words in room for 6 → 4 + 3).
  const cardGrid = $('.ote-cards');
  function balanceCards() {
    if (!cardGrid) return;
    const count = $$('.ote-card', cardGrid).length;
    const gap = 8, minWidth = 200;
    const fit = Math.max(1, Math.floor((cardGrid.clientWidth + gap) / (minWidth + gap)));
    const rows = Math.ceil(count / fit);
    cardGrid.style.setProperty('--ote-cols', String(Math.max(1, Math.ceil(count / rows))));
  }
  if (cardGrid) {
    balanceCards();
    if (window.ResizeObserver) new ResizeObserver(balanceCards).observe(cardGrid);
  }

  // ------------------------------------------------------------------ inline fields (gloss, morphology)
  function colourMorphology(el) {
    const text = el.textContent;
    if (!text) { el.innerHTML = ''; return; }
    el.innerHTML = text.split(/(\s*,\s*)/).map((seg, i) => {
      if (i % 2) return escapeHtml(seg);
      const lower = seg.toLowerCase();
      if (lower.includes('feminine')) return `<span class="ote-morph__f">${escapeHtml(seg)}</span>`;
      if (lower.includes('masculine')) return `<span class="ote-morph__m">${escapeHtml(seg)}</span>`;
      return escapeHtml(seg);
    }).join('');
  }
  $$('.ote-morph').forEach(colourMorphology);

  function flashState(el, cls, ms) {
    el.classList.add(cls);
    setTimeout(() => el.classList.remove(cls), ms || 1400);
  }

  function beginEdit(field) {
    if (field.isContentEditable) return;
    // Glosses are edited as stored, which can include HTML (e.g. the hayah span);
    // morphology as its text (the colour spans are display only).
    field.dataset.original = field.dataset.field === 'gloss' ? (field.dataset.raw || '').trim() : field.textContent.trim();
    field.textContent = field.dataset.original;
    field.setAttribute('contenteditable', 'plaintext-only');
    if (!field.isContentEditable) field.setAttribute('contenteditable', 'true');
    field.classList.add('is-editing');
    field.focus();
    const range = document.createRange();
    range.selectNodeContents(field);
    const sel = window.getSelection();
    sel.removeAllRanges(); sel.addRange(range);
  }

  function showGloss(field, raw) {
    field.dataset.raw = raw;
    field.innerHTML = raw;
  }

  function endEdit(field, text) {
    field.removeAttribute('contenteditable');
    field.classList.remove('is-editing');
    if (field.dataset.field === 'gloss') showGloss(field, text);
    else field.textContent = text;
    if (field.dataset.field === 'morphology') colourMorphology(field);
    delete field.dataset.original;
  }

  async function commitEdit(field) {
    if (!field.isContentEditable) return;
    const original = field.dataset.original || '';
    const value = field.textContent.replace(/\s+/g, ' ').trim();
    if (value === original) { endEdit(field, original); return; }
    const card = field.closest('.ote-card');
    const id = Number(card.dataset.token);
    endEdit(field, value);
    field.classList.add('is-saving');
    try {
      if (field.dataset.field === 'gloss') {
        const scope = $('#oteScope').value;
        const data = await call(api.apiGloss, { method: 'POST', body: { id, english: value, scope } });
        (data.verse_ids || []).forEach((otherId) => {
          const other = cardOf(otherId);
          if (other && otherId !== id) {
            const g = $('.ote-gloss', other);
            if (g && !g.isContentEditable) showGloss(g, data.english);
          }
        });
        $$(`.ote-hebrew__word[data-token="${id}"]`).forEach((w) => { w.title = data.english.replace(/<[^>]+>/g, ''); });
        $('#oteLiteral').innerHTML = data.literal || '';
        toast(data.updated === 1 ? 'Gloss saved' : `Gloss saved · ${data.updated.toLocaleString()} words updated`);
      } else {
        await call(api.apiMorphology, { method: 'POST', body: { id, morphology: value } });
      }
      field.classList.remove('is-saving');
      flashState(field, 'is-saved');
    } catch (err) {
      field.classList.remove('is-saving');
      field.classList.add('is-error');
      toast(`Not saved: ${err.message}`, true);
      if (field.dataset.field === 'gloss') showGloss(field, original);
      else { field.textContent = original; colourMorphology(field); }
      setTimeout(() => field.classList.remove('is-error'), 2500);
    }
  }

  $$('.ote-gloss, .ote-morph').forEach((field) => {
    field.addEventListener('click', () => beginEdit(field));
    field.addEventListener('focus', () => beginEdit(field));
    field.addEventListener('keydown', (e) => {
      if (e.key === 'Enter') { e.preventDefault(); field.blur(); }
      else if (e.key === 'Escape') {
        e.preventDefault();
        const original = field.dataset.original || '';
        endEdit(field, original);
        field.blur();
      }
    });
    field.addEventListener('blur', () => commitEdit(field));
  });

  // ------------------------------------------------------------------ gender
  $$('.ote-gender').forEach((select) => {
    select.addEventListener('change', async () => {
      const card = select.closest('.ote-card');
      const id = Number(card.dataset.token);
      const previous = card.dataset.gender;
      try {
        const data = await call(api.apiGender, { method: 'POST', body: { id, gender: select.value } });
        (data.verse_ids || []).forEach((otherId) => {
          const other = cardOf(otherId);
          if (!other) return;
          other.dataset.gender = data.gender;
          const sel = $('.ote-gender', other);
          if (sel) sel.value = data.gender;
          const word = $(`.ote-hebrew__word[data-token="${otherId}"]`);
          if (word) word.dataset.gender = data.gender;
        });
        toast(`Gender saved · ${data.updated.toLocaleString()} words`);
      } catch (err) {
        select.value = previous;
        toast(`Not saved: ${err.message}`, true);
      }
    });
  });

  // ------------------------------------------------------------------ selection + formatting
  let lastEditable = null;
  const savedRanges = new WeakMap(); // editable element → the last selection inside it

  document.addEventListener('selectionchange', () => {
    const sel = window.getSelection();
    if (!sel.rangeCount) return;
    const node = sel.anchorNode;
    const editable = node && (node.nodeType === 1 ? node : node.parentElement)?.closest('.ote-editable');
    if (editable) {
      lastEditable = editable;
      savedRanges.set(editable, sel.getRangeAt(0).cloneRange());
      const text = textByEl.get(editable);
      if (text) setActiveText(text);
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

  function selectContents(node) {
    const range = document.createRange();
    range.selectNodeContents(node);
    const sel = window.getSelection();
    sel.removeAllRanges(); sel.addRange(range);
    const editable = node.closest('.ote-editable');
    if (editable) savedRanges.set(editable, range.cloneRange());
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
      const sel = window.getSelection(); sel.removeAllRanges(); sel.addRange(range);
      const editable = parent.nodeType === 1 && (parent.closest ? parent.closest('.ote-editable') : null);
      if (editable) savedRanges.set(editable, range.cloneRange());
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
    const FORMAT = /^(strong|b|em|i|span|h5|div|a|u|font)$/i;
    let el = range.commonAncestorContainer;
    el = el.nodeType === 1 ? el : el.parentElement;
    while (el && el !== editor && !FORMAT.test(el.tagName)) el = el.parentElement;
    if (!el || el === editor) {
      if (range.collapsed) { toast('Nothing to clear here.', true); return false; }
      const frag = range.extractContents();
      range.insertNode(document.createTextNode(frag.textContent));
      return true;
    }
    if (el.tagName.toLowerCase() === 'div' && !el.classList.contains('sun-icon')) { toast('Nothing to clear here.', true); return false; }
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
      const sel = window.getSelection(); sel.removeAllRanges(); sel.addRange(after);
      savedRanges.set(editor, after.cloneRange());
      nodes.filter((n) => n.nodeType === 1).forEach((n) => { n.classList.add('ote-insert-flash'); setTimeout(() => n.classList.remove('ote-insert-flash'), 900); });
    }
    return true;
  }

  function remember(range) {
    const sel = window.getSelection(); sel.removeAllRanges(); sel.addRange(range);
    const node = range.commonAncestorContainer;
    const editable = (node.nodeType === 1 ? node : node.parentElement)?.closest('.ote-editable');
    if (editable) savedRanges.set(editable, range.cloneRange());
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
    center: { tag: 'span', style: { display: 'block', textAlign: 'center' } },
    'center-last': { tag: 'span', className: 'last_center' },
    indent: { tag: 'span', className: 'poetry-indent' },
    sun: { tag: 'div', className: 'sun-icon' },
    'hebrew-footnote': { tag: 'span', className: 'hebrew_footnote' },
    paragraph: { tag: 'p' },
  };

  function runCommand(cmd, editor, button) {
    editor = editor || (activeText && activeText.el) || lastEditable;
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
    }
    else if (cmd === 'undo' || cmd === 'redo') { editor.focus(); document.execCommand(cmd); changed = true; }
    else if (cmd === 'ul' || cmd === 'ol') {
      const range = rangeIn(editor);
      if (!range) { toast('Click into the text first.', true); return; }
      remember(range);
      editor.focus();
      document.execCommand(cmd === 'ul' ? 'insertUnorderedList' : 'insertOrderedList');
      liftLists(editor);
      changed = true;
    }
    else if (cmd === 'align') changed = alignBlocks(editor, button.dataset.align);
    // 'indent' is the verse's poetry-indent span; these move whole paragraphs and list items.
    else if (cmd === 'para-indent' || cmd === 'para-outdent') changed = indentBlocks(editor, cmd === 'para-indent' ? 1 : -1);
    else if (SPECS[cmd]) changed = toggleWrap(editor, SPECS[cmd]);
    if (changed) editor.dispatchEvent(new Event('input', { bubbles: true }));
  }

  // Toolbar buttons keep the selection: mousedown is prevented, click runs the command.
  // A footnote's own mini toolbar formats that footnote; the main toolbar formats the active verse text.
  /** The formatting bar for footnotes and image notes (hebrew: the Hebrew button's command). */
  function formatToolbar(hebrew) {
    return `<span class="ote-minibar__group">
      <button type="button" class="tb-btn" data-cmd="bold" title="Bold (⌘B)"><b>B</b></button>
      <button type="button" class="tb-btn" data-cmd="italic" title="Italic (⌘I)"><i>I</i></button>
      ${hebrew === 'hayah' ? '<button type="button" class="tb-btn" data-cmd="hayah" title="Hayah">היה</button>' : '<button type="button" class="tb-btn" data-cmd="hebrew-footnote" title="Hebrew">א</button>'}
      <button type="button" class="tb-btn tb-btn--swatch tb-btn--pink" data-cmd="color" data-color="#ff00aa" title="Magenta"><i class="fas fa-circle"></i></button>
      <button type="button" class="tb-btn tb-btn--swatch tb-btn--blue" data-cmd="color" data-color="blue" title="Blue"><i class="fas fa-circle"></i></button>
      <button type="button" class="tb-btn" data-cmd="link" title="Link"><i class="fas fa-link"></i></button>
      </span><span class="ote-minibar__group">
      <button type="button" class="tb-btn" data-cmd="paragraph" title="Paragraph">¶</button>
      <button type="button" class="tb-btn" data-cmd="ul" title="Bulleted list"><i class="fas fa-list-ul"></i></button>
      <button type="button" class="tb-btn" data-cmd="ol" title="Numbered list"><i class="fas fa-list-ol"></i></button>
      <button type="button" class="tb-btn" data-cmd="para-outdent" title="Indent less (in a list: ⇧Tab)"><i class="fas fa-outdent"></i></button>
      <button type="button" class="tb-btn" data-cmd="para-indent" title="Indent more (in a list: Tab)"><i class="fas fa-indent"></i></button>
      </span><span class="ote-minibar__group">
      <button type="button" class="tb-btn" data-cmd="align" data-align="left" title="Align left"><i class="fas fa-align-left"></i></button>
      <button type="button" class="tb-btn" data-cmd="align" data-align="center" title="Center"><i class="fas fa-align-center"></i></button>
      <button type="button" class="tb-btn" data-cmd="align" data-align="right" title="Align right"><i class="fas fa-align-right"></i></button>
      <button type="button" class="tb-btn" data-cmd="align" data-align="justify" title="Justify"><i class="fas fa-align-justify"></i></button>
      </span><span class="ote-minibar__group">
      <button type="button" class="tb-btn" data-cmd="clear" title="Remove formatting">Tx</button></span>`;
  }
  $$('[data-format-toolbar]').forEach((bar) => { bar.innerHTML = formatToolbar(bar.dataset.formatToolbar === 'notes' ? 'hayah' : 'hebrew'); });

  // A footnote's or the image notes' own bar formats that text; the main toolbar the active verse text.
  function bindCommands(rootEl) {
    $$('[data-cmd]', rootEl).forEach((button) => {
      button.addEventListener('mousedown', (e) => e.preventDefault());
      button.addEventListener('click', () => {
        const scope = button.closest('.ote-footnote, .ote-fn, .ote-media-dialog');
        const editor = scope ? $('.ote-editable', scope) : (activeText && activeText.el);
        runCommand(button.dataset.cmd, editor, button);
      });
    });
  }
  bindCommands(document);

  // Tab / Shift+Tab move a list item in or out a level (footnotes and image notes).
  document.addEventListener('keydown', (e) => {
    if (e.key !== 'Tab' || e.metaKey || e.ctrlKey || e.altKey) return;
    const editable = e.target.closest && e.target.closest('.ote-footnote__editor, .ote-fn__text, #oteMediaNotes');
    if (!editable) return;
    const range = rangeIn(editable);
    const node = range && range.startContainer;
    const li = node && (node.nodeType === 1 ? node : node.parentElement).closest('li');
    if (!li || !editable.contains(li)) return;
    e.preventDefault();
    runCommand(e.shiftKey ? 'para-outdent' : 'para-indent', editable);
  });

  // Enter starts a <p> in footnotes and image notes; the verse texts keep the browser's default.
  document.addEventListener('focusin', (e) => {
    const editable = e.target.closest && e.target.closest('.ote-editable');
    if (editable) document.execCommand('defaultParagraphSeparator', false, editable.matches('.ote-footnote__editor, .ote-fn__text, #oteMediaNotes') ? 'p' : 'div');
  });

  // ⌘B / ⌘I inside any editable use the site's <strong>/<em> rather than the browser's <b>/<i>.
  document.addEventListener('keydown', (e) => {
    const editable = e.target.closest && e.target.closest('.ote-editable');
    if (!editable || !(e.metaKey || e.ctrlKey) || e.shiftKey || e.altKey) return;
    const key = e.key.toLowerCase();
    if (key === 'b' || key === 'i') { e.preventDefault(); runCommand(key === 'b' ? 'bold' : 'italic', editable); }
  });

  // ------------------------------------------------------------------ image blocks
  // Verse HTML holds each image or video as a .tooltip-container: the media, then its notes in
  // a hidden .tooltip. In the editor each block is one compact row that can't be typed into;
  // clicking it opens the image pop-up (media, URL, notes), as the NT inline editor does.
  // Function declarations only: makeText() below runs prepareMedia() while the page starts.
  function mediaBlocks(root) {
    return $$('.tooltip-container', root).filter((block) => !block.parentElement.closest('.tooltip, .tooltip2'));
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
    block.setAttribute('data-ote-label', `${kind} · ${notes || 'no notes yet'}`);
  }
  function prepareMedia(root) {
    mediaBlocks(root).forEach((block) => {
      block.setAttribute('contenteditable', 'false');
      block.setAttribute('draggable', 'false');
      labelMedia(block);
    });
  }

  const mediaModal = $('#oteMediaModal');
  const mediaUrl = $('#oteMediaUrl');
  const mediaNotes = $('#oteMediaNotes');
  const mediaPreview = $('#oteMediaPreview');
  let mediaCtx = null; // { t, block } for an existing block, { t, kind, range } for a new one

  function renderMediaPreview(kind, url) {
    if (!url) { mediaPreview.innerHTML = `<p class="ote-muted">Paste the ${kind} URL to see it here.</p>`; return; }
    mediaPreview.innerHTML = kind === 'video'
      ? `<video src="${escapeHtml(url)}" controls muted loop autoplay playsinline></video>`
      : `<img src="${escapeHtml(url)}" alt="">`;
  }

  function openMedia(ctx) {
    mediaCtx = ctx;
    const kind = ctx.block ? (mediaOf(ctx.block) && mediaOf(ctx.block).tagName === 'VIDEO' ? 'video' : 'image') : ctx.kind;
    ctx.kind = kind;
    $('#oteMediaTitle').textContent = `${ctx.block ? 'Edit' : 'Add'} ${kind} · ${ctx.t.label.toLowerCase()}`;
    $('#oteMediaUrlLabel').firstChild.textContent = kind === 'video' ? 'Video URL ' : 'Image URL ';
    mediaUrl.value = ctx.block ? mediaSrc(ctx.block) : '';
    const notes = ctx.block && notesOf(ctx.block);
    mediaNotes.innerHTML = notes ? notes.innerHTML.trim() : '';
    $('#oteMediaRemove').hidden = !ctx.block;
    $('#oteMediaApply').textContent = ctx.block ? 'Apply' : `Insert ${kind}`;
    renderMediaPreview(kind, mediaUrl.value.trim());
    $$('.tooltip-container.is-selected').forEach((b) => b.classList.remove('is-selected'));
    if (ctx.block) ctx.block.classList.add('is-selected');
    toggleModal(mediaModal, true);
    (ctx.block ? mediaNotes : mediaUrl).focus();
  }

  function closeMedia() {
    if (mediaCtx && mediaCtx.block) mediaCtx.block.classList.remove('is-selected');
    mediaPreview.innerHTML = ''; // stops a playing video
    mediaCtx = null;
    toggleModal(mediaModal, false);
  }

  // A media block is a block element: never put it inside a heading, paragraph or inline
  // element. Use the caret's top-level element and go after it (before it if the caret is at
  // its very start); a caret in loose top-level text inserts right there.
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

  function applyMedia() {
    if (!mediaCtx) return;
    const { t, block, kind, range } = mediaCtx;
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
      // The markup the reader and the older editors use for media blocks.
      if (kind === 'video' && notesHtml && !/^<(p|div|ul|ol|h\d)[\s>]/i.test(notesHtml)) notesHtml = `<p>${notesHtml}</p>`;
      const html = kind === 'video'
        ? `<div class="tooltip-container"><video autoplay muted loop playsinline style="width:500px;display:block;margin:0 auto;border-radius:8px;"><source src="${escapeHtml(url)}" type="video/mp4">Your browser does not support the video tag.</video><i class="touch-indicator fas fa-hand-pointer"></i><div class="tooltip">${notesHtml}</div></div>`
        : `<div class="tooltip-container"><img src="${escapeHtml(url)}" style="width: 500px; display: block; margin: 0 auto;">  <i class="touch-indicator fas fa-hand-pointer"></i><div class="tooltip">${notesHtml}</div></div>`;
      insertHtml(t.el, html, blockInsertionRange(t.el, range));
      prepareMedia(t.el);
    }
    closeMedia();
    t.el.dispatchEvent(new Event('input', { bubbles: true }));
  }

  function removeMedia() {
    if (!mediaCtx || !mediaCtx.block) return;
    if (!window.confirm(`Remove this ${mediaCtx.kind} and its notes from the ${mediaCtx.t.label.toLowerCase()}?`)) return;
    const { t, block } = mediaCtx;
    closeMedia();
    block.remove();
    t.el.dispatchEvent(new Event('input', { bubbles: true }));
  }

  $('#oteMediaApply').addEventListener('click', applyMedia);
  $('#oteMediaRemove').addEventListener('click', removeMedia);
  $$('[data-action="close"]', mediaModal).forEach((b) => b.addEventListener('click', closeMedia));
  mediaUrl.addEventListener('input', debounce(() => { if (mediaCtx) renderMediaPreview(mediaCtx.kind, mediaUrl.value.trim()); }, 400));
  mediaUrl.addEventListener('keydown', (e) => { if (e.key === 'Enter') { e.preventDefault(); applyMedia(); } });
  mediaModal.addEventListener('keydown', (e) => {
    if (e.key === 'Escape') { e.stopPropagation(); closeMedia(); }
    if ((e.metaKey || e.ctrlKey) && e.key === 'Enter') { e.preventDefault(); applyMedia(); }
  });
  mediaModal.addEventListener('mousedown', (e) => { if (e.target === mediaModal) closeMedia(); });

  // ------------------------------------------------------------------ verse texts
  // Every OT book has a paraphrase; Genesis also stores its RBT Hebrew literal as text.
  // Each text saves on its own (autosave, conflict check); the toolbar acts on the active one.
  // Attributes other scripts on the page add to live content (base.html's tooltip set-up
  // marks every .tooltip-container). They describe the page, not the verse, so never save them.
  const FOREIGN_ATTRS = ['contenteditable', 'spellcheck', 'draggable', 'data-tooltip-init', 'data-ote-label'];

  const saveBtn = $('#oteSave');
  const literalEl = $('#oteLiteral');
  const activeLabel = $('#oteActiveText');
  const texts = $$('.ote-text').map(makeText);
  const textByEl = new Map(texts.map((t) => [t.el, t]));
  const textByKey = Object.fromEntries(texts.map((t) => [t.key, t]));
  let activeText = textByKey.paraphrase || texts[0] || null;

  function setActiveText(text) {
    if (!text) return;
    activeText = text;
    texts.forEach((t) => t.section.classList.toggle('is-active', t === text));
    if (activeLabel) activeLabel.textContent = text.label;
  }

  function cleanHtml(root) {
    $$('.ote-insert-flash', root).forEach((n) => n.classList.remove('ote-insert-flash'));
    $$('.is-selected', root).forEach((n) => n.classList.remove('is-selected'));
    FOREIGN_ATTRS.forEach((a) => $$(`[${a}]`, root).forEach((n) => n.removeAttribute(a)));
    $$('[class=""]', root).forEach((n) => n.removeAttribute('class'));
    return root.innerHTML.trim().replace(/(<br\s*\/?>)+$/i, '').trim();
  }

  /** The text to save: in the HTML view exactly what was typed, otherwise the rendered text. */
  function serialize(t) {
    if (t.source && !t.source.hidden) return t.source.value.trim();
    return cleanHtml(t.el.cloneNode(true));
  }

  function setStatus(t, kind, text) {
    t.status.className = `ote-status ote-status--${kind}`;
    t.status.textContent = text;
  }

  const isDirty = (t) => serialize(t) !== t.lastSavedHtml;

  function changedSinceLoad(t) {
    return t.lastSavedHtml !== t.loadedRendered || serialize(t) !== t.loadedRendered;
  }

  function refreshDirty(t) {
    if (t.resetBtn) {
      t.resetBtn.disabled = !t.pendingConflict && !changedSinceLoad(t);
      t.resetBtn.title = t.resetBtn.disabled ? 'No changes since you opened the page'
        : 'Reset to how it was when you opened the page';
    }
    if (t.saving) return;
    if (t.pendingConflict) { setStatus(t, 'conflict', 'Conflict'); return; }
    if (isDirty(t)) setStatus(t, 'dirty', t.suppressAutosave ? 'Unsaved · press Save to keep the suggestion' : 'Unsaved');
    else setStatus(t, 'saved', 'Saved');
  }

  // exactHtml: send this text as is (Reset sends the page-load original byte for byte);
  // otherwise the rendered text.
  async function save(t, exactHtml) {
    if (t.saving) return;
    const html = exactHtml === undefined ? serialize(t) : exactHtml;
    if (exactHtml === undefined && html === t.lastSavedHtml) { refreshDirty(t); return; }
    t.saving = true;
    t.autosave.cancel();
    setStatus(t, 'saving', 'Saving…');
    try {
      const data = await call(api.apiVerse, { method: 'POST', body: { verse_ref: api.verseRef, field: t.key, html, base_hash: t.baseHash } });
      t.baseHash = data.hash;
      t.lastSavedHtml = exactHtml === undefined ? html : serialize(t);
      t.suppressAutosave = false;
      t.saving = false;
      refreshDirty(t);
      if (t.key === 'paraphrase') refreshChapterRow(html);
      if (exactHtml !== undefined) toast(`${t.label} reset to how it was when you opened the page.`);
    } catch (err) {
      t.saving = false;
      if (err.status === 409 && err.data) {
        t.pendingConflict = err.data;
        t.conflictBar.hidden = false;
        setStatus(t, 'conflict', 'Conflict');
      } else {
        setStatus(t, 'error', `Not saved: ${err.message}`);
        toast(`${t.label} not saved: ${err.message}`, true);
      }
    }
  }

  async function saveAll() {
    saveBtn.disabled = true;
    try { await Promise.all(texts.map((t) => save(t))); } finally { saveBtn.disabled = false; }
  }

  function setHtml(t, html) {
    t.el.innerHTML = html;
    prepareMedia(t.el);
    t.source.value = html;
  }

  function makeText(section) {
    const t = {
      section,
      key: section.dataset.field,
      label: section.dataset.label,
      el: $('.ote-verse', section),
      source: $('.ote-source', section),
      status: $('.ote-status', section),
      conflictBar: $('.ote-conflict', section),
      sourceToggle: $('[data-act="source"]', section),
      baseHash: section.dataset.hash,
      saving: false,
      suppressAutosave: false,
      pendingConflict: null,
    };
    prepareMedia(t.el);
    // Image blocks open the image pop-up. Capture phase: base.html's tooltip script stops
    // clicks on these blocks from bubbling on touch screens.
    t.el.addEventListener('click', (e) => {
      const block = e.target.closest('.tooltip-container');
      if (!block || !t.el.contains(block) || block.parentElement.closest('.tooltip, .tooltip2')) return;
      e.preventDefault();
      e.stopPropagation();
      setActiveText(t);
      openMedia({ t, block });
    }, true);
    // Compare against the browser's own rendering of the stored HTML, so harmless
    // normalisation (attribute quoting, entities) never reads as an unsaved change.
    t.lastSavedHtml = serialize(t);
    // What Reset returns to: the text as stored when the page loaded, exactly (the
    // HTML view holds it unaltered), and the browser's rendering of it for comparisons.
    t.loadedHtml = t.source.value.trim();
    t.loadedRendered = t.lastSavedHtml;
    t.resetBtn = $('[data-act="reset"]', section);
    t.autosave = debounce(() => { if (!t.suppressAutosave && !t.pendingConflict) save(t); }, 1500);

    t.el.addEventListener('focus', () => setActiveText(t));
    t.source.addEventListener('focus', () => setActiveText(t));
    t.el.addEventListener('input', () => {
      if (!t.source.hidden) return;
      t.source.value = cleanHtml(t.el.cloneNode(true));
      refreshDirty(t);
      t.autosave();
    });
    t.source.addEventListener('input', () => {
      t.el.innerHTML = t.source.value;
      prepareMedia(t.el);
      refreshDirty(t);
      t.autosave();
    });

    $('[data-act="conflict-load"]', section).addEventListener('click', () => {
      if (!t.pendingConflict) return;
      setHtml(t, t.pendingConflict.html || '');
      t.baseHash = t.pendingConflict.hash;
      t.lastSavedHtml = serialize(t);
      t.pendingConflict = null;
      t.conflictBar.hidden = true;
      t.suppressAutosave = false;
      refreshDirty(t);
      toast(`Loaded the stored ${t.label.toLowerCase()}.`);
    });
    $('[data-act="conflict-keep"]', section).addEventListener('click', () => {
      if (!t.pendingConflict) return;
      t.baseHash = t.pendingConflict.hash;
      t.pendingConflict = null;
      t.conflictBar.hidden = true;
      save(t);
    });

    t.sourceToggle.addEventListener('click', () => {
      const showingSource = !t.source.hidden;
      if (showingSource) {
        const unchanged = t.source.value.trim() === t.lastSavedHtml;
        t.el.innerHTML = t.source.value;
        prepareMedia(t.el);
        t.source.hidden = true; t.el.hidden = false;
        // Back in the rendered view the browser re-serialises the HTML; if nothing was edited,
        // take that form as the saved baseline so it doesn't read as a change.
        if (unchanged) t.lastSavedHtml = serialize(t);
        refreshDirty(t);
        t.el.focus();
      } else {
        t.source.value = cleanHtml(t.el.cloneNode(true));
        t.el.hidden = true; t.source.hidden = false;
        t.source.focus();
      }
      t.sourceToggle.setAttribute('aria-pressed', String(!showingSource));
      setActiveText(t);
    });

    t.resetBtn.addEventListener('click', () => {
      if (!changedSinceLoad(t)) { toast(`No changes to the ${t.label.toLowerCase()} since you opened the page.`); return; }
      const saved = t.lastSavedHtml !== t.loadedRendered;
      if (!window.confirm(`Reset the ${t.label.toLowerCase()} to how it was when you opened this page?` +
        (saved ? '\n\nYour edits were already saved, so the original is saved back.' : ''))) return;
      t.autosave.cancel();
      t.suppressAutosave = false;
      setHtml(t, t.loadedHtml);
      if (saved) save(t, t.loadedHtml);
      else { t.lastSavedHtml = serialize(t); refreshDirty(t); }
    });
    return t;
  }

  function refreshChapterRow(html) {
    const row = document.getElementById('chapter-verse-' + api.verse);
    if (row) $('.ote-chapter__text', row).innerHTML = html;
  }

  if (saveBtn) saveBtn.addEventListener('click', saveAll);
  document.addEventListener('keydown', (e) => {
    if ((e.metaKey || e.ctrlKey) && e.key.toLowerCase() === 's') { e.preventDefault(); saveAll(); }
  });
  window.addEventListener('beforeunload', (e) => {
    if (texts.some(isDirty) || $$('.ote-footnote__status.is-dirty').length) { e.preventDefault(); e.returnValue = ''; }
  });

  // ------------------------------------------------------------------ insert popover
  const pop = $('#oteInsertPop');
  const popToken = $('#oteInsertToken');
  let popKind = null;

  // Only the footnote marker uses this popover; images and videos use the image pop-up.
  function openPop(kind, anchor) {
    popKind = kind;
    pop.hidden = false;
    const r = anchor.getBoundingClientRect();
    pop.style.top = Math.min(window.innerHeight - pop.offsetHeight - 12, r.bottom + 8) + 'px';
    pop.style.left = Math.max(8, Math.min(window.innerWidth - pop.offsetWidth - 8, r.left)) + 'px';
    popToken.focus();
  }
  function closePop() { pop.hidden = true; popKind = null; }

  function nextMarkerNumber() {
    return $$('a.sdfootnoteanc', activeText.el).length + 1;
  }
  function markerHtml(card) {
    return `<a class="sdfootnoteanc" href="${escapeHtml(card.dataset.marker)}"><sup>${nextMarkerNumber()}</sup></a>`;
  }

  $$('[data-insert]').forEach((button) => {
    button.addEventListener('mousedown', (e) => e.preventDefault());
    button.addEventListener('click', () => {
      const kind = button.dataset.insert;
      if (kind === 'literal') {
        insertHtml(activeText.el, literalEl.innerHTML.trim());
        activeText.el.dispatchEvent(new Event('input', { bubbles: true }));
        return;
      }
      if (kind === 'image' || kind === 'video') {
        const range = rangeIn(activeText.el);
        openMedia({ t: activeText, kind, range: range ? range.cloneRange() : null });
        return;
      }
      openPop(kind, button);
    });
  });
  $('#oteInsertGo').addEventListener('click', () => {
    if (popKind !== 'marker') return;
    const card = cardOf(popToken.value);
    if (!card) return;
    const html = markerHtml(card);
    closePop();
    insertHtml(activeText.el, html);
    activeText.el.dispatchEvent(new Event('input', { bubbles: true }));
  });
  popToken.addEventListener('keydown', (e) => { if (e.key === 'Enter') { e.preventDefault(); $('#oteInsertGo').click(); } });
  $$('[data-close-pop]').forEach((b) => b.addEventListener('click', closePop));
  document.addEventListener('mousedown', (e) => { if (!pop.hidden && !pop.contains(e.target) && !e.target.closest('[data-insert]')) closePop(); });

  // ------------------------------------------------------------------ footnote drawers
  $$('.ote-card').forEach((card) => {
    const drawer = $('.ote-footnote', card);
    const editor = $('.ote-footnote__editor', card);
    const fnStatus = $('.ote-footnote__status', card);
    const noteBtn = $('[data-act="footnote"]', card);
    let lastSaved = editor.innerHTML.trim();

    function setFnStatus(text, cls) {
      fnStatus.textContent = text;
      fnStatus.className = 'ote-footnote__status' + (cls ? ' ' + cls : '');
    }
    function fnSerialize() {
      const clone = editor.cloneNode(true);
      $$('[contenteditable], [spellcheck]', clone).forEach((n) => { n.removeAttribute('contenteditable'); n.removeAttribute('spellcheck'); });
      return clone.innerHTML.replace(/(<br\s*\/?>)+$/i, '').trim();
    }
    function toggleDrawer(open) {
      drawer.hidden = !open;
      card.classList.toggle('has-note-open', open);
      if (open) { card.scrollIntoView({ behavior: 'smooth', block: 'nearest' }); editor.focus(); }
    }

    noteBtn.addEventListener('click', () => toggleDrawer(drawer.hidden));
    $('[data-act="fn-close"]', card).addEventListener('click', () => {
      if (fnSerialize() !== lastSaved && !window.confirm('Close without saving this footnote?')) return;
      editor.innerHTML = lastSaved;
      setFnStatus('', '');
      toggleDrawer(false);
    });
    editor.addEventListener('input', () => setFnStatus(fnSerialize() === lastSaved ? '' : 'Unsaved', 'is-dirty'));
    editor.addEventListener('keydown', (e) => { if ((e.metaKey || e.ctrlKey) && e.key.toLowerCase() === 's') { e.preventDefault(); e.stopPropagation(); saveFootnote(); } });

    async function saveFootnote() {
      const html = fnSerialize();
      setFnStatus('Saving…', '');
      try {
        const data = await call(api.apiFootnote, { method: 'POST', body: { id: Number(card.dataset.token), html, base_hash: editor.dataset.baseHash } });
        editor.dataset.baseHash = data.hash;
        lastSaved = data.html;
        if (editor.innerHTML.trim() !== data.html) editor.innerHTML = data.html;
        noteBtn.classList.toggle('has-note', !!data.html);
        noteBtn.title = data.html ? "Edit this word's footnote" : 'Add a footnote to this word';
        setFnStatus(data.html ? 'Saved' : 'Removed', 'is-ok');
        noteSaved(markerId, data.html, data.hash, card);
      } catch (err) {
        if (err.status === 409 && err.data) {
          if (window.confirm('This footnote was changed elsewhere. Load the stored version? (Cancel keeps yours; save again to overwrite.)')) {
            editor.innerHTML = err.data.html || '';
            lastSaved = err.data.html || '';
            setFnStatus('Loaded stored version', 'is-ok');
          } else setFnStatus('Conflict · save again to overwrite', 'is-bad');
          editor.dataset.baseHash = err.data.hash;
        } else setFnStatus(`Not saved: ${err.message}`, 'is-bad');
      }
    }
    $('[data-act="fn-save"]', card).addEventListener('click', saveFootnote);
    // The same note saved from the verse's footnote cards: show it here too, unless edited here.
    const markerId = (card.dataset.marker || '').replace('?footnote=', '');
    document.addEventListener('ote:note-saved', (e) => {
      if (e.detail.id !== markerId || e.detail.from === card || fnSerialize() !== lastSaved) return;
      editor.innerHTML = e.detail.html;
      editor.dataset.baseHash = e.detail.hash;
      lastSaved = e.detail.html;
      noteBtn.classList.toggle('has-note', !!e.detail.html);
    });
    $('[data-act="fn-marker"]', card).addEventListener('click', () => {
      insertHtml(activeText.el, markerHtml(card));
      activeText.el.dispatchEvent(new Event('input', { bubbles: true }));
      toast(`Footnote marker inserted into the ${activeText.label.toLowerCase()}.`);
    });
    $('[data-act="fn-copy"]', card).addEventListener('click', (e) => {
      copyText(markerHtml(card)).then(() => { e.target.textContent = 'Copied'; setTimeout(() => { e.target.textContent = 'Copy marker'; }, 1500); });
    });
  });

  // ------------------------------------------------------------------ verse footnotes
  // The notes linked from this verse's texts (?footnote=<id>: Genesis notes, or other books'
  // word notes), edited in place like the NT verse editor's: autosave, the same conflict check
  // as the verse texts, Reset to the text the page loaded with. Clicking a footnote number in a
  // text jumps to its note; a marker added while editing gets its card.
  const NOTE_ID_RE = /\?footnote=([0-9A-Za-z-]+)/g;
  const noteList = $('#oteNoteCards');
  const notesEmpty = $('#oteNotesEmpty');
  const notesById = new Map();

  function noteSaved(id, html, hash, from) {
    if (id) document.dispatchEvent(new CustomEvent('ote:note-saved', { detail: { id, html, hash, from } }));
  }

  function setupNote(card) {
    const id = card.dataset.note;
    const el = $('.ote-fn__text', card);
    const status = $('.ote-fn__status', card);
    const reset = $('[data-act="fn-reset"]', card);
    const serializeNote = () => cleanHtml(el.cloneNode(true));
    const original = serializeNote();
    let saved = original;
    let timer = 0;
    let saving = null;

    function setStatus(text, cls) {
      status.textContent = text;
      status.className = 'ote-fn__status' + (cls ? ' ' + cls : '');
    }
    async function save() {
      window.clearTimeout(timer);
      if (saving) { await saving; }
      const html = serializeNote();
      if (html === saved) { setStatus(saved === original ? '' : 'Saved', saved === original ? '' : 'is-ok'); return; }
      setStatus('Saving…', '');
      saving = call(api.apiVerseNote, { method: 'POST', body: { id, html, base_hash: el.dataset.baseHash } })
        .then((data) => {
          el.dataset.baseHash = data.hash;
          saved = data.html;
          if (serializeNote() === html) setStatus('Saved', 'is-ok'); else setStatus('Unsaved', 'is-dirty');
          noteSaved(id, data.html, data.hash, card);
        })
        .catch((err) => {
          if (err.status === 409 && err.data) {
            el.dataset.baseHash = err.data.hash;
            if (window.confirm(`Footnote ${id} was changed elsewhere. Load the stored version? (Cancel keeps yours; it saves over the stored one with your next edit.)`)) {
              el.innerHTML = err.data.html || '';
              saved = err.data.html || '';
              setStatus('Loaded the stored version', 'is-ok');
            } else setStatus('Changed elsewhere · your next edit overwrites it', 'is-bad');
          } else setStatus(`Not saved: ${err.message}`, 'is-bad');
        })
        .finally(() => { saving = null; reset.disabled = serializeNote() === original; });
      await saving;
    }

    el.addEventListener('input', () => {
      setStatus('Unsaved', 'is-dirty');
      reset.disabled = false;
      window.clearTimeout(timer);
      timer = window.setTimeout(save, 1200);
    });
    el.addEventListener('blur', () => { if (serializeNote() !== saved) save(); });
    el.addEventListener('keydown', (e) => {
      if ((e.metaKey || e.ctrlKey) && e.key.toLowerCase() === 's') { e.preventDefault(); e.stopPropagation(); save(); }
    });
    reset.addEventListener('click', () => {
      el.innerHTML = original;
      save();
    });
    // The same note saved from its word card's drawer.
    document.addEventListener('ote:note-saved', (e) => {
      if (e.detail.id !== id || e.detail.from === card || serializeNote() !== saved) return;
      el.innerHTML = e.detail.html;
      el.dataset.baseHash = e.detail.hash;
      saved = e.detail.html;
    });
    notesById.set(id, card);
  }

  function noteCard(note) {
    const card = document.createElement('article');
    card.className = 'ote-fn';
    card.dataset.note = note.id;
    card.dataset.kind = note.kind;
    card.innerHTML = `
      <div class="ote-fn__head">
        <span class="ote-fn__num">${escapeHtml(note.number)}</span>
        <code class="ote-fn__id">${escapeHtml(note.id)}</code>
        ${note.kind === 'word' ? '<span class="ote-fn__kind" title="This word\'s footnote (the same as its card\'s note)">word note</span>' : ''}
        <span class="ote-fn__status" aria-live="polite"></span>
        <button type="button" class="tb-btn tb-btn--sm tb-btn--ghost" data-act="fn-reset" title="Put back the note as it was when the page loaded" disabled>Reset</button>
      </div>
      <div class="ote-minibar" role="toolbar" aria-label="Footnote formatting">${formatToolbar('hebrew')}</div>
      <div class="ote-fn__text ote-editable rbt-notes tex2jax_ignore" contenteditable="true" spellcheck="true" aria-label="Footnote ${escapeHtml(note.number)}"></div>`;
    const el = $('.ote-fn__text', card);
    el.innerHTML = note.html;
    el.dataset.baseHash = note.hash;
    bindCommands(card);
    return card;
  }

  function linkedNoteIds() {
    const ids = [];
    texts.forEach((t) => {
      for (const m of t.el.innerHTML.matchAll(NOTE_ID_RE)) if (!ids.includes(m[1])) ids.push(m[1]);
    });
    return ids;
  }

  // Cards for markers added while editing (e.g. with Insert → Note), in the texts' order.
  const pendingNotes = new Set();
  async function syncNoteCards() {
    if (!noteList) return;
    const ids = linkedNoteIds();
    for (const id of ids) {
      if (notesById.has(id) || pendingNotes.has(id)) continue;
      pendingNotes.add(id);
      try {
        const note = await call(api.apiVerseNote, { query: { id } });
        if (notesById.has(id)) continue;
        const card = noteCard(note);
        const after = ids.slice(0, ids.indexOf(id)).reverse().map((other) => notesById.get(other)).find(Boolean);
        if (after) after.after(card); else noteList.prepend(card);
        setupNote(card);
      } catch (err) { /* not a note this page can edit (unknown id); the reader shows it as it is */ }
      finally { pendingNotes.delete(id); }
    }
    if (notesEmpty) notesEmpty.hidden = notesById.size > 0;
  }

  function focusNote(id) {
    const card = notesById.get(id);
    if (!card) return false;
    card.scrollIntoView({ behavior: 'smooth', block: 'center' });
    card.classList.add('is-flash');
    window.setTimeout(() => card.classList.remove('is-flash'), 1200);
    const el = $('.ote-fn__text', card);
    el.focus({ preventScroll: true });
    const range = document.createRange();
    range.selectNodeContents(el);
    range.collapse(false);
    const sel = window.getSelection(); sel.removeAllRanges(); sel.addRange(range);
    return true;
  }

  $$('.ote-fn', noteList || document).forEach(setupNote);
  texts.forEach((t) => {
    // A footnote number in a text opens its note rather than following the link.
    t.el.addEventListener('click', (e) => {
      const link = e.target.closest && e.target.closest('a[href*="footnote="]');
      const m = link && /\?footnote=([0-9A-Za-z-]+)/.exec(link.getAttribute('href') || '');
      if (!m) return;
      e.preventDefault();
      if (!focusNote(m[1])) syncNoteCards().then(() => focusNote(m[1]));
    });
    t.el.addEventListener('input', debounce(syncNoteCards, 800));
  });

  // ------------------------------------------------------------------ panels
  const panels = { chapter: $('#otePanelChapter'), lexicon: $('#otePanelLexicon') };
  const scrim = $('.ote-scrim');
  function openPanel(name) {
    Object.entries(panels).forEach(([key, panel]) => {
      const open = key === name;
      panel.classList.toggle('is-open', open);
      panel.setAttribute('aria-hidden', String(!open));
    });
    scrim.hidden = false;
    if (name === 'chapter') {
      const row = $('.ote-chapter__row.is-current', panels.chapter);
      if (row) setTimeout(() => row.scrollIntoView({ block: 'center' }), 300);
    }
  }
  function closePanels() {
    Object.values(panels).forEach((panel) => { panel.classList.remove('is-open'); panel.setAttribute('aria-hidden', 'true'); });
    scrim.hidden = true;
  }
  $$('[data-toggle-panel]').forEach((b) => b.addEventListener('click', () => {
    const name = b.dataset.togglePanel;
    panels[name].classList.contains('is-open') ? closePanels() : openPanel(name);
  }));
  $$('[data-close-panel]').forEach((b) => b.addEventListener('click', closePanels));

  // A click outside the open side panel closes it, except on what opens or drives a panel
  // (lexicon chips, map icons, the top bar's panel buttons) and in pop-ups the panel opens.
  // Only when the press also began outside, so selecting text in the panel and releasing
  // past its edge doesn't close it.
  let pressedInPanel = false;
  document.addEventListener('pointerdown', (e) => {
    pressedInPanel = Object.values(panels).some((p) => p.contains(e.target));
  }, true);
  document.addEventListener('click', (e) => {
    const openPanelEl = Object.values(panels).find((p) => p.classList.contains('is-open'));
    if (!openPanelEl || pressedInPanel || !document.contains(e.target) || openPanelEl.contains(e.target)) return;
    if (e.target.closest('.ote-card__lex .popup-container, [data-act="map"], [data-toggle-panel], .gemini-modal, .ote-pop, .ote-toast')) return;
    closePanels();
  });
  document.addEventListener('keydown', (e) => {
    if (e.key !== 'Escape') return;
    if (!pop.hidden) { closePop(); return; }
    if ($('.gemini-modal.is-visible')) return;
    closePanels();
  });
  $('#oteChapterSelect')?.addEventListener('change', (e) => {
    window.location.href = `?book=${encodeURIComponent(api.book)}&chapter=${e.target.value}&verse=1`;
  });

  // Panel tabs
  function showTab(name) {
    $$('.ote-tab', panels.lexicon).forEach((t) => t.classList.toggle('is-active', t.dataset.tab === name));
    $$('.ote-tabpane', panels.lexicon).forEach((p) => p.classList.toggle('is-active', p.dataset.pane === name));
  }
  $$('.ote-tab').forEach((t) => t.addEventListener('click', () => showTab(t.dataset.tab)));

  // ------------------------------------------------------------------ lexicon panel
  const lexTitle = $('#oteLexTitle'), lexWord = $('#oteLexWord'), lexChips = $('#oteLexChips'), lexContent = $('#oteLexContent');
  let lexCard = null;

  // Short chip labels keep a card's lexicon row on one line; the full name stays for the
  // tooltip and the side panel.
  const CHIP_SHORT = { STRONGS: "Strong's", 'FÜRST': 'Fürst', GESENIUS: 'Ges.', BDB: 'BDB', LXX: 'LXX' };
  $$('.ote-card__lex .popup-container > :first-child').forEach((trigger) => {
    const full = trigger.textContent.trim();
    trigger.dataset.full = full;
    trigger.title = { STRONGS: "Strong's", 'FÜRST': 'Fürst', GESENIUS: 'Gesenius', BDB: 'Brown-Driver-Briggs', LXX: 'Septuagint' }[full.toUpperCase()] || full;
    trigger.textContent = CHIP_SHORT[full.toUpperCase()] || full;
  });
  function chipLabel(container) {
    const trigger = container.firstElementChild;
    return trigger ? (trigger.title || trigger.dataset.full || trigger.textContent).trim() : 'Lexicon';
  }

  function showLexicon(card, container) {
    lexCard = card;
    const containers = $$('.ote-card__lex .popup-container', card);
    $$('.ote-card__lex .popup-container.is-open').forEach((c) => c.classList.remove('is-open'));
    container.classList.add('is-open');
    lexWord.textContent = card.dataset.niqqud;
    lexTitle.textContent = `${chipLabel(container)} · ${card.dataset.ref}`;
    lexChips.innerHTML = '';
    containers.forEach((c) => {
      const chip = document.createElement('button');
      chip.type = 'button';
      chip.className = 'ote-chip' + (c === container ? ' is-active' : '');
      if (c === container) chip.style.background = 'var(--ote-gold)', chip.style.color = '#fff', chip.style.borderColor = 'var(--ote-gold)';
      chip.textContent = chipLabel(c);
      chip.addEventListener('click', () => showLexicon(card, c));
      lexChips.appendChild(chip);
    });
    const strongs = card.dataset.strongs;
    if (strongs) {
      const meta = document.createElement('span');
      meta.className = 'ote-muted';
      meta.style.cssText = 'font-size:11px;align-self:center;margin-left:auto;';
      meta.textContent = strongs.split(/[\/|]/).map((s) => s.split(/[=«]/)[0]).join(' · ');
      lexChips.appendChild(meta);
    }
    const content = $('.popup-content', container);
    lexContent.innerHTML = content ? content.innerHTML : '<p class="ote-muted">Nothing to show.</p>';
    showTab('lexicon');
    openPanel('lexicon');
    activateCard(card.dataset.token, false);
  }

  document.addEventListener('click', (e) => {
    const container = e.target.closest('.ote-card__lex .popup-container');
    if (container) {
      e.preventDefault();
      showLexicon(container.closest('.ote-card'), container);
      return;
    }
    const map = e.target.closest('[data-act="map"]');
    if (map) openMap(map.closest('.ote-card'));
  });

  // ------------------------------------------------------------------ consonantal search
  const searchResults = $('#oteSearchResults');
  async function searchConsonantal() {
    const term = $('#oteSearchTerm').value.trim();
    const term2 = $('#oteSearchTerm2').value.trim();
    const btn = $('#oteSearchBtn');
    if (!term) { $('#oteSearchTerm').focus(); return; }
    btn.disabled = true; btn.textContent = 'Searching…';
    searchResults.innerHTML = '<p class="ote-muted">Searching…</p>';
    $('#oteSearchCount').textContent = '';
    try {
      const data = await call(api.apiConsonantal, { method: 'POST', body: { search_term: term, search_term2: term2 } });
      if (!data.results || !data.results.length) { searchResults.innerHTML = '<p class="ote-muted">No results.</p>'; return; }
      searchResults.innerHTML = data.results.map((r) => `
        <div class="ote-result">
          <a class="ote-result__ref" href="?ref=${encodeURIComponent(r.ref)}">${escapeHtml(r.ref)}</a>
          <div class="ote-result__heb">${r.hebrew_highlighted}</div>
        </div>`).join('');
      $('#oteSearchCount').textContent = `${data.count} verse${data.count === 1 ? '' : 's'}`;
    } catch (err) {
      searchResults.innerHTML = `<p style="color:var(--ote-bad)">${escapeHtml(err.message)}</p>`;
    } finally {
      btn.disabled = false; btn.textContent = 'Search';
    }
  }
  $('#oteSearchBtn').addEventListener('click', searchConsonantal);
  ['#oteSearchTerm', '#oteSearchTerm2'].forEach((sel) => $(sel).addEventListener('keydown', (e) => { if (e.key === 'Enter') searchConsonantal(); }));

  // ------------------------------------------------------------------ lexicon mapping
  const mapState = { niqqud: '', consonantal: '' };

  // The strongs field packs morphemes ("H9005=ל=to/H3651c=כֵּן=so"); the mapping is keyed on
  // the first lexical number as H<int>. H9xxx are grammatical markers, used only as a fallback.
  function tokenStrongsNumber(field) {
    if (!field) return '';
    let fallback = '';
    for (const part of String(field).split(/[\/|]/)) {
      for (const seg of part.split(/[=«]/)) {
        const s = seg.trim();
        if (!/^H\d/i.test(s)) continue;
        const digits = s.replace(/\D/g, '');
        if (!digits) continue;
        const canonical = 'H' + parseInt(digits, 10);
        if (parseInt(digits, 10) >= 9000) { if (!fallback) fallback = canonical; continue; }
        return canonical;
      }
    }
    return fallback;
  }

  function openMap(card) {
    mapState.niqqud = card.dataset.niqqud;
    mapState.consonantal = card.dataset.consonantal;
    $('#oteMapNiqqud').textContent = mapState.niqqud;
    $('#oteMapConsonantal').textContent = mapState.consonantal;
    $('#oteMapStrongs').value = tokenStrongsNumber(card.dataset.strongs);
    const prefill = stripVowels(mapState.niqqud) || mapState.consonantal;
    $('#oteMapTerm').value = prefill;
    if (/[֐-׿]/.test(prefill)) $('#oteMapMatch').value = 'root';
    $('#oteMapResults').innerHTML = '';
    lexTitle.textContent = `Map · ${card.dataset.ref}`;
    showTab('map');
    openPanel('lexicon');
    activateCard(card.dataset.token, false);
  }

  function renderLexEntry(entry, type) {
    const meta = [entry.part_of_speech, entry.root ? 'Root: ' + entry.root : '', entry.source_page ? 'Page: ' + entry.source_page : ''].filter(Boolean).map(escapeHtml).join(' · ');
    return `<div class="ote-lex-entry">
      <div class="ote-lex-entry__head">
        <div class="ote-lex-entry__heb" dir="rtl">${escapeHtml(entry.hebrew_word || entry.hebrew_consonantal)}</div>
        <button type="button" class="ote-btn ote-btn--primary" data-add-mapping="${escapeHtml(String(entry.id))}" data-lexicon-type="${type}"><i class="fas fa-plus"></i> Add mapping</button>
      </div>
      <div class="ote-lex-entry__meta">${meta}</div>
      <div class="ote-lex-entry__def">${escapeHtml(entry.definition || 'No definition available')}</div>
    </div>`;
  }

  async function searchLexiconEntries() {
    const results = $('#oteMapResults');
    let term = $('#oteMapTerm').value.trim();
    if (/[֐-׿]/.test(term)) term = stripVowels(term);
    results.innerHTML = '<p class="ote-muted"><i class="fas fa-spinner fa-spin"></i> Searching…</p>';
    try {
      const data = await call(api.apiSearchLexicon, { query: {
        hebrew: mapState.niqqud || mapState.consonantal || '',
        strong: $('#oteMapStrongs').value.trim(),
        lexicon: $('#oteMapLexicon').value,
        match: $('#oteMapMatch').value,
        search: term,
      } });
      if (data.error) throw new Error(data.error);
      let html = '';
      if (data.fuerst && data.fuerst.length) html += `<div class="ote-lex-section"><h5>Fürst</h5>${data.fuerst.map((e) => renderLexEntry(e, 'fuerst')).join('')}</div>`;
      if (data.gesenius && data.gesenius.length) html += `<div class="ote-lex-section"><h5>Gesenius</h5>${data.gesenius.map((e) => renderLexEntry(e, 'gesenius')).join('')}</div>`;
      results.innerHTML = html || '<p class="ote-muted">No matching entries. Try another match mode.</p>';
    } catch (err) {
      results.innerHTML = `<p style="color:var(--ote-bad)">${escapeHtml(err.message)}</p>`;
    }
  }
  $('#oteMapSearch').addEventListener('click', searchLexiconEntries);
  $('#oteMapTerm').addEventListener('keydown', (e) => { if (e.key === 'Enter') searchLexiconEntries(); });
  $('#oteMapTerm').addEventListener('input', debounce(() => {
    const val = $('#oteMapTerm').value.trim();
    if (/^[֐-׿\s]+$/.test(val)) {
      $('#oteMapMatch').value = 'root';
      const stripped = stripVowels(val);
      if (stripped !== val) $('#oteMapTerm').value = stripped;
    }
  }, 150));

  $('#oteMapResults').addEventListener('click', async (e) => {
    const btn = e.target.closest('[data-add-mapping]');
    if (!btn) return;
    const numericId = parseInt(String(btn.dataset.addMapping).replace(/\D/g, ''), 10);
    const strongs = $('#oteMapStrongs').value.trim();
    if (!strongs) { toast("Enter the Strong's number the mapping is saved against.", true); return; }
    const payload = {
      hebrew_word: mapState.niqqud, strong_number: strongs, lexicon_type: btn.dataset.lexiconType,
      book: null, chapter: null, verse: null, notes: 'Global manual mapping for similar lexemes',
    };
    payload[btn.dataset.lexiconType === 'fuerst' ? 'fuerst_id' : 'gesenius_id'] = numericId;
    btn.disabled = true;
    try {
      const data = await call(api.apiAddMapping, { method: 'POST', body: payload });
      if (!data.success) throw new Error(data.error || 'Failed to add mapping');
      btn.innerHTML = '<i class="fas fa-check"></i> Mapped';
      toast('Mapping added. Reload the page to see it on the word card.');
    } catch (err) {
      btn.disabled = false;
      toast(`Mapping not added: ${err.message}`, true);
    }
  });

  // ------------------------------------------------------------------ edit lexicon entry modal
  const editModal = $('#oteEditLexModal');
  const editForm = $('#oteEditLexForm');
  const editStatus = $('#oteEditLexStatus');
  let hebrewInput = null;
  function toggleModal(modal, show) { modal.classList.toggle('is-visible', !!show); modal.setAttribute('aria-hidden', String(!show)); }
  $$('.gemini-modal [data-action="close"]').forEach((b) => b.addEventListener('click', () => toggleModal(b.closest('.gemini-modal'), false)));

  document.addEventListener('click', async (e) => {
    const btn = e.target.closest('.edit-lexicon-btn');
    if (!btn) return;
    e.preventDefault();
    const f = editForm.elements;
    f.lexicon_id.value = btn.dataset.lexiconId || '';
    f.lexicon_type.value = btn.dataset.lexiconType || '';
    f.hebrew_word.value = btn.dataset.hebrewWord || '';
    f.hebrew_consonantal.value = btn.dataset.hebrewConsonantal || '';
    f.part_of_speech.value = btn.dataset.partOfSpeech || '';
    f.definition.value = btn.dataset.definition || '';
    f.root.value = btn.dataset.root || '';
    f.source_page.value = btn.dataset.sourcePage || '';
    f.strongs_numbers.value = 'Loading…';
    editStatus.textContent = '';
    toggleModal(editModal, true);
    try {
      const data = await call(api.apiLexiconStrongs, { query: { lexicon_id: f.lexicon_id.value, lexicon_type: f.lexicon_type.value } });
      f.strongs_numbers.value = data.success && data.strongs_numbers ? data.strongs_numbers.join(', ') : '';
    } catch (err) { f.strongs_numbers.value = ''; }
  });
  editForm.addEventListener('focusin', (e) => { if (e.target.classList.contains('hebrew-input')) hebrewInput = e.target; });
  editForm.addEventListener('click', (e) => {
    const key = e.target.closest('.ote-key');
    if (!key) return;
    e.preventDefault();
    if (key.dataset.act === 'kb-vowels') { const v = $('.ote-keyboard__vowels', editForm); v.hidden = !v.hidden; return; }
    const input = hebrewInput || f_first();
    if (!input) return;
    const start = input.selectionStart, end = input.selectionEnd, value = input.value;
    if (key.dataset.act === 'kb-delete') {
      if (start !== end) input.value = value.slice(0, start) + value.slice(end);
      else if (start > 0) input.value = value.slice(0, start - 1) + value.slice(start);
      input.selectionStart = input.selectionEnd = Math.max(0, start !== end ? start : start - 1);
    } else {
      const ch = key.dataset.char || '';
      input.value = value.slice(0, start) + ch + value.slice(end);
      input.selectionStart = input.selectionEnd = start + ch.length;
    }
    input.focus();
    function f_first() { return editForm.querySelector('.hebrew-input'); }
  });
  editForm.addEventListener('submit', async (e) => {
    e.preventDefault();
    const payload = Object.fromEntries(new FormData(editForm).entries());
    editStatus.textContent = 'Saving…';
    try {
      const data = await call(api.apiUpdateLexicon, { method: 'POST', body: payload });
      if (!data.success) throw new Error(data.error || 'Failed to update entry');
      editStatus.textContent = 'Saved. Reloading to show the change…';
      setTimeout(() => window.location.reload(), 600);
    } catch (err) { editStatus.textContent = err.message; }
  });

  // ------------------------------------------------------------------ AI suggestions
  const defaultPromptEl = document.getElementById('oteDefaultHebrewPrompt');
  const defaultPrompt = defaultPromptEl ? JSON.parse(defaultPromptEl.textContent) : '';
  let currentPrompt = defaultPrompt;
  let currentGeminiModel = api.geminiModel || '';
  const aiPayload = (extra) => Object.assign({ translation_type: 'hebrew', book: api.book, chapter: api.chapter, verse: api.verse }, extra);

  // AI suggestions are paraphrases, so they always land in the paraphrase text (never autosaved).
  const aiTarget = () => textByKey.paraphrase || activeText;
  function loadSuggestion(html) {
    const t = aiTarget();
    setHtml(t, html);
    t.suppressAutosave = true;
    setActiveText(t);
    refreshDirty(t);
  }

  // Gemini
  const gModal = $('#oteGeminiModal'), gPrompt = $('#oteGeminiPrompt'), gModel = $('#oteGeminiModel'), gKey = $('#oteGeminiKey'), gStatus = $('#oteGeminiStatus');
  function resetGemini() {
    gPrompt.value = currentPrompt;
    if (currentGeminiModel && !Array.from(gModel.options).some((o) => o.value === currentGeminiModel)) {
      const opt = document.createElement('option'); opt.value = opt.textContent = currentGeminiModel; gModel.appendChild(opt);
    }
    if (currentGeminiModel) gModel.value = currentGeminiModel;
    gStatus.textContent = '';
  }
  $('#oteGeminiOpen').addEventListener('click', () => { resetGemini(); toggleModal(gModal, true); });
  $('#oteGeminiReset').addEventListener('click', () => { gPrompt.value = defaultPrompt; });
  gModal.querySelectorAll('[data-action="close"]').forEach((b) => b.addEventListener('click', () => { gKey.value = ''; }));
  $('#oteGeminiSavePrompt').addEventListener('click', async () => {
    gStatus.textContent = 'Saving prompt…';
    try {
      const data = await call(api.apiGeminiPrefs, { method: 'POST', body: { translation_type: 'hebrew', prompt: gPrompt.value, model: gModel.value } });
      if (data.error) throw new Error(data.error);
      currentPrompt = gPrompt.value; currentGeminiModel = gModel.value;
      gStatus.textContent = 'Prompt saved.';
    } catch (err) { gStatus.textContent = err.message; }
  });
  $('#oteGeminiRunBtn').addEventListener('click', async () => {
    const run = $('#oteGeminiRunBtn');
    run.disabled = true; gStatus.textContent = 'Requesting suggestion…';
    try {
      const response = await fetch(api.apiGemini, {
        method: 'POST', credentials: 'same-origin',
        headers: { 'Content-Type': 'application/json', 'X-CSRFToken': csrf(), 'X-Requested-With': 'XMLHttpRequest' },
        body: JSON.stringify(aiPayload({ prompt: gPrompt.value, model: gModel.value, api_key: gKey.value || undefined, stream: true })),
      });
      const type = response.headers.get('Content-Type') || '';
      if (!response.ok) {
        const text = await response.text();
        let msg = text;
        try { msg = JSON.parse(text).error || text; } catch (e) { /* plain text */ }
        throw new Error(msg || 'Unable to fetch the Gemini suggestion.');
      }
      toggleModal(gModal, false);
      aiTarget().section.scrollIntoView({ behavior: 'smooth', block: 'center' });
      if (type.includes('application/json')) {
        const data = await response.json();
        if (data.error) throw new Error(data.error);
        loadSuggestion(data.suggestion || '');
      } else {
        const reader = response.body.getReader();
        const decoder = new TextDecoder('utf-8');
        let buffer = '', first = true, done = false;
        setStatus(aiTarget(), 'saving', 'Streaming suggestion…');
        while (!done) {
          const { value, done: finished } = await reader.read();
          done = finished;
          if (!value) continue;
          let chunk = decoder.decode(value, { stream: true });
          if (first && chunk.trim() === '') continue;
          if (first) { chunk = chunk.trimStart(); first = false; }
          buffer += chunk;
          aiTarget().el.innerHTML = buffer;
        }
        loadSuggestion(buffer);
      }
      toast('Suggestion loaded. Edit it and press Save to keep it.');
    } catch (err) {
      gStatus.textContent = err.message;
      toggleModal(gModal, true);
      refreshDirty(aiTarget());
    } finally { run.disabled = false; }
  });

  // ChatGPT
  const cModal = $('#oteChatgptModal'), cModel = $('#oteChatgptModel'), cCustom = $('#oteChatgptCustom'), cCustomField = $('#oteChatgptCustomField'), cPrompt = $('#oteChatgptPrompt'), cStatus = $('#oteChatgptStatus');
  const chatgptModel = () => (cModel.value === '__custom__' ? cCustom.value.trim() : cModel.value) || api.chatgptModel;
  cModel.addEventListener('change', () => { cCustomField.hidden = cModel.value !== '__custom__'; if (!cCustomField.hidden) cCustom.focus(); });
  $('#oteChatgptConfig').addEventListener('click', () => { if (!cPrompt.value.trim()) cPrompt.value = defaultPrompt; cStatus.textContent = ''; toggleModal(cModal, true); });
  $('#oteChatgptReset').addEventListener('click', () => { cPrompt.value = defaultPrompt; });
  async function runChatgpt() {
    const data = await call(api.apiChatgpt, { method: 'POST', body: aiPayload({ model: chatgptModel(), prompt: cPrompt.value.trim() || undefined }) });
    if (data.error) throw new Error(data.error);
    if (data.suggestion) { loadSuggestion(data.suggestion); toast('Suggestion loaded. Edit it and press Save to keep it.'); }
  }
  $('#oteChatgptRun').addEventListener('click', async (e) => {
    const btn = e.currentTarget; const label = btn.textContent;
    btn.disabled = true; btn.textContent = 'Requesting…';
    try { await runChatgpt(); } catch (err) { toast(`ChatGPT: ${err.message}`, true); }
    finally { btn.disabled = false; btn.textContent = label; }
  });
  $('#oteChatgptRunModal').addEventListener('click', async (e) => {
    const btn = e.currentTarget;
    if (!chatgptModel()) { cStatus.textContent = 'Choose a model or enter a custom model id.'; return; }
    btn.disabled = true; cStatus.textContent = `Requesting ${chatgptModel()}…`;
    try { await runChatgpt(); toggleModal(cModal, false); } catch (err) { cStatus.textContent = err.message; }
    finally { btn.disabled = false; }
  });

  $$('[data-copy-request]').forEach((btn) => btn.addEventListener('click', async () => {
    const kind = btn.dataset.copyRequest;
    const label = btn.textContent;
    try {
      const data = await call(kind === 'gemini' ? api.apiGemini : api.apiChatgpt, {
        method: 'POST',
        body: aiPayload(kind === 'gemini'
          ? { prompt: gPrompt.value || undefined, model: gModel.value || undefined, assemble_only: true }
          : { model: chatgptModel(), assemble_only: true }),
      });
      if (data.error) throw new Error(data.error);
      await copyText(data.assembled || '');
      btn.textContent = 'Copied'; setTimeout(() => { btn.textContent = label; }, 1500);
    } catch (err) { toast(`Could not copy the request: ${err.message}`, true); }
  }));

  // ------------------------------------------------------------------ start
  texts.forEach(refreshDirty);
  setActiveText(activeText);
})();
