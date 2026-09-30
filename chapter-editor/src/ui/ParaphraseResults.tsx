import { useMemo, useState } from 'react'
import type { Candidate } from '../paraphraseApi'

export const MAX_COMPARE = 3
export const isBusy = (candidate: Candidate) => candidate.status === 'pending' || candidate.status === 'running'

function tokens(n: number | null) {
  if (n == null) return '—'
  return n >= 1000 ? `${(n / 1000).toFixed(1)}k` : String(n)
}

function seconds(ms: number) {
  const total = Math.max(0, Math.round(ms / 1000))
  return total >= 60 ? `${Math.floor(total / 60)}m ${total % 60}s` : `${total}s`
}

function elapsed(candidate: Candidate, now: number) {
  return seconds(now - Date.parse(candidate.started_at ?? candidate.created_at))
}

function when(iso: string) {
  return new Date(iso).toLocaleString(undefined, { month: 'short', day: 'numeric', hour: 'numeric', minute: '2-digit' })
}

function coverage(candidate: Candidate) {
  if (candidate.status !== 'done') return null
  const missing = candidate.missing_verses
  if (!missing.length) return <span className="rbt-ps__ok">all verses</span>
  const shown = missing.slice(0, 6).join(', ') + (missing.length > 6 ? '…' : '')
  return <span className="rbt-ps__warn" title={`Verses no paragraph covers: ${missing.join(', ')}`}>missing {shown}</span>
}

function Status({ candidate, now }: { candidate: Candidate; now: number }) {
  if (isBusy(candidate)) {
    return <span className="rbt-ps__status rbt-ps__status--busy">{candidate.status === 'pending' ? 'queued' : 'writing'} · {elapsed(candidate, now)}</span>
  }
  if (candidate.status === 'failed') {
    return <span className="rbt-ps__status rbt-ps__status--bad" title={candidate.error}>failed</span>
  }
  return <span className="rbt-ps__status rbt-ps__status--ok">done{candidate.duration_ms != null ? ` · ${seconds(candidate.duration_ms)}` : ''}</span>
}

interface TableProps {
  candidates: Candidate[]
  compare: string[]
  now: number
  busy: boolean
  onToggleCompare: (uid: string) => void
  onPublish: (candidate: Candidate) => void
  onUnpublish: () => void
  onDelete: (candidate: Candidate) => void
}

export function CandidateTable({ candidates, compare, now, busy, onToggleCompare, onPublish, onUnpublish, onDelete }: TableProps) {
  if (!candidates.length) return null
  return (
    <div className="rbt-ps__table-wrap">
      <table className="rbt-ps__table">
        <thead>
          <tr>
            <th scope="col"><span className="rbt-ps__sr">Compare</span></th>
            <th scope="col">Model</th>
            <th scope="col">Status</th>
            <th scope="col" title="Output tokens (hover for input and thinking)">Output</th>
            <th scope="col">Cost</th>
            <th scope="col">Verses</th>
            <th scope="col">Created</th>
            <th scope="col"><span className="rbt-ps__sr">Actions</span></th>
          </tr>
        </thead>
        <tbody>
          {candidates.map((candidate) => {
            const comparing = compare.includes(candidate.uid)
            return (
              <tr key={candidate.uid} className={candidate.is_published ? 'is-published' : undefined}>
                <td>
                  <input
                    type="checkbox"
                    aria-label={`Compare ${candidate.model}`}
                    checked={comparing}
                    disabled={!comparing && compare.length >= MAX_COMPARE}
                    onChange={() => onToggleCompare(candidate.uid)}
                  />
                </td>
                <td>
                  <strong>{candidate.model}</strong>
                  {candidate.is_published && <span className="rbt-ps__badge">Published</span>}
                  {candidate.stale && <span className="rbt-ps__badge rbt-ps__badge--warn" title="The chapter's verses changed after this was generated.">Older text</span>}
                  <div className="rbt-ps__sub">{candidate.prompt_name || 'custom prompt'}</div>
                </td>
                <td><Status candidate={candidate} now={now} /></td>
                <td title={`Input ${tokens(candidate.input_tokens)} · thinking ${tokens(candidate.thinking_tokens)}`}>{tokens(candidate.output_tokens)}</td>
                <td>{candidate.cost_usd != null ? `$${candidate.cost_usd.toFixed(3)}` : '—'}</td>
                <td>{coverage(candidate)}</td>
                <td className="rbt-ps__sub">{when(candidate.created_at)}{candidate.created_by ? ` · ${candidate.created_by}` : ''}</td>
                <td className="rbt-ps__actions">
                  {candidate.is_published ? (
                    <button type="button" disabled={busy} onClick={onUnpublish}>Unpublish</button>
                  ) : (
                    <>
                      {candidate.status === 'done' && <button type="button" disabled={busy} onClick={() => onPublish(candidate)}>Publish</button>}
                      {!isBusy(candidate) && <button type="button" className="rbt-ps__link" disabled={busy} onClick={() => onDelete(candidate)}>Delete</button>}
                    </>
                  )}
                </td>
              </tr>
            )
          })}
        </tbody>
      </table>
    </div>
  )
}

interface PaneProps {
  candidate: Candidate
  html: string | null | undefined
  now: number
  busy: boolean
  onPublish: (candidate: Candidate) => void
  onClose: () => void
}

export function PreviewPane({ candidate, html, now, busy, onPublish, onClose }: PaneProps) {
  const [width, setWidth] = useState<'desktop' | 'phone'>('desktop')
  // Preview in the chapter's own reading font and size.
  const pageStyle = useMemo(() => {
    const style = getComputedStyle(document.getElementById('paraphrase-area') ?? document.body)
    return { fontFamily: style.fontFamily, fontSize: style.fontSize }
  }, [])

  let body
  if (isBusy(candidate)) {
    body = <p className="rbt-ps__placeholder">Writing the chapter… {elapsed(candidate, now)}</p>
  } else if (candidate.status === 'failed') {
    body = <p className="rbt-ps__placeholder rbt-ps__warn">{candidate.error || 'Generation failed.'}</p>
  } else if (html == null) {
    body = <p className="rbt-ps__placeholder">Loading…</p>
  } else {
    body = <article className="rbt-paraphrase" dangerouslySetInnerHTML={{ __html: html }} />
  }

  return (
    <section className={`rbt-ps__pane rbt-ps__pane--${width}`} aria-label={`${candidate.model} preview`}>
      <header className="rbt-ps__pane-head">
        <strong>{candidate.model}</strong>
        {candidate.is_published && <span className="rbt-ps__badge">Published</span>}
        <span className="rbt-ps__spacer" />
        <div className="rbt-ps__segmented" role="group" aria-label="Preview width">
          <button type="button" aria-pressed={width === 'desktop'} onClick={() => setWidth('desktop')}>Desktop</button>
          <button type="button" aria-pressed={width === 'phone'} onClick={() => setWidth('phone')}>Phone</button>
        </div>
        {candidate.status === 'done' && !candidate.is_published && (
          <button type="button" className="rbt-ps__publish" disabled={busy} onClick={() => onPublish(candidate)}>Publish</button>
        )}
        <button type="button" className="rbt-ps__link" onClick={onClose} aria-label={`Stop comparing ${candidate.model}`}>×</button>
      </header>
      <div className="rbt-ps__frame">
        <div className="rbt-ps__page" style={pageStyle}>{body}</div>
      </div>
    </section>
  )
}
