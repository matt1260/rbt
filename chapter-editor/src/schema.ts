/**
 * Lossless ProseMirror schema for stored verse HTML (new_testament.nt.rbt).
 *
 * Verse HTML is free-form: coloured spans, headings, footnote anchors, tooltip/image
 * blocks, videos. Instead of modelling each construct, the schema is generic:
 *
 *   doc        → block+
 *   block      → one top-level text block. attrs.tag is null for a bare run of inline
 *                content (serialised without a wrapper) or e.g. 'h5' / 'div' / 'p'.
 *   raw_block  → any other top-level element (tooltip containers, videos, lists...),
 *                kept as its original outerHTML and not editable.
 *   raw_inline → inline element that can't hold editable text (footnote anchors,
 *                images, empty icons, blocks nested in inline elements).
 *   hard_break → <br>
 *   el (mark)  → any inline formatting element, with its tag and attributes kept
 *                verbatim, so `<span style="color: blue;">` stays byte-identical.
 *                Each parsed element gets a unique `key`, so two adjacent identical
 *                spans (common for centred lines) stay two spans instead of merging.
 *
 * Attributes are always written with setAttribute: ProseMirror's own renderer sets
 * `style` through cssText, which rewrites `#ff00aa` as `rgb(255, 0, 170)`.
 *
 * parseVerse() and serializeDoc() are inverses up to whitespace collapsing, which
 * roundTrips() checks before a verse is allowed into the editor.
 */
import {
  DOMParser as PMDOMParser,
  DOMSerializer,
  Schema,
  type Mark,
  type Node as PMNode,
} from 'prosemirror-model'

export type ElAttrs = Record<string, string>
export interface ElSpec {
  tag: string
  attrs: ElAttrs
}

const BLOCK_TAGS = new Set([
  'address', 'article', 'aside', 'blockquote', 'center', 'details', 'dialog', 'dd', 'div',
  'dl', 'dt', 'fieldset', 'figcaption', 'figure', 'footer', 'form', 'h1', 'h2', 'h3', 'h4',
  'h5', 'h6', 'header', 'hr', 'li', 'main', 'nav', 'ol', 'p', 'pre', 'section', 'table',
  'ul', 'video', 'audio', 'iframe',
])
// Top-level blocks that become editable text blocks when they hold only inline content.
const TEXT_BLOCK_TAGS = new Set(['h1', 'h2', 'h3', 'h4', 'h5', 'h6', 'p', 'div', 'center', 'blockquote'])
// Inline formatting elements represented as `el` marks.
const MARK_TAGS = [
  'span', 'b', 'strong', 'i', 'em', 'u', 's', 'strike', 'sub', 'sup', 'font', 'small', 'big',
  'q', 'a', 'mark', 'abbr', 'cite', 'code', 'del', 'ins', 'kbd', 'var', 'bdi', 'bdo', 'dfn', 'time',
]
const MARK_TAG_SET = new Set(MARK_TAGS)

const ATOM_TAG = 'rbt-atom'
const WHITESPACE_RUN = /[ \t\n\r\f]+/g

export function elementAttrs(el: Element): ElAttrs {
  const attrs: ElAttrs = {}
  for (const attr of Array.from(el.attributes)) attrs[attr.name] = attr.value
  return attrs
}

function htmlToElement(html: string, doc: Document): Node {
  const tpl = doc.createElement('template')
  tpl.innerHTML = html
  return tpl.content.firstChild ?? doc.createTextNode('')
}

function createElement(tag: string, attrs: ElAttrs, doc: Document): HTMLElement {
  const el = doc.createElement(tag)
  for (const [name, value] of Object.entries(attrs)) el.setAttribute(name, value)
  return el
}

let nextMarkKey = 1
export function newMarkKey(): number {
  return nextMarkKey++
}

