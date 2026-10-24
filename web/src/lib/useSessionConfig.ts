import { useEffect, useState } from 'react'
import { fetchSessionConfig } from './api'
import type { SessionConfig } from './contract'

export function useSessionConfig(sessionId: string) {
  const [config, setConfig] = useState<SessionConfig | null>(null)
  const [error, setError] = useState<string | null>(null)
  useEffect(() => {
    let cancelled = false
    fetchSessionConfig(sessionId)
      .then((c) => !cancelled && setConfig(c))
      .catch((err) => !cancelled && setError(String(err?.message ?? err)))
    return () => {
      cancelled = true
    }
  }, [sessionId])
  return { config, error }
}
