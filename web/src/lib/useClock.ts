import { useEffect, useState } from 'react'
import type { VivaLink } from './link'

/** Session-clock seconds, re-rendered a few times per second. */
export function useClock(link: VivaLink | null, stopped = false): number {
  const [now, setNow] = useState(0)
  useEffect(() => {
    if (!link || stopped) return
    const id = window.setInterval(() => setNow(link.elapsed()), 250)
    return () => clearInterval(id)
  }, [link, stopped])
  return now
}
