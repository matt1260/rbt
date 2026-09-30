/** Client for translate/paraphrase_api.py (the Paraphrase Studio). */

export type Provider = 'gemini' | 'openai'

export interface Candidate {
  uid: string
  batch_id: string
  provider: Provider
  model: string
  status: 'pending' | 'running' | 'done' | 'failed'
  error: string
  prompt_name: string
  missing_verses: number[]
  input_tokens: number | null
  output_tokens: number | null
  thinking_tokens: number | null
  cost_usd: number | null
  duration_ms: number | null
  is_published: boolean
  stale: boolean
  created_by: string
  created_at: string
  started_at: string | null
}

export interface Preset {
  name: string
  instructions: string
  word_guidance: string
  include_glossary: boolean
  is_default: boolean
  updated_by: string
  updated_at: string
}

export interface StudioState {
  candidates: Candidate[]
  presets: Preset[]
  models: Record<Provider, { models: string[]; configured: boolean }>
  output_rules: string
  glossary_terms: number
}

export interface GenerateRequest {
  models: [Provider, string][]
  instructions: string
  word_guidance: string
  include_glossary: boolean
  prompt_name: string
}

export class ParaphraseApi {
  constructor(
    private base: string,
    private book: string,
    private chapter: string,
    private csrf: string,
  ) {}

  private async request<T>(path: string, init?: RequestInit): Promise<T> {
    const response = await fetch(`${this.base}${path}`, { credentials: 'same-origin', ...init })
    const data = await response.json().catch(() => ({}))
    if (!response.ok) throw new Error(data.error || `Request failed (${response.status})`)
    return data as T
  }

  private post<T>(path: string, body: object): Promise<T> {
    return this.request<T>(path, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json', 'X-CSRFToken': this.csrf },
      body: JSON.stringify(body),
    })
  }

  private chapterParams() {
    return new URLSearchParams({ book: this.book, chapter: this.chapter })
  }

  state() {
    return this.request<StudioState>(`state/?${this.chapterParams()}`)
  }

  candidateHtml(uid: string) {
    return this.request<{ html: string; system_prompt: string; raw_output: string }>(`candidate/?uid=${encodeURIComponent(uid)}`)
  }

  generate(body: GenerateRequest) {
    return this.post<{ batch_id: string; uids: string[] }>('generate/', { book: this.book, chapter: this.chapter, ...body })
  }

  publish(uid: string) {
    return this.post<{ uid: string; html: string }>('publish/', { uid })
  }

  unpublish() {
    return this.post<{ unpublished: number }>('unpublish/', { book: this.book, chapter: this.chapter })
  }

  remove(uid: string) {
    return this.post<{ deleted: boolean }>('delete/', { uid })
  }

  savePreset(preset: Omit<Preset, 'updated_by' | 'updated_at'>) {
    return this.post<{ preset: Preset }>('preset/', preset)
  }
}
