import { createPortal } from 'react-dom'
import type { ParaphraseApi } from '../paraphraseApi'
import { ParaphraseStudio } from './ParaphraseStudio'
import { StudioButton } from './StatusBar'
import { useStudio } from './useStudio'

interface Props {
  paraphraseApi: ParaphraseApi
  title: string
}

/** OT chapter pages (chapter.html): the Paraphrase Studio alone; the inline verse editor is NT only. */
export function StudioApp({ paraphraseApi, title }: Props) {
  const { open, mounted, openStudio, closeStudio } = useStudio()
  return (
    <>
      {createPortal(
        <div className="rbt-ce-status" data-rbt-ui>
          <div className="rbt-ce-pill">
            <StudioButton onClick={openStudio} />
          </div>
        </div>,
        document.body,
      )}
      {mounted && <ParaphraseStudio api={paraphraseApi} title={title} open={open} onClose={closeStudio} />}
    </>
  )
}
