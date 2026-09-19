import { createRoot } from 'react-dom/client'
import type { EditorConfig } from './api'
import { ChapterEditorController } from './controller'
import { App } from './ui/App'
import './styles.css'

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
  }
  const controller = new ChapterEditorController(config, area)
  createRoot(root).render(<App controller={controller} />)
}
