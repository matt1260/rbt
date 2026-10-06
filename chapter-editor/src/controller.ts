/**
 * Drives inline editing on the NT chapter page.
 *
 * The server-rendered chapter stays in place. Each verse sits in a
 * `<div class="rbt-verse" data-verse="N" style="display: contents">` wrapper (added for
 * staff in handle_nt_chapter), so idle verses keep every chapter-viewer.js behaviour.
 * Clicking a word swaps just that verse for a ProseMirror editor; leaving the verse
 * re-renders it as plain HTML. Only one editor exists at a time.
 *
 * Saves are per verse, queued so only one request per verse is in flight, and carry the
 * hash of the HTML they were based on so a concurrent edit elsewhere is reported as a
 * conflict instead of being overwritten.
 */
import { baseKeymap } from 'prosemirror-commands'
import { history, redo, undo, undoDepth } from 'prosemirror-history'
import { keymap } from 'prosemirror-keymap'
import type { Node as PMNode } from 'prosemirror-model'
import { EditorState, NodeSelection, Plugin, TextSelection, type Command } from 'prosemirror-state'
import { Decoration, DecorationSet, EditorView } from 'prosemirror-view'
import { Api, type BlockSaveResult, type EditorConfig, type InterlinearWord } from './api'
import { applyTool, toggleParagraphHeading, toggleParagraphQuote, TOOLS, typeOutsideEndingMarks, type Tool } from './commands'
import { parseVerse, restoreColorSpans, roundTrips, sameHtml, schema, serializeDoc } from './schema'
import { closeText, composeVerse, wrapParentheses } from './verseDom'

const AUTOSAVE_DELAY_MS = 1000
const HOVER_OPEN_DELAY_MS = 150
const HOVER_CLOSE_DELAY_MS = 250
const EDIT_MODE_KEY = 'rbtChapterEditMode'
const UNDO_LIMIT = 50

export type SaveStatus = 'saved' | 'saving' | 'error' | 'conflict'

interface VerseRecord {
  verse: string
  /** HTML known to be stored on the server, and its hash. */
  html: string
  hash: string
  /** HTML we want stored: the last thing handed to save(). */
  target: string
  editable: boolean
  pending?: string
  inFlight: boolean
  status?: SaveStatus
  error?: string
  conflict?: { html: string; hash: string; mine: string }
}

interface ActiveEditor {
  /** A verse of the word-for-word text, or a paragraph or media notes of the published paraphrase. */
  kind: EditKind
  /** Verse number; for a paragraph, the verse range it covers (for labels only). */
  verse: string
  /** For a paragraph: its index among the paraphrase's top-level paragraphs; for notes, the media number. */
  index: number
  wrapper: HTMLElement
  view: EditorView
  refHtml: string
  /** Stored HTML when this editing session began; Escape reverts to it. */
  startHtml: string
  /** The wrapper's DOM before editing, put back untouched if nothing changed (verses, notes). */
  originalNodes: Node[]
  /** For a paragraph: the page elements it edits. */
  unit?: ParagraphUnit
  /** For a footnote: which one. */
  footnote?: FootnoteRef
  /** For a verse's image notes: the verse's HTML when editing began (what Undo restores). */
  verseStart?: string
}

/**
 * A paragraph of the published paraphrase being edited: its heading and its top-level
 * <p>/<blockquote> elements (one, or more once a quote is split out of it). The page only
 * changes shape when a save returns, so the position of these elements among the reader's
 * paragraphs is always the index the server's copy has them at.
 */
interface ParagraphUnit {
  heading: HTMLElement | null
  blocks: HTMLElement[]
  /** The editor, then a preview of the edit until it's saved; the elements stay hidden meanwhile. */
  overlay: HTMLElement | null
  /** The unit as the server last had it (editor HTML: heading, then the blocks). */
  saved: string
}

type PendingSave = { kind: 'paragraph'; unit: ParagraphUnit; html: string } | { kind: 'note'; index: number; html: string }

/** A finished editing session, undoable after leaving the verse: the HTML before it. */
/** 'verseNote': the notes of an image in a verse of the word-for-word text, edited in the image pop-up. */
type EditKind = 'verse' | ParaphrasePart | 'footnote' | 'verseNote'

/** A verse's image blocks (.tooltip-container) in document order, as media-modal.js counts them. */
function verseMediaBlocks(root: ParentNode): Element[] {
  return Array.from(root.querySelectorAll('.tooltip-container')).filter((block) => !block.parentElement?.closest('.tooltip, .tooltip2'))
}

/** The notes of a verse's index-th image block, or null. */
function verseNoteHtml(verseHtml: string, index: number): string | null {
  const tpl = document.createElement('template')
  tpl.innerHTML = verseHtml
  const notes = verseMediaBlocks(tpl.content)[index]?.querySelector('.tooltip, .tooltip2')
  return notes ? notes.innerHTML : null
}

/** The verse HTML with its index-th image block's notes replaced, or null. */
function withVerseNote(verseHtml: string, index: number, notesHtml: string): string | null {
  const tpl = document.createElement('template')
  tpl.innerHTML = verseHtml
  const notes = verseMediaBlocks(tpl.content)[index]?.querySelector('.tooltip, .tooltip2')
  if (!notes) return null
  notes.innerHTML = notesHtml
  return tpl.innerHTML
}

/** A footnote of the chapter, as its link names it: ?footnote=2-5-70a (chapter-verse-ref). */
interface FootnoteRef {
  id: string
  chapter: string
  verse: string
  ref: string
}

/** A footnote's save state; one save at a time per footnote. */
interface FootnoteSave {
  footnote: FootnoteRef
  /** The stored HTML's hash, sent so a footnote changed elsewhere isn't overwritten. */
  hash: string
  /** The footnote as the server last had it. */
  saved: string
  pending?: string
  inFlight: boolean
  status?: SaveStatus
  error?: string
}

function parseFootnoteRef(id: string | undefined): FootnoteRef | null {
  const match = /^(\d+)-(\d+)-([0-9]+[a-z]{0,3})$/i.exec(id ?? '')
  return match ? { id: id!, chapter: match[1], verse: match[2], ref: match[3] } : null
}
/** The parts of the published paraphrase edited in place: a paragraph, or the notes shown with an image. */
type ParaphrasePart = 'paragraph' | 'note'
type UndoEntry =
  | { kind: 'verse'; verse: string; html: string }
  | { kind: 'paragraph'; unit: ParagraphUnit; html: string }
  | { kind: 'note'; index: number; html: string }
  | { kind: 'footnote'; footnote: FootnoteRef; html: string }

export interface VerseStatus {
  /** 'verse' entries are keyed by verse number, 'footnote' ones by footnote id; there is one 'paraphrase' entry. */
  kind: 'verse' | 'paraphrase' | 'footnote'
  verse: string
  status: SaveStatus
  error?: string
  conflict?: { html: string; mine: string }
}

