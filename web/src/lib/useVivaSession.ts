import { useCallback, useEffect, useReducer, useRef, useState } from 'react'
import type { CtlMsg } from './contract'
import type { AvatarTracks, VivaLink } from './link'
import { connectLive } from './liveLink'
import { initialView, reduceUi } from './sessionReducer'

export type LinkStatus = 'idle' | 'connecting' | 'waiting' | 'running' | 'error'

interface Options {
  sessionId: string
  fake: boolean
  speed: number
  /** Fake mode only: the scripted presenter changed slide. */
  onReplaySlide?: (index: number) => void
  /** The slide on screen, re-sent once the agent is listening (it assumes slide 1). */
  currentSlide?: () => number
}

// The agent joins the room a few seconds before it listens to viva.ctl (avatar + Realtime setup),
// so a lone {type:"start"} can be lost. It ignores repeats, so we re-send until it answers.
const START_RETRY_MS = 2000

export function useVivaSession({ sessionId, fake, speed, onReplaySlide, currentSlide }: Options) {
  const [view, dispatch] = useReducer(reduceUi, initialView)
  const [link, setLink] = useState<VivaLink | null>(null)
  const [avatar, setAvatar] = useState<AvatarTracks>({ video: null, audio: null })
  const [status, setStatus] = useState<LinkStatus>('idle')
  const [error, setError] = useState<string | null>(null)
  const startingRef = useRef(false)
  const onSlideRef = useRef(onReplaySlide)
  const slideRef = useRef(currentSlide)
  useEffect(() => {
    onSlideRef.current = onReplaySlide
    slideRef.current = currentSlide
  }, [onReplaySlide, currentSlide])

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
      let answered = false
      let retry: number | undefined
      next.onUi((msg) => {
        if (!answered) {
          answered = true
          clearInterval(retry)
          setStatus('running')
          const slide = slideRef.current?.() ?? 1
          if (next.kind === 'live' && slide !== 1) next.send({ type: 'slide', index: slide })
        }
        dispatch({ msg, at: next.elapsed() })
      })
      next.onAvatar(setAvatar)
      setLink(next)
      setStatus('waiting')
      next.send({ type: 'start' })
      if (next.kind === 'live') retry = window.setInterval(() => next.send({ type: 'start' }), START_RETRY_MS)
      const close = next.close
      next.close = () => {
        clearInterval(retry)
        close()
      }
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
