import { useCallback, useEffect, useState, useSyncExternalStore } from 'react'
import { createPortal } from 'react-dom'
import type { ChapterEditorController } from '../controller'
import type { ParaphraseApi } from '../paraphraseApi'
import { InterlinearPopover } from './InterlinearPopover'
import { ParaphraseStudio } from './ParaphraseStudio'
import { StatusBar } from './StatusBar'
import { Toolbar } from './Toolbar'

interface Props {
  controller: ChapterEditorController
  paraphraseApi: ParaphraseApi
  title: string
}

export function App({ controller, paraphraseApi, title }: Props) {
  const snapshot = useSyncExternalStore(controller.subscribe, controller.getSnapshot)
  const { active, hover } = snapshot
  const [studioOpen, setStudioOpen] = useState(false)
  // Mounted on first open and kept afterwards, so the studio keeps its state when closed.
  const [studioMounted, setStudioMounted] = useState(false)

  const openStudio = useCallback(() => {
    controller.commit()
    setStudioMounted(true)
    setStudioOpen(true)
  }, [controller])
  const closeStudio = useCallback(() => setStudioOpen(false), [])

  // "Open the Paraphrase Studio" button in the empty paraphrase view (nt_chapter.html).
  useEffect(() => {
    const onClick = (event: MouseEvent) => {
      if ((event.target as Element).closest?.('[data-open-paraphrase-studio]')) openStudio()
    }
    document.addEventListener('click', onClick)
    return () => document.removeEventListener('click', onClick)
  }, [openStudio])

  return (
    <>
      {createPortal(<StatusBar controller={controller} snapshot={snapshot} onOpenStudio={openStudio} />, document.body)}
      {active && <Toolbar controller={controller} kind={active.kind} verse={active.verse} view={active.view} state={active.state} />}
      {snapshot.editMode && hover && (
        <InterlinearPopover key={hover.verse} controller={controller} verse={hover.verse} anchor={hover.anchor} />
      )}
      {studioMounted && <ParaphraseStudio api={paraphraseApi} title={title} open={studioOpen} onClose={closeStudio} />}
    </>
  )
}