/** An image or video of the chapter, which a paraphrase paragraph can show as a cue. */
export interface MediaChoice {
  n: number
  title: string
  thumb: string | null
  /** Cues for it in the paraphrase now (the paragraph being edited included). */
  placed: number
}

/** True when the editor's selection is one image cue (a selected atom). */
export function selectedCue(state: EditorState): boolean {
  const { selection } = state
  return selection instanceof NodeSelection && selection.node.type === schema.nodes.raw_inline &&
    /class="pp-cue\b/.test(selection.node.attrs.html)
}

export interface Snapshot {
  editMode: boolean
  loading: boolean
  loadError: string | null
  active: { kind: EditKind; verse: string; view: EditorView; state: EditorState } | null
  statuses: VerseStatus[]
  /** Something to undo: in the open editor, or an earlier edit to a verse/paragraph. */
  canUndo: boolean
  notice: { text: string; verse?: string } | null
  hover: { verse: string; anchor: HTMLElement } | null
}

function readEditModePreference(): boolean {
  try {
    return localStorage.getItem(EDIT_MODE_KEY) === '1'
  } catch {
    return false
  }
}

function writeEditModePreference(on: boolean): void {
  try {
    localStorage.setItem(EDIT_MODE_KEY, on ? '1' : '0')
  } catch {
    // Private mode etc.; the toggle just won't be remembered.
  }
}

function isTypingTarget(target: EventTarget | null): boolean {
  const el = target as HTMLElement | null
  return !!el && (el.tagName === 'INPUT' || el.tagName === 'TEXTAREA' || el.tagName === 'SELECT' || el.isContentEditable)
}

const PART_LABEL: Record<ParaphrasePart, string> = { paragraph: 'Paragraph', note: 'Notes' }

function partKey(kind: ParaphrasePart, index: number): string {
  return `${kind}:${index}`
}

/** Where the verse number sits inside the editor: after the leading <h5>, else at the start. */
function refPosition(doc: PMNode, hasHeading: boolean): number {
  if (hasHeading) {
    let pos = 0
    for (let i = 0; i < doc.childCount; i++) {
      const child = doc.child(i)
      pos += child.nodeSize
      if (child.type === schema.nodes.block && child.attrs.tag === 'h5') return pos
    }
  }
  return 0
}

export class ChapterEditorController {
  readonly api: Api
  private listeners = new Set<() => void>()
  private snapshot: Snapshot
  private verses = new Map<string, VerseRecord>()
  private active: ActiveEditor | null = null
  private undoStack: UndoEntry[] = []
  private editMode = false
  private loading = false
  private loadError: string | null = null
  private notice: Snapshot['notice'] = null
  private hover: Snapshot['hover'] = null
  private autosaveTimer = 0
  private noticeTimer = 0
  private hoverOpenTimer = 0
  private hoverCloseTimer = 0
  private interlinearCache = new Map<string, Promise<InterlinearWord[]>>()
  /** The published paraphrase (#reader-paraphrase); its paragraphs are editable too. */
  private reader = document.getElementById('reader-paraphrase')
  /**
   * Paraphrase saves (paragraphs and notes) run one at a time: each changes the whole
   * paraphrase's hash. Keyed by the paragraph's unit, or partKey('note', n).
   */
  private paraphraseSaves = {
    pending: new Map<ParagraphUnit | string, PendingSave>(),
    current: null as PendingSave | null,
    /** Notes as the server last had them, by media number. */
    notes: new Map<number, string>(),
    inFlight: false,
    status: undefined as SaveStatus | undefined,
    error: undefined as string | undefined,
  }

  /** Footnotes edited in the chapter's footnote pop-up, by id. */
  private footnoteSaves = new Map<string, FootnoteSave>()
  private footnoteLoading = false

  constructor(
    config: EditorConfig,
    private area: HTMLElement,
  ) {
    this.api = new Api(config)
    this.snapshot = this.buildSnapshot()
    document.addEventListener('keydown', this.onDocumentKeyDown)
    window.addEventListener('beforeunload', this.onBeforeUnload)
    window.addEventListener('pagehide', this.onPageHide)
    if (readEditModePreference()) this.setEditMode(true)
  }

  // --- store ---------------------------------------------------------------

  subscribe = (listener: () => void) => {
    this.listeners.add(listener)
    return () => this.listeners.delete(listener)
  }

  getSnapshot = () => this.snapshot

  private buildSnapshot(): Snapshot {
    const statuses: VerseStatus[] = []
    for (const record of this.verses.values()) {
      if (!record.status) continue
      statuses.push({
        kind: 'verse',
        verse: record.verse,
        status: record.status,
        error: record.error,
        conflict: record.conflict && { html: record.conflict.html, mine: record.conflict.mine },
      })
    }
    if (this.paraphraseSaves.status) {
      statuses.push({ kind: 'paraphrase', verse: 'paraphrase', status: this.paraphraseSaves.status, error: this.paraphraseSaves.error })
    }
    for (const save of this.footnoteSaves.values()) {
      if (save.status) statuses.push({ kind: 'footnote', verse: save.footnote.id, status: save.status, error: save.error })
    }
    return {
      editMode: this.editMode,
      loading: this.loading,
      loadError: this.loadError,
      active: this.active && { kind: this.active.kind, verse: this.active.verse, view: this.active.view, state: this.active.view.state },
      statuses,
      canUndo: (this.active ? undoDepth(this.active.view.state) > 0 : false) || this.undoStack.length > 0,
      notice: this.notice,
      hover: this.hover,
    }
  }

  private emit() {
    this.snapshot = this.buildSnapshot()
    for (const listener of this.listeners) listener()
  }

  // --- edit mode -----------------------------------------------------------

  toggleEditMode = () => this.setEditMode(!this.editMode)

  setEditMode(on: boolean) {
    if (on === this.editMode) return
    this.editMode = on
    writeEditModePreference(on)
    document.body.classList.toggle('rbt-edit-mode', on)
    if (on) {
      this.area.addEventListener('mousedown', this.onAreaMouseDown)
      this.area.addEventListener('click', this.onAreaClick)
      this.area.addEventListener('mouseover', this.onAreaMouseOver)
      this.area.addEventListener('mouseout', this.onAreaMouseOut)
      document.addEventListener('mousedown', this.onDocumentMouseDown, true)
      this.reader?.addEventListener('mousedown', this.onReaderMouseDown)
      this.reader?.addEventListener('click', this.onReaderClick)
      document.addEventListener('mousedown', this.onNoteMouseDown)
      document.addEventListener('mousedown', this.onFootnoteMouseDown)
      this.pointVerseRefsAt('edit')
      if (!this.verses.size) void this.load()
    } else {
      this.commit()
      this.area.removeEventListener('mousedown', this.onAreaMouseDown)
      this.area.removeEventListener('click', this.onAreaClick)
      this.area.removeEventListener('mouseover', this.onAreaMouseOver)
      this.area.removeEventListener('mouseout', this.onAreaMouseOut)
      document.removeEventListener('mousedown', this.onDocumentMouseDown, true)
      this.reader?.removeEventListener('mousedown', this.onReaderMouseDown)
      this.reader?.removeEventListener('click', this.onReaderClick)
      document.removeEventListener('mousedown', this.onNoteMouseDown)
      document.removeEventListener('mousedown', this.onFootnoteMouseDown)
      this.pointVerseRefsAt('public')
      this.hover = null
    }
    this.emit()
  }