export const schema = new Schema({
  nodes: {
    doc: { content: 'block+' },
    block: {
      group: 'block',
      content: 'inline*',
      attrs: { tag: { default: null }, attrs: { default: {} } },
      toDOM: (node) => {
        const el = node.attrs.tag
          ? createElement(node.attrs.tag, node.attrs.attrs, document)
          : createElement('span', { class: 'rbt-run' }, document)
        return { dom: el, contentDOM: el }
      },
    },
    raw_block: {
      group: 'block',
      atom: true,
      selectable: false,
      attrs: { html: { default: '' } },
      // Rendered as the element itself so tooltips/images keep their exact layout.
      toDOM: (node) => {
        const el = htmlToElement(node.attrs.html, document)
        if (el instanceof HTMLElement) el.contentEditable = 'false'
        return el as HTMLElement
      },
    },
    text: { group: 'inline' },
    hard_break: {
      group: 'inline',
      inline: true,
      selectable: false,
      parseDOM: [{ tag: 'br' }],
      toDOM: () => ['br'],
    },
    raw_inline: {
      group: 'inline',
      inline: true,
      atom: true,
      attrs: { html: { default: '' } },
      parseDOM: [{ tag: ATOM_TAG, getAttrs: (dom) => ({ html: (dom as HTMLElement).getAttribute('data-html') ?? '' }) }],
      toDOM: (node) => {
        const wrap = document.createElement('span')
        wrap.className = 'rbt-raw-inline'
        wrap.contentEditable = 'false'
        wrap.appendChild(htmlToElement(node.attrs.html, document))
        return wrap
      },
    },
  },
  marks: {
    el: {
      attrs: { tag: { default: 'span' }, attrs: { default: {} }, key: { default: 0 } },
      // Several el marks can overlap (a colour span inside a greek-header span).
      excludes: '',
      parseDOM: [{
        tag: MARK_TAGS.join(','),
        getAttrs: (el: HTMLElement) => ({ tag: el.tagName.toLowerCase(), attrs: elementAttrs(el), key: newMarkKey() }),
      }],
      toDOM: (mark) => {
        const el = createElement(mark.attrs.tag, mark.attrs.attrs, document)
        return { dom: el, contentDOM: el }
      },
    },
  },
})

// ---------------------------------------------------------------------------
// Parsing

function isFootnoteAnchor(el: Element): boolean {
  return el.tagName === 'A' && (el.classList.contains('sdfootnoteanc') || (el.getAttribute('href') ?? '').includes('footnote='))
}

function hasBlockDescendant(el: Element): boolean {
  return Array.from(el.querySelectorAll('*')).some((child) => BLOCK_TAGS.has(child.tagName.toLowerCase()))
}

function makeAtom(el: Element, doc: Document): Element {
  const atom = doc.createElement(ATOM_TAG)
  atom.setAttribute('data-html', el.outerHTML)
  return atom
}

/**
 * Prepare inline content for the ProseMirror parser: collapse whitespace runs (as the
 * browser does when rendering) and swap anything that can't be an editable mark for an
 * atom placeholder.
 */
function prepareInline(node: Node, doc: Document): Node | null {
  if (node.nodeType === 3) {
    return doc.createTextNode((node.nodeValue ?? '').replace(WHITESPACE_RUN, ' '))
  }
  if (node.nodeType !== 1) return null // comments etc.
  const el = node as Element
  const tag = el.tagName.toLowerCase()
  if (tag === 'br') return el.cloneNode(false)
  if (!MARK_TAG_SET.has(tag) || isFootnoteAnchor(el) || !(el.textContent ?? '').trim() || hasBlockDescendant(el)) {
    return makeAtom(el, doc)
  }
  const copy = el.cloneNode(false) as Element
  for (const child of Array.from(el.childNodes)) {
    const prepared = prepareInline(child, doc)
    if (prepared) copy.appendChild(prepared)
  }
  return copy
}

