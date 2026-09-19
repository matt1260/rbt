import type { ChapterEditorController, Snapshot } from '../controller'

interface Props {
  controller: ChapterEditorController
  snapshot: Snapshot
}

function summary(snapshot: Snapshot): { text: string; tone: 'idle' | 'busy' | 'ok' | 'bad' } {
  if (snapshot.loading) return { text: 'Loading chapter…', tone: 'busy' }
  if (snapshot.loadError) return { text: snapshot.loadError, tone: 'bad' }
  const saving = snapshot.statuses.filter((s) => s.status === 'saving')
  if (saving.length) return { text: `Saving ${saving.map((s) => s.verse).join(', ')}…`, tone: 'busy' }
  if (snapshot.statuses.some((s) => s.status === 'saved')) return { text: 'All changes saved', tone: 'ok' }
  if (snapshot.active) return { text: `Editing verse ${snapshot.active.verse}`, tone: 'idle' }
  return { text: 'Click any word to edit', tone: 'idle' }
}

/** Fixed bottom-right: edit mode switch, save state, conflicts and notices. */
export function StatusBar({ controller, snapshot }: Props) {
  const { text, tone } = summary(snapshot)
  const problems = snapshot.statuses.filter((s) => s.status === 'error' || s.status === 'conflict')

  return (
    <div className="rbt-ce-status" data-rbt-ui>
      {snapshot.editMode && problems.map((problem) => (
        <div key={problem.verse} className="rbt-ce-card rbt-ce-card--bad" role="alert">
          {problem.status === 'conflict' ? (
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
          <span className={`rbt-ce-pill__state rbt-ce-pill__state--${tone}`}>
            {text}
            {snapshot.loadError && <button type="button" onClick={controller.retryLoad}>Retry</button>}
          </span>
        )}
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