  private async load() {
    this.loading = true
    this.loadError = null
    this.emit()
    try {
      const verses = await this.api.chapter()
      for (const { verse, html, hash } of verses) {
        this.verses.set(verse, { verse, html, hash, target: html, editable: roundTrips(html, document), inFlight: false })
      }
    } catch (error) {
      this.loadError = error instanceof Error ? error.message : String(error)
    }
    this.loading = false
    this.emit()
  }

  retryLoad = () => void this.load()

  /** In edit mode verse numbers open the verse edit page; otherwise the public verse page. */
  private pointVerseRefsAt(target: 'edit' | 'public') {
    for (const wrapper of this.wrappers()) {
      const link = wrapper.querySelector<HTMLAnchorElement>('.verse_ref a')
      const verse = wrapper.dataset.verse
      if (!link || !verse) continue
      if (target === 'edit') {
        if (!link.dataset.publicHref) link.dataset.publicHref = link.getAttribute('href') ?? ''
        link.href = this.api.editUrl(verse)
      } else if (link.dataset.publicHref !== undefined) {
        link.setAttribute('href', link.dataset.publicHref)
      }
    }
  }

  private wrappers(): HTMLElement[] {
    return Array.from(this.area.querySelectorAll<HTMLElement>('.rbt-verse[data-verse]'))
  }

  private wrapperFor(verse: string): HTMLElement | undefined {
    return this.wrappers().find((wrapper) => wrapper.dataset.verse === verse)
  }

  // --- DOM events ----------------------------------------------------------

  private onDocumentKeyDown = (event: KeyboardEvent) => {
    if (this.editMode && !this.active && (event.metaKey || event.ctrlKey) && !event.shiftKey && event.key.toLowerCase() === 'z' &&
      !isTypingTarget(event.target) && this.undoStack.length) {
      event.preventDefault()
      this.undoLast()
      return
    }
    if (event.key !== 'e' || event.metaKey || event.ctrlKey || event.altKey || isTypingTarget(event.target)) return
    this.toggleEditMode()
  }

  private onAreaMouseDown = (event: MouseEvent) => {
    if (event.button !== 0 || event.metaKey || event.ctrlKey || event.shiftKey || event.altKey) return
    const target = event.target as Element
    const wrapper = target.closest<HTMLElement>('.rbt-verse[data-verse]')
    if (!wrapper || this.active?.wrapper === wrapper) return
    // Links, verse numbers, footnotes, images and videos keep their normal behaviour.
    if (target.closest('a, .verse_ref, img, video, audio, .tooltip-container')) return
    if (this.loading || !this.verses.size) return
    event.preventDefault()
    this.commit()
    this.activate(wrapper, { left: event.clientX, top: event.clientY })
  }

  /** Links inside re-rendered verses have no footnote-popup listeners; don't navigate away. */
  private onAreaClick = (event: MouseEvent) => {
    const link = (event.target as Element).closest('a')
    if (!link || link.closest('.verse_ref')) return
    const wrapper = link.closest<HTMLElement>('.rbt-verse')
    if (wrapper?.dataset.rendered === 'editor' || this.active?.wrapper === wrapper) event.preventDefault()
  }

  private onDocumentMouseDown = (event: MouseEvent) => {
    if (!this.active) return
    const target = event.target as Element
    if (this.active.wrapper.contains(target)) return
    if (target.closest?.('[data-rbt-ui]')) return
    if (target.closest?.('.rbt-verse') && this.area.contains(target)) return // handled by onAreaMouseDown
    if (this.paragraphOf(target)) return // handled by onReaderMouseDown
    this.commit()
  }

  private onBeforeUnload = (event: BeforeUnloadEvent) => {
    // Start the save now; it's sent with keepalive, so it completes after navigation
    // (e.g. clicking a verse number mid-edit). Only warn about work that won't be sent.
    this.flushActive()
    if (this.hasUnsendableWork()) {
      event.preventDefault()
      event.returnValue = ''
    }
  }

  private onPageHide = () => this.commit()

  /** Edits that leaving the page would lose: queued behind another save, failed, or in conflict. */
  private hasUnsendableWork(): boolean {
    for (const record of this.verses.values()) {
      if (record.pending !== undefined || record.status === 'error' || record.status === 'conflict') return true
    }
    const saves = this.paraphraseSaves
    return saves.pending.size > 0 || saves.status === 'error' || saves.status === 'conflict'
  }

  // --- verse ref hover (interlinear popup) ------------------------------------

  private onAreaMouseOver = (event: MouseEvent) => {
    const ref = (event.target as Element).closest<HTMLElement>('.verse_ref')
    const verse = ref?.closest<HTMLElement>('.rbt-verse')?.dataset.verse
    if (!ref || !verse) return
    window.clearTimeout(this.hoverCloseTimer)
    if (this.hover?.anchor === ref) return
    window.clearTimeout(this.hoverOpenTimer)
    this.hoverOpenTimer = window.setTimeout(() => {
      this.hover = { verse, anchor: ref }
      this.emit()
    }, HOVER_OPEN_DELAY_MS)
  }

  private onAreaMouseOut = (event: MouseEvent) => {
    const ref = (event.target as Element).closest('.verse_ref')
    if (!ref || ref.contains(event.relatedTarget as Node)) return
    window.clearTimeout(this.hoverOpenTimer)
    this.scheduleHoverClose()
  }

  keepHover = () => window.clearTimeout(this.hoverCloseTimer)

  scheduleHoverClose = () => {
    window.clearTimeout(this.hoverCloseTimer)
    this.hoverCloseTimer = window.setTimeout(() => {
      this.hover = null
      this.emit()
    }, HOVER_CLOSE_DELAY_MS)
  }

  interlinear(verse: string): Promise<InterlinearWord[]> {
    let request = this.interlinearCache.get(verse)
    if (!request) {
      request = this.api.interlinear(verse)
      request.catch(() => this.interlinearCache.delete(verse))
      this.interlinearCache.set(verse, request)
    }
    return request
  }

  // --- paraphrase paragraphs ---------------------------------------------------

  private paragraphs(): HTMLElement[] {
    return this.reader
      ? Array.from(this.reader.children).filter((el): el is HTMLElement => el.matches('p, blockquote'))
      : []
  }

  private paragraphOf(target: Element): HTMLElement | null {
    if (!this.reader?.dataset.uid || !this.reader.contains(target)) return null
    const heading = target.closest<HTMLElement>('h5')
    if (heading && heading.parentElement === this.reader) {
      // A heading is edited with the paragraph below it.
      const next = heading.nextElementSibling as HTMLElement | null
      return next?.matches('p, blockquote') ? next : null
    }
    const block = target.closest<HTMLElement>('p, blockquote')
    return block && block.parentElement === this.reader ? block : null
  }

