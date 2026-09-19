import { autoUpdate, flip, FloatingPortal, offset, shift, useFloating } from '@floating-ui/react'
import { useEffect, useLayoutEffect, useState } from 'react'
import type { InterlinearWord } from '../api'
import type { ChapterEditorController } from '../controller'

interface Props {
  controller: ChapterEditorController
  verse: string
  anchor: HTMLElement
}

type Load = { state: 'loading' } | { state: 'ready'; words: InterlinearWord[] } | { state: 'error'; message: string }

/** Same gender colouring as the verse edit page's interlinear (chapter_views_part1.py). */
function morphColour(description: string | null): string | undefined {
  if (!description) return undefined
  if (description.includes('Feminine')) return '#FF1493'
  if (description.includes('Masculine')) return 'blue'
  return undefined
}

/** Compact Greek interlinear shown while hovering a verse number. */
export function InterlinearPopover({ controller, verse, anchor }: Props) {
  const [load, setLoad] = useState<Load>({ state: 'loading' })
  const { refs, floatingStyles } = useFloating({
    placement: 'bottom-start',
    strategy: 'fixed',
    middleware: [offset(6), flip({ padding: 8 }), shift({ padding: 8 })],
    whileElementsMounted: autoUpdate,
  })

  useLayoutEffect(() => {
    refs.setReference(anchor)
  }, [refs, anchor])

  useEffect(() => {
    let cancelled = false
    setLoad({ state: 'loading' })
    controller.interlinear(verse).then(
      (words) => !cancelled && setLoad({ state: 'ready', words }),
      (error: Error) => !cancelled && setLoad({ state: 'error', message: error.message }),
    )
    return () => {
      cancelled = true
    }
  }, [controller, verse])

  return (
    <FloatingPortal>
      <div
        ref={refs.setFloating}
        style={floatingStyles}
        className="rbt-ce-interlinear"
        onMouseEnter={controller.keepHover}
        onMouseLeave={controller.scheduleHoverClose}
        data-rbt-ui
      >
        <div className="rbt-ce-interlinear__head">
          <span>Greek interlinear · verse {verse}</span>
          <a href={controller.api.editUrl(verse)}>Edit verse ↗</a>
        </div>
        {load.state === 'loading' && <div className="rbt-ce-interlinear__msg">Loading…</div>}
        {load.state === 'error' && <div className="rbt-ce-interlinear__msg">{load.message}</div>}
        {load.state === 'ready' && !load.words.length && <div className="rbt-ce-interlinear__msg">No interlinear for this verse.</div>}
        {load.state === 'ready' && load.words.length > 0 && (
          <div className="rbt-ce-interlinear__words">
            {load.words.map((word, index) => (
              <div key={index} className="rbt-ce-word" title={word.morph_desc ?? undefined}>
                <span className="rbt-ce-word__greek">{word.lemma}</span>
                <span className="rbt-ce-word__translit">{word.translit}</span>
                <span className="rbt-ce-word__english">{word.english}</span>
                <span className="rbt-ce-word__morph" style={{ color: morphColour(word.morph_desc) }}>{word.morph}</span>
                <span className="rbt-ce-word__strongs">{word.strongs}</span>
              </div>
            ))}
          </div>
        )}
      </div>
    </FloatingPortal>
  )
}
