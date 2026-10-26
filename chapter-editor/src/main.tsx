import { createRoot } from 'react-dom/client'
import type { EditorConfig } from './api'
import { ChapterEditorController } from './controller'
import { ParaphraseApi } from './paraphraseApi'
import { App } from './ui/App'
import './styles.css'

declare global {
  interface Window {
    /** Set by static/reader-paraphrase.js on chapter pages with a paraphrase view. */
    rbtReaderParaphrase?: {
      setHtml(html: string, uid?: string, hash?: string): void
      show(): void
      /** The stored notes of media item n in the published paraphrase. */
      noteHtml(n: number): string | null
      setNote(n: number, html: string): void
    }
    /** Set by static/chapter-viewer.js: update a footnote's text after it's edited. */
    rbtFootnotes?: { setContent(footnoteId: string, html: string): void }
    /** Set by static/media-modal.js: the image pop-up. */
    rbtMediaModal?: { setNotes(html: string): void }
  }
}

// Mounted for staff on English chapter pages: NT pages (nt_chapter.html) and, with
// data-mode="ot", Genesis and OT pages (chapter.html), whose word-for-word view holds the
// RBT Translation and (Genesis) the Hebrew literal.
const root = document.getElementById('chapter-editor-root')

if (root) {
  const data = root.dataset
  const ot = data.mode === 'ot'
  const config: EditorConfig = {
    book: data.book ?? '',
    chapter: data.chapter ?? '',
    csrf: data.csrf ?? '',
    editUrl: data.editUrl ?? '/edit/',
    apiBase: data.apiBase ?? '/translate/api/chapter-editor/',
    paraphraseApiBase: data.paraphraseApi ?? '/translate/api/paraphrase/',
    mode: ot ? 'ot' : 'nt',
  }
  const area = ot ? document.querySelector<HTMLElement>('[data-reader-verses]') : document.getElementById('paraphrase-area')
  if (area) {
    const controller = new ChapterEditorController(config, area)
    const paraphraseApi = new ParaphraseApi(config.paraphraseApiBase, config.book, config.chapter, config.csrf)
    createRoot(root).render(<App controller={controller} paraphraseApi={paraphraseApi} title={`${config.book} ${config.chapter}`} />)
  }
}