  /** The heading above a paraphrase paragraph, if it has one. */
  private headingOf(block: HTMLElement): HTMLElement | null {
    const previous = block.previousElementSibling
    return previous instanceof HTMLElement && previous.tagName === 'H5' ? previous : null
  }

  /** A unit's editor HTML from the page: its heading's text, then each block with its class and verse range. */
  private unitHtml(heading: HTMLElement | null, blocks: HTMLElement[]): string {
    const parts = blocks.map((block) => {
      const copy = document.createElement(block.tagName.toLowerCase())
      for (const name of ['class', 'data-v']) {
        const value = block.getAttribute(name)
        if (value) copy.setAttribute(name, value)
      }
      copy.innerHTML = block.innerHTML
      return copy.outerHTML
    })
    // The page may have added attributes to the heading (font scaling); edit just its text.
    // Read from the page, so undo what its color toggles did to the color spans.
    return restoreColorSpans((heading ? `<h5>${heading.innerHTML}</h5>` : '') + parts.join(''), document)
  }

  private setUnitHidden(unit: ParagraphUnit, hidden: boolean) {
    for (const el of [unit.heading, ...unit.blocks]) if (el) el.hidden = hidden
  }

  /** Open in the editor, or waiting for a save: its elements stay hidden under the overlay. */
  private unitBusy(unit: ParagraphUnit): boolean {
    const saves = this.paraphraseSaves
    return this.active?.unit === unit || saves.pending.has(unit) || (saves.current?.kind === 'paragraph' && saves.current.unit === unit)
  }

  /** Show `html` (editor HTML) in place of the unit while it saves. */
  private previewUnit(unit: ParagraphUnit, html: string) {
    if (!unit.overlay) {
      unit.overlay = document.createElement('div')
      ;(unit.heading ?? unit.blocks[0]).before(unit.overlay)
      this.setUnitHidden(unit, true)
    }
    unit.overlay.className = 'rbt-pp-pending'
    unit.overlay.innerHTML = html
  }

  /** Drop the overlay and show the unit's elements, unless it's still open or saving. */
  private settleUnit(unit: ParagraphUnit) {
    if (this.unitBusy(unit)) return
    unit.overlay?.remove()
    unit.overlay = null
    this.setUnitHidden(unit, false)
  }

  /** Replace the unit's elements with the server's version of it (editor HTML). */
  private renderUnit(unit: ParagraphUnit, html: string) {
    const tpl = document.createElement('template')
    tpl.innerHTML = html
    const nodes = Array.from(tpl.content.children) as HTMLElement[]
    const lead = nodes[0]?.tagName === 'H5' ? nodes.shift()! : null
    const heading = lead && (lead.textContent ?? '').trim() ? lead : null
    const blocks = nodes.filter((el) => el.matches('p, blockquote'))
    const first = unit.heading ?? unit.blocks[0]
    const hidden = this.unitBusy(unit)
    for (const el of [heading, ...blocks]) {
      if (!el) continue
      el.hidden = hidden
      first.before(el)
    }
    const oldBlocks = unit.blocks
    for (const el of [unit.heading, ...oldBlocks]) el?.remove()
    // Earlier sessions on the same paragraph (in the undo stack) follow its new elements.
    for (const entry of this.undoStack) {
      if (entry.kind === 'paragraph' && entry.unit !== unit && entry.unit.blocks.length === oldBlocks.length &&
        entry.unit.blocks.every((block, i) => block === oldBlocks[i])) {
        entry.unit.heading = heading
        entry.unit.blocks = blocks
      }
    }
    unit.heading = heading
    unit.blocks = blocks
    this.settleUnit(unit)
  }

  private onReaderMouseDown = (event: MouseEvent) => {
    if (event.button !== 0 || event.metaKey || event.ctrlKey || event.shiftKey || event.altKey) return
    const target = event.target as Element
    const block = this.paragraphOf(target)
    if (!block || this.active?.wrapper === block) return
    // Image cues open their modal; links keep working.
    if (target.closest('a, button, .pp-cue')) return
    event.preventDefault()
    this.commit()
    this.activateParagraph(block, { left: event.clientX, top: event.clientY }, !!target.closest('h5'))
  }

  private onReaderClick = (event: MouseEvent) => {
    const link = (event.target as Element).closest('a')
    if (link && this.active?.kind === 'paragraph' && this.active.wrapper.contains(link)) event.preventDefault()
  }

  private activateParagraph(block: HTMLElement, coords: { left: number; top: number }, onHeading = false) {
    const heading = this.headingOf(block)
    const html = this.unitHtml(heading, [block])
    if (!roundTrips(html, document)) {
      this.showNotice('This paragraph has markup the inline editor cannot keep intact.')
      return
    }
    const unit: ParagraphUnit = { heading, blocks: [block], overlay: null, saved: html }
    // The editor sits above the paragraph's elements, which stay on the page (hidden) until
    // a save replaces them, so the reader's paragraph count only changes with the server's.
    const host = document.createElement('div')
    host.className = 'rbt-verse-editor rbt-pp-editor'
    ;(heading ?? block).before(host)
    unit.overlay = host
    this.setUnitHidden(unit, true)

    const view = new EditorView({ mount: host }, {
      state: EditorState.create({
        doc: parseVerse(html, document),
        plugins: this.editorPlugins(),
      }),
      dispatchTransaction: (tr) => {
        view.updateState(view.state.apply(tr))
        if (tr.docChanged) this.scheduleAutosave()
        this.emit()
      },
    })
    this.active = {
      kind: 'paragraph', verse: block.dataset.v ?? '', index: -1, wrapper: host, view,
      refHtml: '', startHtml: html, originalNodes: [], unit,
    }
    const hit = view.posAtCoords(coords)
    let selection = hit ? TextSelection.near(view.state.doc.resolve(hit.pos)) : TextSelection.atEnd(view.state.doc)
    // Clicked the heading: put the caret in it even if the click landed just outside the editor's copy.
    if (onHeading && selection.$from.index(0) !== 0) selection = TextSelection.create(view.state.doc, view.state.doc.firstChild!.nodeSize - 1)
    view.dispatch(view.state.tr.setSelection(selection))
    view.focus()
    this.emit()
  }

  // --- image cues --------------------------------------------------------------

