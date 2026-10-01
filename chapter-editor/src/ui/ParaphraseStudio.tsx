import { useCallback, useEffect, useMemo, useState } from 'react'
import { createPortal } from 'react-dom'
import type { Candidate, ParaphraseApi, Preset, Provider, StudioState } from '../paraphraseApi'
import { CandidateTable, MAX_COMPARE, PreviewPane, isBusy } from './ParaphraseResults'

interface Props {
  api: ParaphraseApi
  title: string
  open: boolean
  onClose: () => void
}

interface Draft {
  presetName: string
  instructions: string
  wordGuidance: string
  includeGlossary: boolean
}

const DRAFT_KEY = 'rbtParaphraseDraft'
const MODELS_KEY = 'rbtParaphraseModels'
const POLL_MS = 3000

function loadJson<T>(key: string, fallback: T): T {
  try {
    const value = localStorage.getItem(key)
    return value ? (JSON.parse(value) as T) : fallback
  } catch {
    return fallback
  }
}

function saveJson(key: string, value: unknown) {
  try {
    localStorage.setItem(key, JSON.stringify(value))
  } catch {
    // Private mode etc.: the draft just isn't remembered.
  }
}

const fromPreset = (preset: Preset): Draft => ({
  presetName: preset.name,
  instructions: preset.instructions,
  wordGuidance: preset.word_guidance,
  includeGlossary: preset.include_glossary,
})

const modelKey = (provider: Provider, model: string) => `${provider}:${model}`

const EMPTY_PARAPHRASE = '<p class="rbt-paraphrase__empty">No paraphrase is published for this chapter yet.</p>'

/**
 * Staff tool for AI chapter paraphrases: tune the prompt, run several models at once,
 * compare the results side by side (desktop and phone width) and publish one.
 * Generations run on the server, so the studio can be closed while they finish.
 */
