/**
 * Formatting tools for the floating toolbar. They mirror the buttons on the verse edit
 * page (translate/templates/edit_nt_verse.html) and produce the same markup.
 *
 * With an empty selection a tool applies to the word under the caret.
 */
import { Fragment, type Mark, type MarkType, type Node as PMNode } from 'prosemirror-model'
import { EditorState, TextSelection, type Transaction } from 'prosemirror-state'
import type { EditorView } from 'prosemirror-view'
import { newMarkKey, schema, type ElAttrs, type ElSpec } from './schema'

export type Tool =
  | { kind: 'mark'; id: string; label: string; title: string; spec: ElSpec; aliases?: ElSpec[] }
  | { kind: 'color'; id: string; label: string; title: string; spec: ElSpec | null }
  | { kind: 'block'; id: string; label: string; title: string; spec: ElSpec }

const span = (attrs: ElAttrs): ElSpec => ({ tag: 'span', attrs })

export const TOOLS: Tool[] = [
  { kind: 'color', id: 'pink', label: '', title: 'Pink text', spec: span({ style: 'color: #ff00aa;' }) },
  { kind: 'color', id: 'blue', label: '', title: 'Blue text', spec: span({ style: 'color: blue;' }) },
  { kind: 'color', id: 'nocolor', label: '⌀', title: 'Remove color', spec: null },
  { kind: 'mark', id: 'bold', label: 'B', title: 'Bold (⌘B)', spec: { tag: 'strong', attrs: {} }, aliases: [{ tag: 'b', attrs: {} }] },
  { kind: 'mark', id: 'hayah', label: 'היה', title: 'Hayah', spec: span({ class: 'hayah' }) },
  { kind: 'block', id: 'h5', label: 'h5', title: 'Heading', spec: { tag: 'h5', attrs: {} } },
  { kind: 'mark', id: 'hebrew-header', label: 'א', title: 'Hebrew header', spec: span({ class: 'hebrew-header' }) },
  { kind: 'mark', id: 'greek-header', label: 'Ω', title: 'Greek header', spec: span({ class: 'greek-header' }) },
  { kind: 'mark', id: 'center', label: '≡', title: 'Center line', spec: span({ style: 'display: block; text-align: center;' }) },
  { kind: 'mark', id: 'last-center', label: '≡ₗ', title: 'Center last line', spec: span({ class: 'last_center' }) },
  { kind: 'block', id: 'sun', label: '☀', title: 'Sun', spec: { tag: 'div', attrs: { class: 'sun-icon' } } },
]

function sameAttrs(a: ElAttrs, b: ElAttrs): boolean {
  const keys = Object.keys(a)
  return keys.length === Object.keys(b).length && keys.every((k) => a[k] === b[k])
}

function matches(mark: Mark, spec: ElSpec): boolean {
  return mark.type === schema.marks.el && mark.attrs.tag === spec.tag && sameAttrs(mark.attrs.attrs, spec.attrs)
}

/** A plain color span: `<span style="color: …;">` with no other attributes or declarations. */
function isColor(mark: Mark): boolean {
  if (mark.type !== schema.marks.el || mark.attrs.tag !== 'span') return false
  const attrs = mark.attrs.attrs as ElAttrs
  const keys = Object.keys(attrs)
  return keys.length === 1 && keys[0] === 'style' && /^\s*color\s*:[^;]*;?\s*$/i.test(attrs.style)
}

function createMark(spec: ElSpec): Mark {
  return (schema.marks.el as MarkType).create({ tag: spec.tag, attrs: spec.attrs, key: newMarkKey() })
}

