import { autoUpdate, flip, FloatingPortal, offset, shift, useFloating } from '@floating-ui/react'
import { undoDepth, redoDepth } from 'prosemirror-history'
import type { EditorState } from 'prosemirror-state'
import type { EditorView } from 'prosemirror-view'
import { useLayoutEffect, useState, type MouseEvent } from 'react'
import { isToolActive, TOOLS } from '../commands'
import { selectedCue, type ChapterEditorController } from '../controller'

interface Props {
  controller: ChapterEditorController
  kind: 'verse' | 'paragraph' | 'note' | 'verseNote' | 'footnote'
  verse: string
  view: EditorView
  state: EditorState
}

/** Floating toolbar pinned above the caret/selection of the verse being edited. */
export function Toolbar({ controller, kind, verse, view, state }: Props) {
  // Sun blocks belong to verses, quotes to paraphrase paragraphs (where h5 is the heading
  // above the paragraph); image notes take inline formatting only.
  // Outside verses the sun is the inline one.
  const tools = kind === 'paragraph' ? TOOLS.filter((tool) => tool.id !== 'sun')
    : kind === 'note' || kind === 'verseNote' || kind === 'footnote' ? TOOLS.filter((tool) => tool.kind !== 'block')
    : TOOLS.filter((tool) => tool.id !== 'quote' && tool.id !== 'sun-inline')
  const [picking, setPicking] = useState(false)
  const cueSelected = kind === 'paragraph' && selectedCue(state)
  const { refs, floatingStyles, update } = useFloating({
    placement: 'top',
    strategy: 'fixed',
    middleware: [offset(10), flip({ padding: 8 }), shift({ padding: 8 })],
    whileElementsMounted: autoUpdate,
  })

  useLayoutEffect(() => {
    const { from, to } = state.selection
    refs.setPositionReference({
      contextElement: view.dom,
      getBoundingClientRect() {
        const start = view.coordsAtPos(from)
        const end = view.coordsAtPos(to, -1)
        const right = Math.abs(start.top - end.top) < 4 ? Math.max(end.right, start.right) : start.right
        return {
          x: start.left,
          y: start.top,
          left: start.left,
          top: start.top,
          right,
          bottom: start.bottom,
          width: right - start.left,
          height: start.bottom - start.top,
        }
      },
    })
    update()
  }, [refs, update, view, state])

  // Keep focus (and the selection) in the editor when a button is pressed.
  const keepFocus = (event: MouseEvent) => event.preventDefault()

  return (
    // Inside the image modal when editing its notes: a modal <dialog> sits above everything else.
    // (The footnote pop-up is an ordinary transformed box, so its toolbar stays in the body, above it.)
    <FloatingPortal root={kind === 'note' || kind === 'verseNote' ? view.dom.closest<HTMLElement>('dialog') : undefined}>
      {/* The row scrolls sideways on narrow screens, so the image picker hangs off this
          wrapper instead (a scrolling box would clip it). */}
      <div ref={refs.setFloating} style={floatingStyles} className="rbt-ce-toolbar-wrap" data-rbt-ui>
        <div
          className="rbt-ce-toolbar"
          role="toolbar"
          aria-label={kind === 'verse' ? `Format verse ${verse}` : kind === 'note' || kind === 'verseNote' ? 'Format notes' : kind === 'footnote' ? 'Format footnote' : 'Format paragraph'}
          data-rbt-ui
        >
          {tools.map((tool) => {
            const active = isToolActive(state, tool)
            return (
              <button
                key={tool.id}
                type="button"
                className={`rbt-ce-tool rbt-ce-tool--${tool.id}`}
                title={tool.title}
                aria-label={tool.title}
                aria-pressed={tool.kind === 'color' && !tool.spec ? undefined : active}
                onMouseDown={keepFocus}
                onClick={() => controller.runTool(tool)}
              >
                {tool.kind === 'color' && tool.spec ? <span className="rbt-ce-swatch" /> : tool.label}
              </button>
            )
          })}
          {kind === 'paragraph' && (
            <>
              <span className="rbt-ce-divider" />
              {cueSelected ? (
                <button type="button" className="rbt-ce-tool rbt-ce-tool--wide" title="Remove this image cue (Delete). The image stays available to add again."
                  onMouseDown={keepFocus} onClick={controller.removeSelectedCue}>Remove image</button>
              ) : (
                <button type="button" className="rbt-ce-tool rbt-ce-tool--image" title="Add an image cue at the caret" aria-label="Add image"
                  aria-expanded={picking} onMouseDown={keepFocus} onClick={() => setPicking((open) => !open)}>🖼</button>
              )}
            </>
          )}
          <span className="rbt-ce-divider" />
          <button type="button" className="rbt-ce-tool" title="Undo (⌘Z)" aria-label="Undo"
            disabled={!undoDepth(state)} onMouseDown={keepFocus} onClick={controller.undo}>↶</button>
          <button type="button" className="rbt-ce-tool" title="Redo (⇧⌘Z)" aria-label="Redo"
            disabled={!redoDepth(state)} onMouseDown={keepFocus} onClick={controller.redo}>↷</button>
          <span className="rbt-ce-divider" />
          {kind === 'verse' && (
            <a className="rbt-ce-tool rbt-ce-tool--link" href={controller.api.editUrl(verse)} title="Open the verse edit page"
              onMouseDown={keepFocus} onClick={() => controller.done()}>{verse} ↗</a>
          )}
          <button type="button" className="rbt-ce-tool rbt-ce-tool--done" title={`Done (Enter). Esc discards ${kind === 'note' || kind === 'verseNote' ? 'these notes\'' : `this ${kind}'s`} changes.`}
            onMouseDown={keepFocus} onClick={controller.done}>Done</button>
        </div>
        {picking && kind === 'paragraph' && (
          <MediaPicker controller={controller} onPick={(n) => { setPicking(false); controller.insertCue(n) }} />
        )}
      </div>
    </FloatingPortal>
  )
}

/** The chapter's images; picking one puts its cue at the caret. */
function MediaPicker({ controller, onPick }: { controller: ChapterEditorController; onPick: (n: number) => void }) {
  const choices = controller.mediaChoices()
  const keepFocus = (event: MouseEvent) => event.preventDefault()
  return (
    <div className="rbt-ce-media" role="listbox" aria-label="Chapter images">
      {choices.length === 0 && <p className="rbt-ce-media__empty">This chapter has no images.</p>}
      {choices.map((item) => (
        <button key={item.n} type="button" role="option" aria-selected={false} className="rbt-ce-media__item"
          onMouseDown={keepFocus} onClick={() => onPick(item.n)} title={item.title}>
          {item.thumb ? <img src={item.thumb} alt="" /> : <span className="rbt-ce-media__icon">▶</span>}
          <span className="rbt-ce-media__title">{item.title}</span>
          <span className="rbt-ce-media__placed">{item.placed ? `placed${item.placed > 1 ? ` ×${item.placed}` : ''}` : 'not placed'}</span>
        </button>
      ))}
    </div>
  )
}