export function parseVerse(html: string, doc: Document): PMNode {
  const container = doc.createElement('div')
  container.innerHTML = html
  const parser = PMDOMParser.fromSchema(schema)
  const blocks: PMNode[] = []
  let run: Node[] = []

  const parseInto = (nodes: Node[], tag: string | null, attrs: ElAttrs) => {
    const holder = doc.createElement('div')
    for (const child of nodes) {
      const prepared = prepareInline(child, doc)
      if (prepared) holder.appendChild(prepared)
    }
    blocks.push(parser.parse(holder, {
      topNode: schema.nodes.block.create({ tag, attrs }),
      preserveWhitespace: 'full',
    }))
  }
  const flushRun = () => {
    if (run.length) parseInto(run, null, {})
    run = []
  }

  for (const child of Array.from(container.childNodes)) {
    const tag = child.nodeType === 1 ? (child as Element).tagName.toLowerCase() : ''
    if (!BLOCK_TAGS.has(tag)) {
      run.push(child)
      continue
    }
    flushRun()
    const el = child as Element
    if (TEXT_BLOCK_TAGS.has(tag) && !hasBlockDescendant(el) && (el.textContent ?? '').trim()) {
      parseInto(Array.from(el.childNodes), tag, elementAttrs(el))
    } else {
      blocks.push(schema.nodes.raw_block.create({ html: el.outerHTML }))
    }
  }
  flushRun()
  if (!blocks.length) blocks.push(schema.nodes.block.create({ tag: null, attrs: {} }))
  return schema.nodes.doc.create(null, blocks)
}

// ---------------------------------------------------------------------------
// Serialising

function inlineSerializer(doc: Document): DOMSerializer {
  return new DOMSerializer(
    {
      // DOMOutputSpec accepts any DOM node; its type only admits elements.
      text: (node) => doc.createTextNode(node.text ?? '') as unknown as HTMLElement,
      hard_break: () => doc.createElement('br'),
      raw_inline: (node) => htmlToElement(node.attrs.html, doc) as HTMLElement,
    },
    {
      el: (mark: Mark) => {
        const el = createElement(mark.attrs.tag, mark.attrs.attrs, doc)
        return { dom: el, contentDOM: el }
      },
    },
  )
}

export function serializeDoc(pmDoc: PMNode, doc: Document): string {
  const out = doc.createElement('div')
  const serializer = inlineSerializer(doc)
  pmDoc.forEach((block) => {
    if (block.type === schema.nodes.raw_block) {
      out.appendChild(htmlToElement(block.attrs.html, doc))
      return
    }
    const inline = serializer.serializeFragment(block.content, { document: doc })
    if (block.attrs.tag) {
      const el = createElement(block.attrs.tag, block.attrs.attrs, doc)
      el.appendChild(inline)
      out.appendChild(el)
    } else {
      out.appendChild(inline)
    }
  })
  return out.innerHTML
}

// ---------------------------------------------------------------------------
// Round-trip guard

/** Canonical form for comparing verse HTML: browser-serialised, whitespace runs collapsed. */
export function normalizeHtml(html: string, doc: Document): string {
  const container = doc.createElement('div')
  container.innerHTML = html
  const walker = doc.createTreeWalker(container, 4 /* NodeFilter.SHOW_TEXT */)
  const texts: Text[] = []
  while (walker.nextNode()) texts.push(walker.currentNode as Text)
  for (const text of texts) {
    const value = (text.nodeValue ?? '').replace(WHITESPACE_RUN, ' ')
    if (value) text.nodeValue = value
    else text.remove()
  }
  return container.innerHTML
}

/** True when the editor would store this verse back unchanged (modulo whitespace). */
export function roundTrips(html: string, doc: Document): boolean {
  try {
    return normalizeHtml(serializeDoc(parseVerse(html, doc), doc), doc) === normalizeHtml(html, doc)
  } catch {
    return false
  }
}

export function sameHtml(a: string, b: string, doc: Document): boolean {
  return a === b || normalizeHtml(a, doc) === normalizeHtml(b, doc)
}