const WORD_CHAR = /[\p{L}\p{M}\p{N}'’\-]/u

/** The selection, or the word around an empty caret. Null if there's nothing to format. */
export function targetRange(state: EditorState): { from: number; to: number } | null {
  const { from, to, empty, $from } = state.selection
  if (!empty) return { from, to }
  const parent = $from.parent
  if (!parent.isTextblock) return null
  const start = $from.start()
  const text = parent.textBetween(0, parent.content.size, undefined, '￼')
  let left = $from.parentOffset
  let right = $from.parentOffset
  while (left > 0 && WORD_CHAR.test(text[left - 1])) left--
  while (right < text.length && WORD_CHAR.test(text[right])) right++
  return left === right ? null : { from: start + left, to: start + right }
}

function marksInRange(state: EditorState, from: number, to: number, keep: (mark: Mark) => boolean): Mark[] {
  const found: Mark[] = []
  state.doc.nodesBetween(from, to, (node) => {
    for (const mark of node.marks) if (keep(mark) && !found.includes(mark)) found.push(mark)
  })
  return found
}

/** True when every text character in the range carries a mark matching one of the specs. */
function rangeHasMark(state: EditorState, from: number, to: number, specs: ElSpec[]): boolean {
  let sawText = false
  let all = true
  state.doc.nodesBetween(from, to, (node) => {
    if (!node.isText) return
    sawText = true
    if (!node.marks.some((mark) => specs.some((spec) => matches(mark, spec)))) all = false
  })
  return sawText && all
}

function currentBlock(state: EditorState) {
  const { $from } = state.selection
  return { node: $from.parent, pos: $from.before() }
}

export function isToolActive(state: EditorState, tool: Tool): boolean {
  if (tool.kind === 'block') {
    const { node } = currentBlock(state)
    return node.attrs.tag === tool.spec.tag && sameAttrs(node.attrs.attrs ?? {}, tool.spec.attrs)
  }
  if (!tool.spec) return false
  const range = targetRange(state)
  if (!range) {
    const marks = state.storedMarks ?? state.selection.$from.marks()
    return marks.some((mark) => matches(mark, tool.spec!))
  }
  return rangeHasMark(state, range.from, range.to, [tool.spec, ...(tool.kind === 'mark' ? tool.aliases ?? [] : [])])
}

/** Build the transaction for a toolbar click, or null when the tool can't apply here. */
export function applyTool(state: EditorState, tool: Tool): Transaction | null {
  if (tool.kind === 'block') return toggleBlock(state, tool.spec)
  const range = targetRange(state)
  if (!range) return null
  const { from, to } = range
  const tr = state.tr

  if (tool.kind === 'color') {
    for (const mark of marksInRange(state, from, to, isColor)) tr.removeMark(from, to, mark)
    if (tool.spec) tr.addMark(from, to, createMark(tool.spec))
  } else {
    const specs = [tool.spec, ...(tool.aliases ?? [])]
    if (rangeHasMark(state, from, to, specs)) {
      for (const mark of marksInRange(state, from, to, (m) => specs.some((s) => matches(m, s)))) tr.removeMark(from, to, mark)
    } else {
      tr.addMark(from, to, createMark(tool.spec))
    }
  }
  // Keep the caret where it was; a word-expanded range shouldn't turn into a selection.
  return tr.setSelection(TextSelection.create(tr.doc, state.selection.from, state.selection.to)).scrollIntoView()
}

/**
 * Wrap the target range in its own block (e.g. <h5>), splitting the surrounding text
 * block around it. Applied inside a block that already has that tag, it unwraps.
 */
function toggleBlock(state: EditorState, spec: ElSpec): Transaction | null {
  const { node, pos } = currentBlock(state)
  const tr = state.tr
  if (node.attrs.tag === spec.tag && sameAttrs(node.attrs.attrs ?? {}, spec.attrs)) {
    return tr.setNodeMarkup(pos, undefined, { tag: null, attrs: {} })
  }
  const range = targetRange(state)
  if (!range) return null
  const $from = state.doc.resolve(range.from)
  const $to = state.doc.resolve(range.to)
  if ($from.parent !== $to.parent) return null

  if (range.to < $to.end()) tr.split(range.to)
  if (range.from > $from.start()) tr.split(range.from)
  const $inner = tr.doc.resolve(tr.mapping.map(range.from, 1))
  tr.setNodeMarkup($inner.before(), undefined, { tag: spec.tag, attrs: spec.attrs })
  return tr.scrollIntoView()
}

const HEADING_PLACEHOLDER = 'Heading'

/** Size of the atoms (verse anchors) a block opens with, before its first text. */
function leadingAtomsSize(block: PMNode): number {
  let size = 0
  for (let i = 0; i < block.childCount && block.child(i).type === schema.nodes.raw_inline; i++) size += block.child(i).nodeSize
  return size
}

/**
 * The h5 tool in a paraphrase paragraph, which can have one heading: the line above it
 * (the editor's first block). In the heading it turns it back into the paragraph's opening
 * text; on text at the very start of the paragraph it lifts that text into the heading;
 * anywhere else it adds a heading with its placeholder text selected, ready to type over
 * (or moves to the existing one).
 */
export function toggleParagraphHeading(state: EditorState, spec: ElSpec): Transaction {
  const first = state.doc.firstChild!
  const hasHeading = first.type === schema.nodes.block && first.attrs.tag === spec.tag
  const inFirst = state.selection.$from.index(0) === 0
  if (hasHeading && inFirst) {
    if (state.doc.childCount === 1) return state.tr.setNodeMarkup(0, undefined, { tag: null, attrs: {} })
    const tr = state.tr.delete(0, first.nodeSize)
    const at = 1 + leadingAtomsSize(tr.doc.firstChild!)
    tr.insert(at, first.content.append(Fragment.from(schema.text(' '))))
    return tr.setSelection(TextSelection.create(tr.doc, at + first.content.size)).scrollIntoView()
  }
  if (hasHeading) return state.tr.setSelection(TextSelection.create(state.doc, first.nodeSize - 1)).scrollIntoView()

  const range = targetRange(state)
  if (range && inFirst && range.from <= 1 + leadingAtomsSize(first) && state.doc.resolve(range.to).index(0) === 0) {
    const lifted = first.content.cut(range.from - 1, range.to - 1)
    const tr = state.tr.delete(range.from, range.to)
    // Drop the space the lifted words leave at the start of the paragraph.
    const next = tr.doc.resolve(range.from).nodeAfter
    if (next?.isText && next.text?.startsWith(' ')) tr.delete(range.from, range.from + 1)
    tr.insert(0, schema.nodes.block.create({ tag: spec.tag, attrs: spec.attrs }, lifted))
    return tr.setSelection(TextSelection.create(tr.doc, 1 + lifted.size)).scrollIntoView()
  }
  // Not an empty heading: Chrome puts text typed into an empty <h5> inside a <p> after it.
  const placeholder = schema.text(HEADING_PLACEHOLDER)
  const tr = state.tr.insert(0, schema.nodes.block.create({ tag: spec.tag, attrs: spec.attrs }, placeholder))
  return tr.setSelection(TextSelection.create(tr.doc, 1, 1 + placeholder.nodeSize)).scrollIntoView()
}

/**
 * Styling of words (color, bold, italic, hayah), as opposed to spans that lay out a whole
 * line or verse (last_center, centered, poetry-indent), which typed punctuation stays in.
 */
function isWordStyling(mark: Mark): boolean {
  if (mark.type !== schema.marks.el) return false
  if (['strong', 'b', 'em', 'i'].includes(mark.attrs.tag)) return true
  const attrs = mark.attrs.attrs as ElAttrs
  return isColor(mark) || (mark.attrs.tag === 'span' && Object.keys(attrs).length === 1 && attrs.class === 'hayah')
}

/** Punctuation and spaces: typed at the end of a colored/bold word they belong after it, not in it. */
const BOUNDARY_TEXT = /^[\s.,;:!?…)\]—–-]+$/u

/**
 * handleTextInput: typing "." right after `<span style="color: blue;">the Order</span>`
 * would otherwise extend the span (marks are inclusive), storing `the Order.</span>`.
 * Besides coloring the period, a verse that then ends in </span> loses the line break
 * after it on the chapter page (close_text in handle_nt_chapter).
 */
export function typeOutsideEndingMarks(view: EditorView, from: number, to: number, text: string): boolean {
  const { state } = view
  if (state.storedMarks || !BOUNDARY_TEXT.test(text)) return false
  const before = state.doc.resolve(from).nodeBefore
  if (!before?.isText) return false
  const afterMarks = state.doc.resolve(to).nodeAfter?.marks ?? []
  const ending = before.marks.filter((mark) => isWordStyling(mark) && !mark.isInSet(afterMarks))
  if (!ending.length) return false
  const marks = before.marks.filter((mark) => !ending.includes(mark))
  view.dispatch(state.tr.replaceWith(from, to, schema.text(text, marks)).scrollIntoView())
  return true
}
