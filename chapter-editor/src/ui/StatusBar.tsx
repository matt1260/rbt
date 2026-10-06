import type { ChapterEditorController, Snapshot } from '../controller'

interface Props {
  controller: ChapterEditorController
  snapshot: Snapshot
  onOpenStudio: () => void
}

function summary(snapshot: Snapshot): { text: string; tone: 'idle' | 'busy' | 'ok' | 'bad' } {
  if (snapshot.loading) return { text: 'Loading chapter…', tone: 'busy' }
  if (snapshot.loadError) return { text: snapshot.loadError, tone: 'bad' }
  const saving = snapshot.statuses.filter((s) => s.status === 'saving')
  if (saving.length) {
    const what = saving.map((s) => (s.kind === 'paraphrase' ? 'paraphrase' : s.kind === 'footnote' ? `footnote ${s.verse.split('-').pop()}` : s.verse)).join(', ')
    return { text: `Saving ${what}…`, tone: 'busy' }
  }
  if (snapshot.statuses.some((s) => s.status === 'saved')) return { text: 'All changes saved', tone: 'ok' }
  if (snapshot.active) {
    const what = snapshot.active.kind === 'note' || snapshot.active.kind === 'verseNote' ? 'notes' : snapshot.active.kind === 'footnote' ? 'footnote' : `verse ${snapshot.active.verse}`
    return { text: `Editing ${what}`, tone: 'idle' }
  }
  return { text: 'Click any word to edit', tone: 'idle' }
}

/** Fixed bottom-right: edit mode switch, save state, conflicts and notices. */
export function StatusBar({ controller, snapshot, onOpenStudio }: Props) {
  const { text, tone } = summary(snapshot)
  const problems = snapshot.statuses.filter((s) => s.status === 'error' || s.status === 'conflict')

  return (
    <div className="rbt-ce-status" data-rbt-ui>
      {snapshot.editMode && problems.map((problem) => (
        <div key={problem.verse} className="rbt-ce-card rbt-ce-card--bad" role="alert">
          {problem.kind === 'footnote' ? (
            problem.status === 'conflict' ? (
              <>
                <strong>Footnote {problem.verse.split('-').pop()} was changed elsewhere</strong> (e.g. on the footnote edit page), so your last edit wasn't saved.
                <div className="rbt-ce-card__actions">
                  <button type="button" onClick={() => window.location.reload()}>Reload the page</button>
                </div>
              </>
            ) : (
              <>
                <strong>Footnote {problem.verse.split('-').pop()} didn't save:</strong> {problem.error}
                <div className="rbt-ce-card__actions">
                  <button type="button" onClick={() => controller.retryFootnote(problem.verse)}>Retry</button>
                </div>
              </>
            )
          ) : problem.kind === 'paraphrase' ? (
            problem.status === 'conflict' ? (
              <>
                <strong>The paraphrase was changed elsewhere</strong> (republished, or edited in another tab), so your last edit wasn't saved.
                <div className="rbt-ce-card__actions">
                  <button type="button" onClick={() => window.location.reload()}>Reload the page</button>
                </div>
              </>
            ) : (
              <>
                <strong>A paraphrase edit didn't save:</strong> {problem.error}
                <div className="rbt-ce-card__actions">
                  <button type="button" onClick={controller.retryParagraphSaves}>Retry</button>
                </div>
              </>
            )
          ) : problem.status === 'conflict' ? (
            <>
              <strong>Verse {problem.verse} was changed elsewhere</strong> (e.g. on the verse edit page) since this chapter loaded.
              <div className="rbt-ce-card__actions">
                <button type="button" onClick={() => controller.resolveConflict(problem.verse, 'theirs')}>Use saved version</button>
                <button type="button" onClick={() => controller.resolveConflict(problem.verse, 'mine')}>Overwrite with mine</button>
              </div>
            </>
          ) : (
            <>
              <strong>Verse {problem.verse} didn't save:</strong> {problem.error}
              <div className="rbt-ce-card__actions">
                <button type="button" onClick={() => controller.retrySave(problem.verse)}>Retry</button>
              </div>
            </>
          )}
        </div>
      ))}

      {snapshot.editMode && snapshot.notice && (
        <div className="rbt-ce-card" role="status">
          {snapshot.notice.text}
          <div className="rbt-ce-card__actions">
            {snapshot.notice.verse && <a href={controller.api.editUrl(snapshot.notice.verse)}>Open verse editor ↗</a>}
            <button type="button" onClick={controller.dismissNotice}>Dismiss</button>
          </div>
        </div>
      )}

      <div className="rbt-ce-pill">
        {snapshot.editMode && (
          <span className={`rbt-ce-pill__state rbt-ce-pill__state--${tone}`} title={text}>
            <span className="rbt-ce-pill__text">{text}</span>
            {snapshot.loadError && <button type="button" onClick={controller.retryLoad}>Retry</button>}
          </span>
        )}
        {snapshot.editMode && (
          <button
            type="button"
            className="rbt-ce-undo"
            onClick={controller.undoLast}
            disabled={!snapshot.canUndo}
            title="Undo the last change (⌘Z / Ctrl+Z)"
            aria-label="Undo the last change"
          >
            <svg viewBox="0 0 24 24" width="16" height="16" aria-hidden="true" focusable="false">
              <path d="M9 14 4 9l5-5" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" />
              <path d="M4 9h10.5a5.5 5.5 0 0 1 0 11H11" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" />
            </svg>
          </button>
        )}
        <button type="button" className="rbt-ce-studio" onClick={onOpenStudio} title="Generate, compare and publish the AI paraphrase of this chapter">
          <span className="rbt-ce-studio__full">Paraphrase studio</span>
          <span className="rbt-ce-studio__short" aria-hidden="true">Studio</span>
        </button>
        <button
          type="button"
          className="rbt-ce-switch"
          role="switch"
          aria-checked={snapshot.editMode}
          onClick={controller.toggleEditMode}
          title="Toggle inline editing (E)"
        >
          <span className="rbt-ce-switch__track"><span className="rbt-ce-switch__thumb" /></span>
          Edit (E)
        </button>
      </div>
    </div>
  )
}
