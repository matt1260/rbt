import { useSyncExternalStore } from 'react'
import { createPortal } from 'react-dom'
import type { ChapterEditorController } from '../controller'
import { InterlinearPopover } from './InterlinearPopover'
import { StatusBar } from './StatusBar'
import { Toolbar } from './Toolbar'

export function App({ controller }: { controller: ChapterEditorController }) {
  const snapshot = useSyncExternalStore(controller.subscribe, controller.getSnapshot)
  const { active, hover } = snapshot

  return (
    <>
      {createPortal(<StatusBar controller={controller} snapshot={snapshot} />, document.body)}
      {active && <Toolbar controller={controller} verse={active.verse} view={active.view} state={active.state} />}
      {snapshot.editMode && hover && (
        <InterlinearPopover key={hover.verse} controller={controller} verse={hover.verse} anchor={hover.anchor} />
      )}
    </>
  )
}