  /** The chapter's images (the paraphrase's media store), for the paragraph toolbar's picker. */
  mediaChoices(): MediaChoice[] {
    const reader = this.reader
    if (!reader) return []
    const counts = new Map<number, number>()
    const count = (n: number) => counts.set(n, (counts.get(n) ?? 0) + 1)
    // Cues on the page, except in the paragraph being edited (hidden), which the editor counts.
    for (const cue of Array.from(reader.querySelectorAll<HTMLElement>(':scope > p .pp-cue, :scope > blockquote .pp-cue'))) {
      if (!cue.closest<HTMLElement>('p, blockquote')!.hidden) count(Number(cue.dataset.media))
    }
    this.active?.view.state.doc.descendants((node) => {
      const match = node.type === schema.nodes.raw_inline && /class="pp-cue\b[^>]*data-media="(\d+)"|data-media="(\d+)"[^>]*class="pp-cue\b/.exec(node.attrs.html)
      if (match) count(Number(match[1] ?? match[2]))
    })
    return Array.from(reader.querySelectorAll<HTMLTemplateElement>('.pp-media-store template[data-media]')).map((template) => {
      const n = Number(template.dataset.media)
      const cue = reader.querySelector<HTMLElement>(`.pp-cue[data-media="${n}"]`)
      // Like the server's titles: the notes' bold heading, else their first sentence.
      const notes = template.content.querySelector('.tooltip, .tooltip2')
      const heading = (notes?.querySelector('b, strong')?.textContent ?? '').trim()
      const sentence = (notes?.textContent ?? '').trim().replace(/\s+/g, ' ').split(/(?<=[.!?])\s/)[0].slice(0, 90)
      const title = cue?.title || heading || sentence || `Image ${n}`
      const img = template.content.querySelector('img')
      return { n, title, thumb: img?.getAttribute('src') ?? null, placed: counts.get(n) ?? 0 }
    })
  }

  /** The cue markup for media item n; the server rebuilds it from the stored media on save. */
  private cueHtml(n: number): string {
    const existing = this.reader?.querySelector<HTMLElement>(`.pp-cue[data-media="${n}"]`)
    if (existing) return existing.outerHTML
    const choice = this.mediaChoices().find((item) => item.n === n)
    const button = document.createElement('button')
    button.type = 'button'
    button.className = 'pp-cue pp-cue--image'
    button.dataset.media = String(n)
    button.title = choice?.title ?? ''
    if (choice?.thumb) {
      const img = document.createElement('img')
      img.className = 'pp-cue__thumb'
      img.alt = ''
      img.src = choice.thumb
      button.append(img)
    }
    return button.outerHTML
  }

  /** Put media item n's cue at the caret of the paragraph being edited. */
  insertCue = (n: number) => {
    const view = this.active?.kind === 'paragraph' ? this.active.view : null
    if (!view) return
    const node = schema.nodes.raw_inline.create({ html: this.cueHtml(n) })
    view.dispatch(view.state.tr.replaceSelectionWith(node, false).scrollIntoView())
    view.focus()
  }

  /** Remove the selected cue (the image stays in the chapter's media, so it can be put back). */
  removeSelectedCue = () => {
    const view = this.active?.view
    if (!view || !selectedCue(view.state)) return
    view.dispatch(view.state.tr.deleteSelection().scrollIntoView())
    view.focus()
  }

  // --- image notes -------------------------------------------------------------

  /** In edit mode, a click on the notes in the image modal (published paraphrase) edits them. */
  private onNoteMouseDown = (event: MouseEvent) => {
    if (event.button !== 0 || event.metaKey || event.ctrlKey || event.shiftKey || event.altKey) return
    const target = event.target as Element
    const box = target.closest?.<HTMLElement>('.pp-modal__text')
    const modal = box?.closest<HTMLDialogElement>('dialog.pp-modal')
    if (!box || !modal?.open || this.active?.wrapper === box || target.closest('a, img, video')) return
    const coords = { left: event.clientX, top: event.clientY }
    if (modal.dataset.source === 'verse') {
      // An image in the word-for-word text: its notes are part of the verse's HTML.
      const index = Number(modal.dataset.index)
      if (!modal.dataset.verse || !Number.isInteger(index) || index < 0) return
      event.preventDefault()
      this.commit()
      this.activateVerseNote(box, modal.dataset.verse, index, coords)
      return
    }
    const n = Number(modal.dataset.media)
    if (modal.dataset.source !== 'reader' || !this.reader?.dataset.uid || !Number.isInteger(n)) return
    event.preventDefault()
    this.commit()
    this.activateNote(box, n, coords)
  }

  private activateVerseNote(box: HTMLElement, verse: string, index: number, coords: { left: number; top: number }) {
    const record = this.verses.get(verse)
    if (!record) {
      this.showNotice(this.loading ? 'The chapter is still loading; try again in a moment.' : `Verse ${verse} isn't loaded for editing.`)
      return
    }
    if (record.conflict) {
      this.showNotice(`Verse ${verse} was changed elsewhere. Resolve the conflict first.`, verse)
      return
    }
    const html = verseNoteHtml(record.target, index)
    if (html == null) return
    if (!roundTrips(html, document)) {
      this.showNotice('These notes have markup the inline editor cannot keep intact.')
      return
    }
    const originalNodes = Array.from(box.childNodes)
    const host = document.createElement('div')
    host.className = 'rbt-verse-editor'
    box.replaceChildren(host)
    const view = new EditorView({ mount: host }, {
      state: EditorState.create({ doc: parseVerse(html, document), plugins: this.editorPlugins() }),
      dispatchTransaction: (tr) => {
        view.updateState(view.state.apply(tr))
        if (tr.docChanged) this.scheduleAutosave()
        this.emit()
      },
    })
    this.active = { kind: 'verseNote', verse, index, wrapper: box, view, refHtml: '', startHtml: html, originalNodes, verseStart: record.target }
    const hit = view.posAtCoords(coords)
    view.dispatch(view.state.tr.setSelection(hit ? TextSelection.near(view.state.doc.resolve(hit.pos)) : TextSelection.atEnd(view.state.doc)))
    view.focus()
    this.emit()
  }

  /** Save edited image notes as part of their verse, and show the verse with them. */
  private saveVerseNote(verse: string, index: number, notesHtml: string) {
    const record = this.verses.get(verse)
    const html = record && withVerseNote(record.target, index, notesHtml)
    if (!record || html == null) return
    if (sameHtml(html, record.target, document)) return
    this.save(verse, html)
    const wrapper = this.wrapperFor(verse)
    if (wrapper) this.render(verse, wrapper)
  }

  private activateNote(box: HTMLElement, n: number, coords: { left: number; top: number }) {
    const html = window.rbtReaderParaphrase?.noteHtml(n)
    if (html == null) return
    if (!roundTrips(html, document)) {
      this.showNotice('These notes have markup the inline editor cannot keep intact.')
      return
    }
    if (!this.paraphraseSaves.notes.has(n)) this.paraphraseSaves.notes.set(n, html)
    // The modal shows a display copy (title lifted out); the editor works on the stored notes.
    const originalNodes = Array.from(box.childNodes)
    const host = document.createElement('div')
    host.className = 'rbt-verse-editor'
    box.replaceChildren(host)

    const view = new EditorView({ mount: host }, {
      state: EditorState.create({ doc: parseVerse(html, document), plugins: this.editorPlugins() }),
      dispatchTransaction: (tr) => {
        view.updateState(view.state.apply(tr))
        if (tr.docChanged) this.scheduleAutosave()
        this.emit()
      },
    })
    this.active = { kind: 'note', verse: '', index: n, wrapper: box, view, refHtml: '', startHtml: html, originalNodes }
    const hit = view.posAtCoords(coords)
    view.dispatch(view.state.tr.setSelection(hit ? TextSelection.near(view.state.doc.resolve(hit.pos)) : TextSelection.atEnd(view.state.doc)))
    view.focus()
    this.emit()
  }

