import { useCallback, useEffect, useState } from 'react'
import { ApiError, fetchScorecard } from './api'
import type { Scorecard } from './contract'

export type ScorecardState =
  | { status: 'writing' } // request in flight (first generation takes ~15 s)
  | { status: 'waiting' } // 404: the agent hasn't uploaded the log yet; polling
  | { status: 'failed'; message: string }
  | { status: 'ready'; card: Scorecard }

const POLL_MS = 4000
const MAX_WAIT_MS = 3 * 60 * 1000

export function useScorecard(sessionId: string) {
  const [state, setState] = useState<ScorecardState>({ status: 'writing' })
  const [attempt, setAttempt] = useState(0)

  useEffect(() => {
    let cancelled = false
    let timer: number | undefined
    const started = Date.now()

    const load = async () => {
      if (cancelled) return
      try {
        const card = await fetchScorecard(sessionId)
        if (!cancelled) setState({ status: 'ready', card })
      } catch (err) {
        if (cancelled) return
        if (err instanceof ApiError && err.status === 404 && Date.now() - started < MAX_WAIT_MS) {
          setState({ status: 'waiting' })
          timer = window.setTimeout(load, POLL_MS)
          return
        }
        setState({ status: 'failed', message: err instanceof Error ? err.message : String(err) })
      }
    }
    void load()
    return () => {
      cancelled = true
      clearTimeout(timer)
    }
  }, [sessionId, attempt])

  const retry = useCallback(() => {
    setState({ status: 'writing' })
    setAttempt((n) => n + 1)
  }, [])

  return { state, retry }
}
