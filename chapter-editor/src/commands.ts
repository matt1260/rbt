/**
 * Formatting tools for the floating toolbar. They mirror the buttons on the verse edit
 * page (translate/templates/edit_nt_verse.html) and produce the same markup.
 *
 * With an empty selection a tool applies to the word under the caret.
 */
import type { Mark, MarkType } from 'prosemirror-model'
import { EditorState, TextSelection, type Transaction } from 'prosemirror-state'
import { newMarkKey, schema, type ElAttrs, type ElSpec } from './schema'

export type Tool =
  | { kind: 'mark'; id: string; label: string; title: string; spec: ElSpec; aliases?: ElSpec[] }
  | { kind: 'colour'; id: string; label: string; title: string; spec: ElSpec | null }
  | { kind: 'block'; id: string; label: string; title: string; spec: ElSpec }

const span = (attrs: ElAttrs): ElSpec => ({ tag: 'span', attrs })

export const TOOLS: Tool[] = [
  { kind: 'colour', id: 'pink', label: '', title: 'Pink text', spec: span({ style: 'color: #ff00aa;' }) },
  { kind: 'colour', id: 'blue', label: '', title: 'Blue text', spec: span({ style: 'color: blue;' }) },
  { kind: 'colour', id: 'nocolour', label: '⌀', title: 'Remove colour', spec: null },
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

/** A plain colour span: `<span style="color: …;">` with no other attributes or declarations. */
function isColour(mark: Mark): boolean {
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

  if (tool.kind === 'colour') {
    for (const mark of marksInRange(state, from, to, isColour)) tr.removeMark(from, to, mark)
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