export function ParaphraseStudio({ api, title, open, onClose }: Props) {
  const [state, setState] = useState<StudioState | null>(null)
  const [loadError, setLoadError] = useState<string | null>(null)
  const [draft, setDraft] = useState<Draft | null>(() => loadJson<Draft | null>(DRAFT_KEY, null))
  const [selected, setSelected] = useState<string[]>(() => loadJson(MODELS_KEY, [modelKey('gemini', 'gemini-3.8-flash')]))
  const [compare, setCompare] = useState<string[]>([])
  const [html, setHtml] = useState<Record<string, string | null>>({})
  const [action, setAction] = useState<string | null>(null)
  const [message, setMessage] = useState<{ text: string; tone: 'ok' | 'bad' } | null>(null)
  const [now, setNow] = useState(() => Date.now())

  const refresh = useCallback(async () => {
    try {
      setState(await api.state())
      setLoadError(null)
    } catch (error) {
      setLoadError((error as Error).message)
    }
  }, [api])

  useEffect(() => {
    if (open) void refresh()
  }, [open, refresh])

  useEffect(() => {
    if (!state || draft) return
    const preset = state.presets.find((p) => p.is_default) ?? state.presets[0]
    if (preset) setDraft(fromPreset(preset))
  }, [state, draft])

  useEffect(() => {
    if (draft) saveJson(DRAFT_KEY, draft)
  }, [draft])

  useEffect(() => saveJson(MODELS_KEY, selected), [selected])

  const generating = state?.candidates.some(isBusy) ?? false
  useEffect(() => {
    if (!open || !generating) return
    const poll = window.setInterval(() => void refresh(), POLL_MS)
    const tick = window.setInterval(() => setNow(Date.now()), 1000)
    return () => {
      window.clearInterval(poll)
      window.clearInterval(tick)
    }
  }, [open, generating, refresh])

  // First load: compare the published paraphrase with the newest batch.
  useEffect(() => {
    if (!state || compare.length || !state.candidates.length) return
    const published = state.candidates.find((c) => c.is_published)
    const newestBatch = state.candidates[0].batch_id
    const batch = state.candidates.filter((c) => c.batch_id === newestBatch).map((c) => c.uid)
    setCompare([...new Set([...(published ? [published.uid] : []), ...batch])].slice(0, MAX_COMPARE))
  }, [state, compare.length])

  // Fetch the HTML of compared candidates once they're done.
  useEffect(() => {
    if (!state) return
    for (const uid of compare) {
      const candidate = state.candidates.find((c) => c.uid === uid)
      if (candidate?.status !== 'done' || html[uid] !== undefined) continue
      setHtml((current) => ({ ...current, [uid]: null }))
      api.candidateHtml(uid).then(
        (result) => setHtml((current) => ({ ...current, [uid]: result.html })),
        () => setHtml((current) => {
          const { [uid]: _failed, ...rest } = current
          return rest
        }),
      )
    }
  }, [api, state, compare, html])

  useEffect(() => {
    if (!open) return
    const previous = document.body.style.overflow
    document.body.style.overflow = 'hidden'
    const onKey = (event: KeyboardEvent) => {
      if (event.key === 'Escape') onClose()
    }
    document.addEventListener('keydown', onKey)
    return () => {
      document.body.style.overflow = previous
      document.removeEventListener('keydown', onKey)
    }
  }, [open, onClose])

  const run = async (label: string, work: () => Promise<unknown>, success?: string) => {
    setAction(label)
    setMessage(null)
    try {
      await work()
      if (success) setMessage({ text: success, tone: 'ok' })
    } catch (error) {
      setMessage({ text: (error as Error).message, tone: 'bad' })
    } finally {
      setAction(null)
    }
  }

  const availableModels = useMemo(() => {
    if (!state) return [] as { provider: Provider; model: string; configured: boolean }[]
    return (Object.entries(state.models) as [Provider, StudioState['models'][Provider]][]).flatMap(([provider, info]) =>
      info.models.map((model) => ({ provider, model, configured: info.configured })),
    )
  }, [state])

  const chosen = availableModels.filter((m) => m.configured && selected.includes(modelKey(m.provider, m.model)))
  const savedPreset = state?.presets.find((p) => p.name === draft?.presetName)
  const dirty = !!draft && (!savedPreset
    || savedPreset.instructions !== draft.instructions
    || savedPreset.word_guidance !== draft.wordGuidance
    || savedPreset.include_glossary !== draft.includeGlossary)

  const generate = () => {
    if (!draft || !chosen.length) return
    void run('generate', async () => {
      const result = await api.generate({
        models: chosen.map((m) => [m.provider, m.model]),
        instructions: draft.instructions,
        word_guidance: draft.wordGuidance,
        include_glossary: draft.includeGlossary,
        prompt_name: dirty ? `${draft.presetName} (edited)` : draft.presetName,
      })
      setCompare(result.uids.slice(0, MAX_COMPARE))
      await refresh()
    }, `Generating with ${chosen.length} model${chosen.length === 1 ? '' : 's'}. This takes a few minutes; you can close the studio meanwhile.`)
  }

  const savePreset = (asNew: boolean, makeDefault = false) => {
    if (!draft) return
    const name = asNew ? window.prompt('Name for the new preset', `${draft.presetName} copy`)?.trim() : draft.presetName
    if (!name) return
    void run('preset', async () => {
      const result = await api.savePreset({
        name,
        instructions: draft.instructions,
        word_guidance: draft.wordGuidance,
        include_glossary: draft.includeGlossary,
        is_default: makeDefault || !!savedPreset?.is_default && !asNew,
      })
      setDraft((current) => current && { ...current, presetName: result.preset.name })
      await refresh()
    }, `Saved preset "${name}".`)
  }

  const publish = (candidate: Candidate) => {
    if (!window.confirm(`Publish the ${candidate.model} paraphrase? Readers will see it immediately.`)) return
    void run('publish', async () => {
      const result = await api.publish(candidate.uid)
      window.rbtReaderParaphrase?.setHtml(result.html, result.uid, result.hash)
      await refresh()
    }, 'Published. Readers now see this paraphrase.')
  }

  const unpublish = () => {
    if (!window.confirm('Unpublish? Readers will no longer see a paraphrase for this chapter.')) return
    void run('unpublish', async () => {
      await api.unpublish()
      window.rbtReaderParaphrase?.setHtml(EMPTY_PARAPHRASE)
      await refresh()
    }, 'Unpublished.')
  }

  const remove = (candidate: Candidate) => {
    if (!window.confirm(`Delete the ${candidate.model} candidate? This can't be undone.`)) return
    void run('delete', async () => {
      await api.remove(candidate.uid)
      setCompare((current) => current.filter((uid) => uid !== candidate.uid))
      await refresh()
    })
  }

  const toggleCompare = (uid: string) =>
    setCompare((current) => current.includes(uid) ? current.filter((u) => u !== uid) : [...current, uid].slice(-MAX_COMPARE))

  if (!open) return null

  const candidatesByUid = new Map(state?.candidates.map((c) => [c.uid, c]))

  return createPortal(
    <div className="rbt-ps" role="dialog" aria-modal="true" aria-label={`Paraphrase Studio: ${title}`} data-rbt-ui>
      <div className="rbt-ps__backdrop" onClick={onClose} />
      <div className="rbt-ps__panel">
        <header className="rbt-ps__header">
          <h2>Paraphrase Studio <span>{title}</span></h2>
          {message && <p className={`rbt-ps__message rbt-ps__message--${message.tone}`} role="status">{message.text}</p>}
          <button type="button" className="rbt-ps__close" onClick={onClose} aria-label="Close (Esc)">×</button>
        </header>

        {!state && (
          <div className="rbt-ps__loading">
            {loadError ? <>{loadError} <button type="button" onClick={() => void refresh()}>Retry</button></> : 'Loading…'}
          </div>
        )}

        {state && draft && (
          <div className="rbt-ps__body">
            <aside className="rbt-ps__side">
              <section>
                <h3>Prompt</h3>
                <div className="rbt-ps__row">
                  <select
                    value={draft.presetName}
                    aria-label="Preset"
                    onChange={(event) => {
                      const preset = state.presets.find((p) => p.name === event.target.value)
                      if (preset && (!dirty || window.confirm('Discard your unsaved prompt changes?'))) setDraft(fromPreset(preset))
                    }}
                  >
                    {!savedPreset && <option value={draft.presetName}>{draft.presetName}</option>}
                    {state.presets.map((preset) => (
                      <option key={preset.name} value={preset.name}>{preset.name}{preset.is_default ? ' (default)' : ''}</option>
                    ))}
                  </select>
                  <button type="button" onClick={() => savePreset(false)} disabled={!dirty || !!action}>Save</button>
                  <button type="button" onClick={() => savePreset(true)} disabled={!!action}>Save as…</button>
                </div>
                <p className="rbt-ps__hint">
                  {dirty ? 'Unsaved changes.' : `Saved${savedPreset?.updated_by ? ` by ${savedPreset.updated_by}` : ''}.`}
                  {savedPreset && !savedPreset.is_default && !dirty && (
                    <> <button type="button" className="rbt-ps__link" onClick={() => savePreset(false, true)}>Make default</button></>
                  )}
                </p>
                <label className="rbt-ps__label" htmlFor="rbt-ps-instructions">Style, paraphrase level and smoothing</label>
                <textarea
                  id="rbt-ps-instructions"
                  rows={14}
                  value={draft.instructions}
                  onChange={(event) => setDraft({ ...draft, instructions: event.target.value })}
                />
                <label className="rbt-ps__label" htmlFor="rbt-ps-words">Word and usage guidance</label>
                <textarea
                  id="rbt-ps-words"
                  rows={5}
                  placeholder={'One per line, e.g.\nLogos: keep "the Logos Ratio", never "the Word"'}
                  value={draft.wordGuidance}
                  onChange={(event) => setDraft({ ...draft, wordGuidance: event.target.value })}
                />
                <label className="rbt-ps__check">
                  <input
                    type="checkbox"
                    checked={draft.includeGlossary}
                    onChange={(event) => setDraft({ ...draft, includeGlossary: event.target.checked })}
                  />
                  Include the translation glossary ({state.glossary_terms} active term{state.glossary_terms === 1 ? '' : 's'})
                </label>
                <details className="rbt-ps__rules">
                  <summary>Fixed rules: fidelity and output format (always appended)</summary>
                  <pre>{state.output_rules}</pre>
                </details>
              </section>

              <section>
                <h3>Models</h3>
                {(Object.keys(state.models) as Provider[]).map((provider) => (
                  <div key={provider} className="rbt-ps__models" role="group" aria-labelledby={`rbt-ps-models-${provider}`}>
                    <div id={`rbt-ps-models-${provider}`} className="rbt-ps__models-name">
                      {provider === 'gemini' ? 'Gemini' : 'OpenAI'}
                      {!state.models[provider].configured && <span className="rbt-ps__warn"> · no API key on this server</span>}
                    </div>
                    {state.models[provider].models.map((model) => {
                      const key = modelKey(provider, model)
                      return (
                        <label key={key} className="rbt-ps__check">
                          <input
                            type="checkbox"
                            disabled={!state.models[provider].configured}
                            checked={selected.includes(key)}
                            onChange={() => setSelected((current) => current.includes(key) ? current.filter((k) => k !== key) : [...current, key])}
                          />
                          {model}
                        </label>
                      )
                    })}
                  </div>
                ))}
                <button
                  type="button"
                  className="rbt-ps__generate"
                  onClick={generate}
                  disabled={!chosen.length || !draft.instructions.trim() || action === 'generate'}
                >
                  {action === 'generate' ? 'Starting…' : `Generate with ${chosen.length || 'no'} model${chosen.length === 1 ? '' : 's'}`}
                </button>
                <p className="rbt-ps__hint">All selected models run at once, in the background.</p>
              </section>
            </aside>

            <main className="rbt-ps__main">
              <CandidateTable
                candidates={state.candidates}
                compare={compare}
                now={now}
                busy={!!action}
                onToggleCompare={toggleCompare}
                onPublish={publish}
                onUnpublish={unpublish}
                onDelete={remove}
              />
              <div className="rbt-ps__compare">
                {compare.length === 0 && (
                  <p className="rbt-ps__empty">
                    {state.candidates.length ? 'Tick up to three candidates above to compare them here.' : 'Nothing generated for this chapter yet. Pick models and press Generate.'}
                  </p>
                )}
                {compare.map((uid) => {
                  const candidate = candidatesByUid.get(uid)
                  return candidate ? (
                    <PreviewPane
                      key={uid}
                      candidate={candidate}
                      html={html[uid]}
                      now={now}
                      busy={!!action}
                      onPublish={publish}
                      onClose={() => toggleCompare(uid)}
                    />
                  ) : null
                })}
              </div>
            </main>
          </div>
        )}
      </div>
    </div>,
    document.body,
  )
}
