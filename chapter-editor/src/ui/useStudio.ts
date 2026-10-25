import { useCallback, useEffect, useState } from 'react'

/**
 * The Paraphrase Studio's open state. It mounts on first open and stays mounted, so it keeps
 * its state when closed. The "Open the Paraphrase Studio" button in an empty paraphrase view
 * (data-open-paraphrase-studio) opens it too. beforeOpen runs first (the NT editor commits
 * the verse being edited).
 */
export function useStudio(beforeOpen?: () => void) {
  const [open, setOpen] = useState(false)
  const [mounted, setMounted] = useState(false)

  const openStudio = useCallback(() => {
    beforeOpen?.()
    setMounted(true)
    setOpen(true)
  }, [beforeOpen])
  const closeStudio = useCallback(() => setOpen(false), [])

  useEffect(() => {
    const onClick = (event: MouseEvent) => {
      if ((event.target as Element).closest?.('[data-open-paraphrase-studio]')) openStudio()
    }
    document.addEventListener('click', onClick)
    return () => document.removeEventListener('click', onClick)
  }, [openStudio])

  return { open, mounted, openStudio, closeStudio }
}