  // --- footnotes --------------------------------------------------------------------

  /** In edit mode, a click on the text of the chapter's footnote pop-up edits that footnote. */
  private onFootnoteMouseDown = (event: MouseEvent) => {
    if (event.button !== 0 || event.metaKey || event.ctrlKey || event.shiftKey || event.altKey) return
    const target = event.target as Element
    const box = target.closest?.<HTMLElement>('.footnote-popup.active .footnote-popup-content')
    const popup = box?.closest<HTMLElement>('.footnote-popup')
    const footnote = parseFootnoteRef(popup?.dataset.footnote)
    // Only the English footnotes are stored here; a translated one isn't edited in place.
    if (!box || !popup || !footnote || (popup.dataset.lang && popup.dataset.lang !== 'en')) return
    if (this.active?.wrapper === box || target.closest('a')) return
    event.preventDefault()
    this.commit()
    void this.activateFootnote(box, popup, footnote, { left: event.clientX, top: event.clientY })
  }

  private async activateFootnote(box: HTMLElement, popup: HTMLElement, footnote: FootnoteRef, coords: { left: number; top: number }) {
    if (this.footnoteLoading) return
    let save = this.footnoteSaves.get(footnote.id)
    if (!save) {
      // The pop-up shows a display copy; edit the stored footnote.
      this.footnoteLoading = true
      const loaded = await this.api.footnote(footnote.ref)
      this.footnoteLoading = false
      if ('error' in loaded) {
        this.showNotice(`Footnote ${footnote.ref}: ${loaded.error}`)
        return
      }
      save = { footnote, hash: loaded.hash, saved: loaded.html, inFlight: false }
      this.footnoteSaves.set(footnote.id, save)
    }
    // The pop-up may have closed or moved on while the footnote loaded.
    if (this.active || !box.isConnected || !popup.classList.contains('active') || popup.dataset.footnote !== footnote.id) return
    const html = save.pending ?? save.saved
    if (!roundTrips(html, document)) {
      this.showNotice(`Footnote ${footnote.ref} has markup the inline editor cannot keep intact.`)
      return
    }
    const originalNodes = Array.from(box.childNodes)
    const host = document.createElement('div')
    host.className = 'rbt-verse-editor'
    box.replaceChildren(host)
    const view = new EditorView({ mount: host }, {
      state: EditorState.create({ doc: parseVerse(html, document), plugins: this.editorPlugins() }),
      dispatchTransaction: (tr) => {
        view.updateState(view.state.apply(tr))
        if (tr.docChanged) this.scheduleAutosave()
        this.emit()
      },
    })
    this.active = { kind: 'footnote', verse: footnote.id, index: -1, wrapper: box, view, refHtml: '', startHtml: html, originalNodes, footnote }
    const hit = view.posAtCoords(coords)
    view.dispatch(view.state.tr.setSelection(hit ? TextSelection.near(view.state.doc.resolve(hit.pos)) : TextSelection.atEnd(view.state.doc)))
    view.focus()
    this.emit()
  }

  private saveFootnote(footnote: FootnoteRef, html: string) {
    const save = this.footnoteSaves.get(footnote.id)
    if (!save || sameHtml(html, save.pending ?? save.saved, document)) return
    save.pending = html
    void this.runFootnoteQueue(save)
  }

  private async runFootnoteQueue(save: FootnoteSave) {
    if (save.inFlight) return
    while (save.pending !== undefined && save.status !== 'conflict') {
      const html = save.pending
      save.pending = undefined
      save.inFlight = true
      save.status = 'saving'
      save.error = undefined
      this.emit()
      const { chapter, verse, ref, id } = save.footnote
      const result = await this.api.saveFootnote(chapter, verse, ref, html, save.hash)
      save.inFlight = false
      if (result.status === 'ok') {
        save.hash = result.hash
        save.saved = result.html
        save.status = save.pending === undefined ? 'saved' : 'saving'
        // Show the stored version (normalised on save), unless it's open in the editor.
        if (this.active?.footnote?.id !== id) window.rbtFootnotes?.setContent(id, result.html)
      } else if (result.status === 'conflict') {
        save.status = 'conflict'
        save.pending = undefined
      } else {
        save.status = 'error'
        save.error = result.message
        save.pending ??= html
        break
      }
    }
    this.emit()
  }

  retryFootnote = (id: string) => {
    const save = this.footnoteSaves.get(id)
    if (save?.status === 'error') void this.runFootnoteQueue(save)
  }

  // --- saving paraphrase parts ---------------------------------------------------

  private saveUnit(unit: ParagraphUnit, html: string) {
    const saves = this.paraphraseSaves
    const inFlight = saves.current?.kind === 'paragraph' && saves.current.unit === unit ? saves.current.html : undefined
    const latest = saves.pending.get(unit)?.html ?? inFlight ?? unit.saved
    if (sameHtml(html, latest, document)) return
    saves.pending.set(unit, { kind: 'paragraph', unit, html })
    void this.runParaphraseQueue()
  }

  private saveNote(n: number, html: string) {
    const saves = this.paraphraseSaves
    const key = partKey('note', n)
    const current = saves.pending.get(key)?.html ?? saves.notes.get(n)
    if (current !== undefined && sameHtml(html, current, document)) return
    saves.pending.set(key, { kind: 'note', index: n, html })
    void this.runParaphraseQueue()
  }

  private async runParaphraseQueue() {
    const saves = this.paraphraseSaves
    const reader = this.reader
    if (saves.inFlight || !reader?.dataset.uid) return
    while (saves.pending.size && saves.status !== 'conflict') {
      const [key, part] = saves.pending.entries().next().value as [ParagraphUnit | string, PendingSave]
      saves.pending.delete(key)
      saves.inFlight = true
      saves.current = part
      saves.status = 'saving'
      saves.error = undefined
      this.emit()

      let result: BlockSaveResult
      if (part.kind === 'note') {
        result = await this.api.saveParaphraseNote(reader.dataset.uid, part.index, part.html, reader.dataset.hash ?? '')
      } else {
        // Where the unit's elements are now is where the server has them.
        const index = this.paragraphs().indexOf(part.unit.blocks[0])
        result = index < 0 || part.unit.blocks.some((block) => !block.isConnected)
          ? { status: 'error', message: 'This paragraph is no longer on the page. Reload to edit it.' }
          : await this.api.saveParaphraseBlock(reader.dataset.uid, index, part.unit.blocks.length, part.html, reader.dataset.hash ?? '')
      }
      saves.inFlight = false
      saves.current = null
      if (result.status === 'ok') {
        reader.dataset.hash = result.hash
        saves.status = saves.pending.size ? 'saving' : 'saved'
        // Show the server's version (cues rebuilt, anchors re-added, notes sanitised).
        if (part.kind === 'note') {
          saves.notes.set(part.index, result.html)
          if (this.active?.kind !== 'note' || this.active.index !== part.index) window.rbtReaderParaphrase?.setNote(part.index, result.html)
        } else {
          part.unit.saved = result.html
          this.renderUnit(part.unit, result.html)
        }
      } else if (result.status === 'conflict') {
        saves.status = 'conflict'
        saves.pending.clear()
      } else {
        saves.status = 'error'
        saves.error = result.message
        if (!saves.pending.has(key)) saves.pending.set(key, part)
        break
      }
    }
    this.emit()
  }

