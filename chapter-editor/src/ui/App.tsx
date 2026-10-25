import { useCallback, useSyncExternalStore } from 'react'
import { createPortal } from 'react-dom'
import type { ChapterEditorController } from '../controller'
import type { ParaphraseApi } from '../paraphraseApi'
import { InterlinearPopover } from './InterlinearPopover'
import { ParaphraseStudio } from './ParaphraseStudio'
import { StatusBar } from './StatusBar'
import { Toolbar } from './Toolbar'
import { useStudio } from './useStudio'

interface Props {
  controller: ChapterEditorController
  paraphraseApi: ParaphraseApi
  title: string
}

export function App({ controller, paraphraseApi, title }: Props) {
  const snapshot = useSyncExternalStore(controller.subscribe, controller.getSnapshot)
  const { active, hover } = snapshot
  const commit = useCallback(() => controller.commit(), [controller])
  const { open: studioOpen, mounted: studioMounted, openStudio, closeStudio } = useStudio(commit)

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
