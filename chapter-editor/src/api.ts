import { verseNumber } from './verseDom'

/**
 * Client for translate/chapter_editor_api.py (NT chapters), or in OT mode for the OT editor's
 * endpoints (translate/ot_editor.py: chapter_texts, save_verse).
 */

export interface EditorConfig {
  book: string
  chapter: string
  csrf: string
  editUrl: string
  apiBase: string
  paraphraseApiBase: string
  /** 'ot' on Genesis and OT chapter pages. */
  mode?: 'nt' | 'ot'
}

export interface VerseData {
  /** The record key (verseDom.ts keyOf); NT verses use the verse number. */
  key?: string
  verse: string
  html: string
  hash: string
  /** OT: the verse's hebrewdata ref (Gen.1.1) and which text ('paraphrase' or 'literal'). */
  ref?: string
  text?: string
}

export interface InterlinearWord {
  strongs: string
  translit: string
  lemma: string
  english: string
  morph: string
  morph_desc: string
}

export type SaveResult =
  | { status: 'ok'; hash: string }
  | { status: 'conflict'; html: string; hash: string }
  | { status: 'error'; message: string }

export type BlockSaveResult =
  | { status: 'ok'; hash: string; html: string }
  | { status: 'conflict' }
  | { status: 'error'; message: string }

export class Api {
  /** OT: where each record key saves (its ref and text), from chapter(). */
  private otTargets = new Map<string, { ref: string; text: string }>()

  constructor(private config: EditorConfig) {}

  get isOt(): boolean {
    return this.config.mode === 'ot'
  }

  private url(path: string, params: Record<string, string>): string {
    return `${this.config.apiBase}${path}?${new URLSearchParams(params)}`
  }

  async chapter(): Promise<VerseData[]> {
    const response = await fetch(this.url('chapter/', { book: this.config.book, chapter: this.config.chapter }), {
      credentials: 'same-origin',
    })
    if (!response.ok) throw new Error(`Loading the chapter failed (${response.status})`)
    const verses: VerseData[] = (await response.json()).verses
    for (const v of verses) if (v.key && v.ref && v.text) this.otTargets.set(v.key, { ref: v.ref, text: v.text })
    return verses
  }

  async interlinear(verse: string): Promise<InterlinearWord[]> {
    const response = await fetch(
      this.url('interlinear/', { book: this.config.book, chapter: this.config.chapter, verse }),
      { credentials: 'same-origin' },
    )
    if (!response.ok) throw new Error(`Loading the interlinear failed (${response.status})`)
    return (await response.json()).words
  }

  async saveVerse(verse: string, html: string, baseHash: string): Promise<SaveResult> {
    let response: Response
    try {
      response = await fetch(`${this.config.apiBase}verse/`, {
        method: 'POST',
        credentials: 'same-origin',
        // keepalive lets a save started while leaving the page (e.g. clicking a verse
        // number to open the verse editor) finish after navigation.
        keepalive: html.length < 60_000,
        headers: { 'Content-Type': 'application/json', 'X-CSRFToken': this.config.csrf },
        body: JSON.stringify(this.verseBody(verse, html, baseHash)),
      })
    } catch {
      return { status: 'error', message: 'Network error' }
    }
    const data = await response.json().catch(() => ({}))
    if (response.ok) return { status: 'ok', hash: data.hash }
    if (response.status === 409) return { status: 'conflict', html: data.html, hash: data.hash }
    return { status: 'error', message: data.error || `Save failed (${response.status})` }
  }

  /**
   * Replace `count` paragraphs of a published paraphrase, from `index`, with html: an optional
   * <h5> then one or more <p>/<blockquote> (translate/paraphrase_api.py edit_block).
   */
  async saveParaphraseBlock(uid: string, index: number, count: number, html: string, baseHash: string): Promise<BlockSaveResult> {
    let response: Response
    try {
      response = await fetch(`${this.config.paraphraseApiBase}edit-block/`, {
        method: 'POST',
        credentials: 'same-origin',
        keepalive: html.length < 60_000,
        headers: { 'Content-Type': 'application/json', 'X-CSRFToken': this.config.csrf },
        body: JSON.stringify({ uid, index, count, html, base_hash: baseHash }),
      })
    } catch {
      return { status: 'error', message: 'Network error' }
    }
    const data = await response.json().catch(() => ({}))
    if (response.ok) return { status: 'ok', hash: data.hash, html: data.html }
    if (response.status === 409) return { status: 'conflict' }
    return { status: 'error', message: data.error || `Save failed (${response.status})` }
  }

  /** Replace the notes of one media item of a published paraphrase (translate/paraphrase_api.py edit_note). */
  async saveParaphraseNote(uid: string, n: number, html: string, baseHash: string): Promise<BlockSaveResult> {
    let response: Response
    try {
      response = await fetch(`${this.config.paraphraseApiBase}edit-note/`, {
        method: 'POST',
        credentials: 'same-origin',
        keepalive: html.length < 60_000,
        headers: { 'Content-Type': 'application/json', 'X-CSRFToken': this.config.csrf },
        body: JSON.stringify({ uid, n, html, base_hash: baseHash }),
      })
    } catch {
      return { status: 'error', message: 'Network error' }
    }
    const data = await response.json().catch(() => ({}))
    if (response.ok) return { status: 'ok', hash: data.hash, html: data.html }
    if (response.status === 409) return { status: 'conflict' }
    return { status: 'error', message: data.error || `Save failed (${response.status})` }
  }

  /** One footnote of this chapter's book, as stored (translate/chapter_editor_api.py footnote). */
  async footnote(ref: string): Promise<{ html: string; hash: string } | { error: string }> {
    try {
      const response = await fetch(this.url('footnote/', { book: this.config.book, ref }), { credentials: 'same-origin' })
      const data = await response.json().catch(() => ({}))
      return response.ok ? { html: data.html ?? '', hash: data.hash ?? '' } : { error: data.error || `Loading failed (${response.status})` }
    } catch {
      return { error: 'Network error' }
    }
  }

  async saveFootnote(chapter: string, verse: string, ref: string, html: string, baseHash: string): Promise<BlockSaveResult> {
    let response: Response
    try {
      response = await fetch(`${this.config.apiBase}footnote/`, {
        method: 'POST',
        credentials: 'same-origin',
        keepalive: html.length < 60_000,
        headers: { 'Content-Type': 'application/json', 'X-CSRFToken': this.config.csrf },
        body: JSON.stringify({ book: this.config.book, chapter, verse, ref, html, base_hash: baseHash }),
      })
    } catch {
      return { status: 'error', message: 'Network error' }
    }
    const data = await response.json().catch(() => ({}))
    if (response.ok) return { status: 'ok', hash: data.hash, html: data.html }
    if (response.status === 409) return { status: 'conflict' }
    return { status: 'error', message: data.error || `Save failed (${response.status})` }
  }

  /** The save request for a verse (key): NT chapter_editor_api.verse, or OT ot_editor.save_verse. */
  private verseBody(key: string, html: string, baseHash: string): object {
    const target = this.otTargets.get(key)
    if (this.isOt && target) return { verse_ref: target.ref, field: target.text, html, base_hash: baseHash }
    return { book: this.config.book, chapter: this.config.chapter, verse: key, html, base_hash: baseHash }
  }

  /** The verse edit page (NT /edit/, OT /translate/ot/) for a verse or record key. */
  editUrl(key: string): string {
    const params = new URLSearchParams({ book: this.config.book, chapter: this.config.chapter, verse: verseNumber(key) })
    return `${this.config.editUrl}?${params}`
  }
}