  retryParagraphSaves = () => {
    if (this.paraphraseSaves.status === 'error') void this.runParaphraseQueue()
  }

  // --- editing ---------------------------------------------------------------

  private activate(wrapper: HTMLElement, coords: { left: number; top: number }) {
    const verse = wrapper.dataset.verse!
    const record = this.verses.get(verse)
    if (!record) return
    if (!record.editable) {
      this.showNotice(`Verse ${verse} has markup the inline editor can't keep intact. Open it in the verse editor.`, verse)
      return
    }
    if (record.conflict) {
      this.showNotice(`Verse ${verse} was changed elsewhere. Resolve the conflict first.`, verse)
      return
    }

    const html = record.target
    const refHtml = wrapper.querySelector('.verse_ref')?.outerHTML ?? ''
    const hasHeading = html.includes('<h5>')
    const originalNodes = Array.from(wrapper.childNodes)
    const host = document.createElement('div')
    host.className = 'rbt-verse-editor'
    wrapper.replaceChildren(host)
    if (closeText(html)) wrapper.append(document.createElement('br'))

    const refDom = () => {
      const span = document.createElement('span')
      span.className = 'rbt-ref-widget'
      span.innerHTML = hasHeading ? refHtml : `${refHtml} `
      return span
    }
    const refPlugin = new Plugin({
      props: {
        decorations: (state) =>
          DecorationSet.create(state.doc, [
            Decoration.widget(refPosition(state.doc, hasHeading), refDom, { side: -1, key: 'verse-ref', ignoreSelection: true }),
          ]),
      },
    })

    const state = EditorState.create({
      doc: parseVerse(html, document),
      plugins: [...this.editorPlugins(), refPlugin],
    })
    const view = new EditorView({ mount: host }, {
      state,
      dispatchTransaction: (tr) => {
        view.updateState(view.state.apply(tr))
        if (tr.docChanged) this.scheduleAutosave()
        this.emit()
      },
      handleDOMEvents: {
        click: (_view, event) => {
          const link = (event.target as Element).closest('a')
          if (!link) return false
          if (link.closest('.verse_ref')) {
            // Verse number inside the editor: open the verse edit page like the idle ones do.
            event.preventDefault()
            this.commit()
            window.location.href = this.api.editUrl(verse)
          } else {
            event.preventDefault()
          }
          return true
        },
      },
    })

    this.active = { kind: 'verse', verse, index: -1, wrapper, view, refHtml, startHtml: record.target, originalNodes }
    const hit = view.posAtCoords(coords)
    const selection = hit
      ? TextSelection.near(view.state.doc.resolve(hit.pos))
      : TextSelection.atEnd(view.state.doc)
    view.dispatch(view.state.tr.setSelection(selection))
    view.focus()
    this.emit()
  }

  private editorPlugins(): Plugin[] {
    return [
      history(),
      keymap(this.editorKeymap()),
      keymap(baseKeymap),
      new Plugin({ props: { handleTextInput: typeOutsideEndingMarks } }),
    ]
  }

  private editorKeymap(): Record<string, Command> {
    const bold = TOOLS.find((tool) => tool.id === 'bold')!
    const italic = TOOLS.find((tool) => tool.id === 'italic')!
    return {
      'Mod-z': undo,
      'Shift-Mod-z': redo,
      'Mod-y': redo,
      'Mod-b': (state, dispatch) => {
        const tr = applyTool(state, bold)
        if (tr && dispatch) dispatch(tr)
        return !!tr
      },
      'Mod-i': (state, dispatch) => {
        const tr = applyTool(state, italic)
        if (tr && dispatch) dispatch(tr)
        return !!tr
      },
      'Shift-Enter': (state, dispatch) => {
        dispatch?.(state.tr.replaceSelectionWith(schema.nodes.hard_break.create()).scrollIntoView())
        return true
      },
      Enter: () => {
        this.commit()
        return true
      },
      Escape: () => {
        this.commit({ revert: true })
        return true
      },
    }
  }

  runTool(tool: Tool) {
    const view = this.active?.view
    if (!view) return
    const paragraph = this.active?.kind === 'paragraph' && tool.kind === 'block'
    const tr = paragraph && tool.id === 'h5' ? toggleParagraphHeading(view.state, tool.spec)
      : paragraph && tool.id === 'quote' ? toggleParagraphQuote(view.state)
      : applyTool(view.state, tool)
    if (tr) view.dispatch(tr)
    view.focus()
  }

  undo = () => this.runCommand(undo)
  redo = () => this.runCommand(redo)

  private runCommand(command: Command) {
    const view = this.active?.view
    if (!view) return
    command(view.state, view.dispatch)
    view.focus()
  }

  private scheduleAutosave() {
    window.clearTimeout(this.autosaveTimer)
    this.autosaveTimer = window.setTimeout(() => this.flushActive(), AUTOSAVE_DELAY_MS)
  }

  /** Save the active editor's current content without leaving the verse. */
  private flushActive() {
    window.clearTimeout(this.autosaveTimer)
    const active = this.active
    if (!active) return
    const html = serializeDoc(active.view.state.doc, document)
    if (active.kind === 'verse') this.save(active.verse, html)
    else if (active.kind === 'note') this.saveNote(active.index, html)
    else if (active.kind === 'verseNote') this.saveVerseNote(active.verse, active.index, html)
    else if (active.kind === 'footnote') this.saveFootnote(active.footnote!, html)
    else this.saveUnit(active.unit!, html)
  }

