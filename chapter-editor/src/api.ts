/** Client for translate/chapter_editor_api.py. */

export interface EditorConfig {
  book: string
  chapter: string
  csrf: string
  editUrl: string
  apiBase: string
}

export interface VerseData {
  verse: string
  html: string
  hash: string
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

export class Api {
  constructor(private config: EditorConfig) {}

  private url(path: string, params: Record<string, string>): string {
    return `${this.config.apiBase}${path}?${new URLSearchParams(params)}`
  }

  async chapter(): Promise<VerseData[]> {
    const response = await fetch(this.url('chapter/', { book: this.config.book, chapter: this.config.chapter }), {
      credentials: 'same-origin',
    })
    if (!response.ok) throw new Error(`Loading the chapter failed (${response.status})`)
    return (await response.json()).verses
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
        body: JSON.stringify({ book: this.config.book, chapter: this.config.chapter, verse, html, base_hash: baseHash }),
      })
    } catch {
      return { status: 'error', message: 'Network error' }
    }
    const data = await response.json().catch(() => ({}))
    if (response.ok) return { status: 'ok', hash: data.hash }
    if (response.status === 409) return { status: 'conflict', html: data.html, hash: data.hash }
    return { status: 'error', message: data.error || `Save failed (${response.status})` }
  }

  editUrl(verse: string): string {
    const params = new URLSearchParams({ book: this.config.book, chapter: this.config.chapter, verse })
    return `${this.config.editUrl}?${params}`
  }
}
