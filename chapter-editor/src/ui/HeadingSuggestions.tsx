import { useEffect, useMemo, useState } from 'react'
import type { Candidate, HeadingJob, ParaphraseApi, Provider } from '../paraphraseApi'

const POLL_MS = 3000

interface Props {
  api: ParaphraseApi
  candidate: Candidate
  html: string
  hash: string
  /** The model to ask: the first one ticked in the studio. */
  model: { provider: Provider; model: string } | null
  onChange: (html: string, hash: string) => void
}

interface Paragraph {
  verses: string
  heading: string
  start: string
}

/** The paraphrase's top-level paragraphs and quotes, as paraphrase.editable_blocks() counts them. */
function paragraphs(html: string): Paragraph[] {
  const doc = new DOMParser().parseFromString(`<div>${html}</div>`, 'text/html')
  const root = doc.body.firstElementChild
  if (!root) return []
  const blocks = Array.from(root.children).filter((el) => el.tagName === 'P' || el.tagName === 'BLOCKQUOTE')
  return blocks.map((block) => {
    const previous = block.previousElementSibling
    const heading = previous?.tagName === 'H5' ? previous.textContent?.trim() ?? '' : ''
    const words = (block.textContent ?? '').replace(/\s+/g, ' ').trim().split(' ')
    return {
      verses: block.getAttribute('data-v') ?? '',
      heading,
      start: words.slice(0, 9).join(' ') + (words.length > 9 ? '…' : ''),
    }
  })
}

/**
 * "Suggest headings" for one candidate in the Paraphrase Studio: asks a model for section
 * headings (search/paraphrase.py, in the background) and lists them by paragraph. Clicking
 * one puts it above that paragraph; the published paraphrase updates on the page as well.
 */
export function HeadingSuggestions({ api, candidate, html, hash, model, onChange }: Props) {
  const [job, setJob] = useState<HeadingJob>({ status: 'idle' })
  const [error, setError] = useState<string | null>(null)
  const [saving, setSaving] = useState(false)
  const [now, setNow] = useState(() => Date.now())
  const blocks = useMemo(() => paragraphs(html), [html])

  useEffect(() => {
    let cancelled = false
    api.headingJob(candidate.uid).then((result) => !cancelled && setJob(result), () => {})
    return () => { cancelled = true }
  }, [api, candidate.uid])

  useEffect(() => {
    if (job.status !== 'running') return
    const poll = window.setInterval(() => {
      api.headingJob(candidate.uid).then(setJob, () => {})
    }, POLL_MS)
    const tick = window.setInterval(() => setNow(Date.now()), 1000)
    return () => {
      window.clearInterval(poll)
      window.clearInterval(tick)
    }
  }, [api, candidate.uid, job.status])

  const start = async () => {
    if (!model) return
    setError(null)
    try {
      setJob(await api.suggestHeadings(candidate.uid, model.provider, model.model))
    } catch (e) {
      setError((e as Error).message)
    }
  }

  const apply = async (index: number, heading: string) => {
    setSaving(true)
    setError(null)
    try {
      const result = await api.setHeading(candidate.uid, index, heading, hash)
      onChange(result.html, result.hash)
      if (candidate.is_published) window.rbtReaderParaphrase?.setHtml(result.html, candidate.uid, result.hash)
    } catch (e) {
      setError((e as Error).message)
    } finally {
      setSaving(false)
    }
  }

  const running = job.status === 'running'
  const seconds = job.started ? Math.max(0, Math.round(now / 1000 - job.started)) : 0

  return (
    <div className="rbt-ps__headings">
      <div className="rbt-ps__headings-bar">
        <button type="button" onClick={start} disabled={!model || running || saving}
          title={model ? `Ask ${model.model} for section headings` : 'Tick a model on the left first'}>
          {running ? `Suggesting headings… ${seconds}s` : job.status === 'done' ? 'Suggest again' : 'Suggest headings'}
        </button>
        {job.status === 'done' && job.model && <span className="rbt-ps__sub">from {job.model}</span>}
        {job.status === 'failed' && <span className="rbt-ps__warn" title={job.error}>Failed: {job.error}</span>}
        {error && <span className="rbt-ps__warn">{error}</span>}
      </div>
      {job.status === 'done' && job.sections && (
        <ol className="rbt-ps__headings-list">
          {job.sections.map((section) => {
            const block = blocks[section.index]
            if (!block) return null
            return (
              <li key={section.index}>
                <div className="rbt-ps__sub">
                  ¶{section.index + 1}{block.verses ? ` · v${block.verses}` : ''} · {block.start}
                </div>
                <div className="rbt-ps__chips">
                  {section.options.map((option) => (
                    <button key={option} type="button" disabled={saving}
                      className={`rbt-ps__chip${block.heading === option ? ' is-current' : ''}`}
                      aria-pressed={block.heading === option}
                      onClick={() => void apply(section.index, block.heading === option ? '' : option)}
                      title={block.heading === option ? 'Remove this heading' : 'Put this heading above the paragraph'}>
                      {option}
                    </button>
                  ))}
                  {block.heading && !section.options.includes(block.heading) && (
                    <button type="button" className="rbt-ps__chip is-current" disabled={saving}
                      onClick={() => void apply(section.index, '')} title="Remove this heading">
                      {block.heading} ×
                    </button>
                  )}
                </div>
              </li>
            )
          })}
        </ol>
      )}
    </div>
  )
}