  /** Leave the active verse: save it (or revert it) and render it as plain HTML again. */
  commit = (options: { revert?: boolean } = {}) => {
    const active = this.active
    if (!active) return
    window.clearTimeout(this.autosaveTimer)
    this.active = null
    const edited = serializeDoc(active.view.state.doc, document)
    const html = options.revert ? active.startHtml : edited
    if (active.kind === 'verse') this.save(active.verse, html)
    else if (active.kind === 'note') this.saveNote(active.index, html)
    else if (active.kind === 'verseNote') this.saveVerseNote(active.verse, active.index, html)
    else if (active.kind === 'footnote') this.saveFootnote(active.footnote!, html)
    else this.saveUnit(active.unit!, html)
    if (!options.revert && !sameHtml(html, active.startHtml, document)) {
      this.undoStack.push(active.kind === 'verse' ? { kind: 'verse', verse: active.verse, html: active.startHtml }
        // Undo restores the whole verse as it was before these notes were edited.
        : active.kind === 'verseNote' ? { kind: 'verse', verse: active.verse, html: active.verseStart! }
        : active.kind === 'note' ? { kind: 'note', index: active.index, html: active.startHtml }
        : active.kind === 'footnote' ? { kind: 'footnote', footnote: active.footnote!, html: active.startHtml }
        : { kind: 'paragraph', unit: active.unit!, html: active.startHtml })
      if (this.undoStack.length > UNDO_LIMIT) this.undoStack.shift()
    }
    active.view.destroy()
    if (active.kind === 'paragraph') {
      // Until the save lands the edit shows as a preview over the paragraph's elements.
      const unit = active.unit!
      if (this.unitBusy(unit)) this.previewUnit(unit, html)
      else this.settleUnit(unit)
    } else if (sameHtml(html, active.startHtml, document)) {
      // Nothing changed this session: put the original DOM back (keeps footnote/tooltip listeners).
      active.wrapper.replaceChildren(...active.originalNodes)
    } else if (active.kind === 'note') {
      window.rbtReaderParaphrase?.setNote(active.index, html)
    } else if (active.kind === 'footnote') {
      active.wrapper.replaceChildren()
      window.rbtFootnotes?.setContent(active.footnote!.id, html)
    } else if (active.kind === 'verseNote') {
      window.rbtMediaModal?.setNotes(html)
    } else {
      this.render(active.verse, active.wrapper, active.refHtml)
    }
    if (options.revert && !sameHtml(edited, active.startHtml, document)) {
      this.showNotice(active.kind === 'verse' ? `Verse ${active.verse}: changes discarded.`
        : active.kind === 'footnote' ? `Footnote ${active.footnote!.ref}: changes discarded.`
        : active.kind === 'verseNote' ? `Verse ${active.verse} notes: changes discarded.`
        : `${PART_LABEL[active.kind]}: changes discarded.`)
    }
    this.emit()
  }

  done = () => this.commit()

  /**
   * The Undo button: step back in the open editor while it has history, otherwise restore
   * the most recently edited verse or paragraph to how it was before that edit (and save it).
   */
  undoLast = () => {
    const active = this.active
    if (active && undoDepth(active.view.state) > 0) {
      this.runCommand(undo)
      return
    }
    if (active) this.commit()
    const entry = this.undoStack.pop()
    if (!entry) return
    let target: HTMLElement | undefined
    if (entry.kind === 'verse') {
      this.save(entry.verse, entry.html)
      target = this.wrapperFor(entry.verse)
      if (target) this.render(entry.verse, target)
      this.showNotice(`Verse ${entry.verse}: last edit undone.`)
    } else if (entry.kind === 'note') {
      this.saveNote(entry.index, entry.html)
      window.rbtReaderParaphrase?.setNote(entry.index, entry.html)
      this.showNotice('Notes: last edit undone.')
    } else if (entry.kind === 'footnote') {
      this.saveFootnote(entry.footnote, entry.html)
      window.rbtFootnotes?.setContent(entry.footnote.id, entry.html)
      this.showNotice(`Footnote ${entry.footnote.ref}: last edit undone.`)
    } else {
      const unit = entry.unit
      if (!unit.blocks.length || unit.blocks.some((block) => !block.isConnected)) {
        this.showNotice('That paragraph has changed since, so the edit can no longer be undone.')
        this.emit()
        return
      }
      this.saveUnit(unit, entry.html)
      if (this.unitBusy(unit)) this.previewUnit(unit, entry.html)
      target = unit.overlay ?? unit.blocks[0]
      this.showNotice('Paraphrase: last edit undone.')
    }
    // The verse wrapper is display: contents, so measure what's inside it.
    const range = document.createRange()
    if (target) range.selectNodeContents(target)
    const box = target && range.getBoundingClientRect()
    if (box && (box.top < 0 || box.bottom > window.innerHeight)) {
      window.scrollBy({ top: box.top - window.innerHeight / 3, behavior: 'instant' })
    }
    this.emit()
  }

  private render(verse: string, wrapper: HTMLElement, refHtml?: string) {
    const record = this.verses.get(verse)
    if (!record) return
    const ref = refHtml ?? wrapper.querySelector('.verse_ref')?.outerHTML ?? ''
    wrapper.innerHTML = composeVerse(record.target, ref)
    wrapper.dataset.rendered = 'editor'
    wrapParentheses(wrapper)
  }

  // --- saving ----------------------------------------------------------------

  private save(verse: string, html: string) {
    const record = this.verses.get(verse)
    if (!record || sameHtml(html, record.target, document)) return
    record.target = html
    if (record.conflict) {
      record.conflict.mine = html
      this.emit()
      return
    }
    record.pending = html
    void this.runQueue(record)
  }

  private async runQueue(record: VerseRecord) {
    if (record.inFlight) return
    while (record.pending !== undefined && !record.conflict) {
      const html = record.pending
      record.pending = undefined
      record.inFlight = true
      record.status = 'saving'
      record.error = undefined
      this.emit()

      const result = await this.api.saveVerse(record.verse, html, record.hash)
      record.inFlight = false
      if (result.status === 'ok') {
        record.html = html
        record.hash = result.hash
        record.status = record.pending === undefined ? 'saved' : 'saving'
      } else if (result.status === 'conflict') {
        record.status = 'conflict'
        record.conflict = { html: result.html, hash: result.hash, mine: record.pending ?? html }
        record.pending = undefined
      } else {
        record.status = 'error'
        record.error = result.message
        record.pending ??= html
        this.emit()
        return
      }
    }
    this.emit()
  }

  retrySave = (verse: string) => {
    const record = this.verses.get(verse)
    if (record && record.status === 'error') void this.runQueue(record)
  }

  resolveConflict = (verse: string, keep: 'mine' | 'theirs') => {
    const record = this.verses.get(verse)
    const conflict = record?.conflict
    if (!record || !conflict) return
    record.conflict = undefined
    record.html = conflict.html
    record.hash = conflict.hash
    record.editable = roundTrips(conflict.html, document)
    if (keep === 'mine') {
      record.target = conflict.html
      record.status = undefined
      this.save(verse, conflict.mine)
    } else {
      record.target = conflict.html
      record.status = 'saved'
      if (this.active?.verse === verse) {
        window.clearTimeout(this.autosaveTimer)
        const active = this.active
        this.active = null
        active.view.destroy()
        this.render(verse, active.wrapper, active.refHtml)
      } else {
        const wrapper = this.wrapperFor(verse)
        if (wrapper) this.render(verse, wrapper)
      }
    }
    this.emit()
  }

  // --- notices ---------------------------------------------------------------

  private showNotice(text: string, verse?: string) {
    window.clearTimeout(this.noticeTimer)
    this.notice = { text, verse }
    this.emit()
    this.noticeTimer = window.setTimeout(() => {
      this.notice = null
      this.emit()
    }, 5000)
  }

  dismissNotice = () => {
    window.clearTimeout(this.noticeTimer)
    this.notice = null
    this.emit()
  }
}
