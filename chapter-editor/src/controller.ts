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
import { history, redo, undo } from 'prosemirror-history'
import { keymap } from 'prosemirror-keymap'
import type { Node as PMNode } from 'prosemirror-model'
import { EditorState, Plugin, TextSelection, type Command } from 'prosemirror-state'
import { Decoration, DecorationSet, EditorView } from 'prosemirror-view'
import { Api, type EditorConfig, type InterlinearWord } from './api'
import { applyTool, TOOLS, type Tool } from './commands'
import { parseVerse, roundTrips, sameHtml, schema, serializeDoc } from './schema'
import { closeText, composeVerse, wrapParentheses } from './verseDom'

const AUTOSAVE_DELAY_MS = 1000
const HOVER_OPEN_DELAY_MS = 150
const HOVER_CLOSE_DELAY_MS = 250
const EDIT_MODE_KEY = 'rbtChapterEditMode'

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
  verse: string
  wrapper: HTMLElement
  view: EditorView
  refHtml: string
  /** Stored HTML when this editing session began; Escape reverts to it. */
  startHtml: string
  /** The wrapper's DOM before editing, put back untouched if nothing changed. */
  originalNodes: Node[]
}

export interface VerseStatus {
  verse: string
  status: SaveStatus
  error?: string
  conflict?: { html: string; mine: string }
}

export interface Snapshot {
  editMode: boolean
  loading: boolean
  loadError: string | null
  active: { verse: string; view: EditorView; state: EditorState } | null
  statuses: VerseStatus[]
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
        verse: record.verse,
        status: record.status,
        error: record.error,
        conflict: record.conflict && { html: record.conflict.html, mine: record.conflict.mine },
      })
    }
    return {
      editMode: this.editMode,
      loading: this.loading,
      loadError: this.loadError,
      active: this.active && { verse: this.active.verse, view: this.active.view, state: this.active.view.state },
      statuses,
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
      this.pointVerseRefsAt('edit')
      if (!this.verses.size) void this.load()
    } else {
      this.commit()
      this.area.removeEventListener('mousedown', this.onAreaMouseDown)
      this.area.removeEventListener('click', this.onAreaClick)
      this.area.removeEventListener('mouseover', this.onAreaMouseOver)
      this.area.removeEventListener('mouseout', this.onAreaMouseOut)
      document.removeEventListener('mousedown', this.onDocumentMouseDown, true)
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
    return false
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
      plugins: [history(), keymap(this.editorKeymap()), keymap(baseKeymap), refPlugin],
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

    this.active = { verse, wrapper, view, refHtml, startHtml: record.target, originalNodes }
    const hit = view.posAtCoords(coords)
    const selection = hit
      ? TextSelection.near(view.state.doc.resolve(hit.pos))
      : TextSelection.atEnd(view.state.doc)
    view.dispatch(view.state.tr.setSelection(selection))
    view.focus()
    this.emit()
  }

  private editorKeymap(): Record<string, Command> {
    const bold = TOOLS.find((tool) => tool.id === 'bold')!
    return {
      'Mod-z': undo,
      'Shift-Mod-z': redo,
      'Mod-y': redo,
      'Mod-b': (state, dispatch) => {
        const tr = applyTool(state, bold)
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
    const tr = applyTool(view.state, tool)
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
    this.save(active.verse, serializeDoc(active.view.state.doc, document))
  }

  /** Leave the active verse: save it (or revert it) and render it as plain HTML again. */
  commit = (options: { revert?: boolean } = {}) => {
    const active = this.active
    if (!active) return
    window.clearTimeout(this.autosaveTimer)
    this.active = null
    const edited = serializeDoc(active.view.state.doc, document)
    const html = options.revert ? active.startHtml : edited
    this.save(active.verse, html)
    active.view.destroy()
    if (sameHtml(html, active.startHtml, document)) {
      // Nothing changed this session: put the original DOM back (keeps footnote/tooltip listeners).
      active.wrapper.replaceChildren(...active.originalNodes)
    } else {
      this.render(active.verse, active.wrapper, active.refHtml)
    }
    if (options.revert && !sameHtml(edited, active.startHtml, document)) {
      this.showNotice(`Verse ${active.verse}: changes discarded.`)
    }
    this.emit()
  }

  done = () => this.commit()

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
