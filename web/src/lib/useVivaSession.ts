import { useCallback, useEffect, useReducer, useRef, useState } from 'react'
import type { CtlMsg } from './contract'
import type { AvatarTracks, VivaLink } from './link'
import { connectLive } from './liveLink'
import { initialView, reduceUi } from './sessionReducer'

interface Options {
  sessionId: string
  fake: boolean
  speed: number
  /** Fake mode only: the scripted presenter changed slide. */
  onReplaySlide?: (index: number) => void
}

export function useVivaSession({ sessionId, fake, speed, onReplaySlide }: Options) {
  const [view, dispatch] = useReducer(reduceUi, initialView)
  const [link, setLink] = useState<VivaLink | null>(null)
  const [avatar, setAvatar] = useState<AvatarTracks>({ video: null, audio: null })
  const [status, setStatus] = useState<'idle' | 'connecting' | 'running' | 'error'>('idle')
  const [error, setError] = useState<string | null>(null)
  const startingRef = useRef(false)
  const onSlideRef = useRef(onReplaySlide)
  useEffect(() => {
    onSlideRef.current = onReplaySlide
  }, [onReplaySlide])

  // Must run from a click: the live link starts audio playback.
  const start = useCallback(async () => {
    if (startingRef.current) return
    startingRef.current = true
    setStatus('connecting')
    setError(null)
    try {
      const next = fake
        ? (await import('./fakeAgent')).createFakeLink({ speed, onSlide: (i) => onSlideRef.current?.(i) })
        : await connectLive(sessionId)
      next.onUi((msg) => dispatch({ msg, at: next.elapsed() }))
      next.onAvatar(setAvatar)
      setLink(next)
      setStatus('running')
      next.send({ type: 'start' })
    } catch (err) {
      startingRef.current = false // allow retry
      setStatus('error')
      setError(err instanceof Error ? err.message : String(err))
    }
  }, [fake, speed, sessionId])

  useEffect(() => () => link?.close(), [link])

  const send = useCallback((msg: CtlMsg) => link?.send(msg), [link])

  return { view, link, avatar, status, error, start, send }
}
