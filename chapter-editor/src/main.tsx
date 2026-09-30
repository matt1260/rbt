import { createRoot } from 'react-dom/client'
import type { EditorConfig } from './api'
import { ChapterEditorController } from './controller'
import { ParaphraseApi } from './paraphraseApi'
import { App } from './ui/App'
import './styles.css'

declare global {
  interface Window {
    /** Set by static/reader-paraphrase.js on NT chapter pages. */
    rbtReaderParaphrase?: { setHtml(html: string): void; show(): void }
  }
}

// Mounted by search/templates/nt_chapter.html for staff on English NT chapters.
const root = document.getElementById('chapter-editor-root')
const area = document.getElementById('paraphrase-area')

if (root && area) {
  const data = root.dataset
  const config: EditorConfig = {
    book: data.book ?? '',
    chapter: data.chapter ?? '',
    csrf: data.csrf ?? '',
    editUrl: data.editUrl ?? '/edit/',
    apiBase: data.apiBase ?? '/translate/api/chapter-editor/',
    paraphraseApiBase: data.paraphraseApi ?? '/translate/api/paraphrase/',
  }
  const controller = new ChapterEditorController(config, area)
  const paraphraseApi = new ParaphraseApi(config.paraphraseApiBase, config.book, config.chapter, config.csrf)
  createRoot(root).render(<App controller={controller} paraphraseApi={paraphraseApi} title={`${config.book} ${config.chapter}`} />)
}
