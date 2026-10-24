import type { SessionConfig } from './contract'

export const SERVER_URL = (import.meta.env.VITE_SERVER_URL || 'http://localhost:8000').replace(/\/$/, '')

/** Server paths like "/api/sessions/demo/slides/1.png" → absolute URL. */
export function serverUrl(path: string): string {
  return path.startsWith('/') ? `${SERVER_URL}${path}` : path
}

async function getJson<T>(path: string): Promise<T> {
  const res = await fetch(serverUrl(path))
  if (!res.ok) throw new Error(`${path}: HTTP ${res.status}`)
  return res.json() as Promise<T>
}

export async function fetchSessionConfig(sessionId: string): Promise<SessionConfig> {
  try {
    return await getJson<SessionConfig>(`/api/sessions/${encodeURIComponent(sessionId)}`)
  } catch (err) {
    if (sessionId !== 'demo') throw err
    // Server down: the demo session still works from the bundled fixture (no slide images).
    const fixture = await import('../../../demo/session-config.json')
    return fixture.default as SessionConfig
  }
}

export function fetchToken(room: string, identity: string): Promise<{ url: string; token: string }> {
  const q = new URLSearchParams({ room, identity })
  return getJson(`/token?${q}`)
}
