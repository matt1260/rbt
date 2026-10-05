import { autoUpdate, flip, FloatingPortal, offset, shift, useFloating } from '@floating-ui/react'
import { undoDepth, redoDepth } from 'prosemirror-history'
import type { EditorState } from 'prosemirror-state'
import type { EditorView } from 'prosemirror-view'
import { useLayoutEffect, type MouseEvent } from 'react'
import { isToolActive, TOOLS } from '../commands'
import type { ChapterEditorController } from '../controller'

interface Props {
  controller: ChapterEditorController
  kind: 'verse' | 'paragraph' | 'note'
  verse: string
  view: EditorView
  state: EditorState
}

/** Floating toolbar pinned above the caret/selection of the verse being edited. */
export function Toolbar({ controller, kind, verse, view, state }: Props) {
  // Sun blocks belong to verses, quotes to paraphrase paragraphs (where h5 is the heading
  // above the paragraph); image notes take inline formatting only.
  const tools = kind === 'paragraph' ? TOOLS.filter((tool) => tool.id !== 'sun')
    : kind === 'note' ? TOOLS.filter((tool) => tool.kind !== 'block')
    : TOOLS.filter((tool) => tool.id !== 'quote')
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
    <FloatingPortal root={kind === 'note' ? view.dom.closest<HTMLElement>('dialog') : undefined}>
      <div
        ref={refs.setFloating}
        style={floatingStyles}
        className="rbt-ce-toolbar"
        role="toolbar"
        aria-label={kind === 'verse' ? `Format verse ${verse}` : kind === 'note' ? 'Format notes' : 'Format paragraph'}
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
        <button type="button" className="rbt-ce-tool rbt-ce-tool--done" title={`Done (Enter). Esc discards ${kind === 'note' ? 'these notes\'' : `this ${kind}'s`} changes.`}
          onMouseDown={keepFocus} onClick={controller.done}>Done</button>
      </div>
    </FloatingPortal>
  )
}
