import type { Scorecard, SessionConfig } from './contract'

export class ApiError extends Error {
  readonly status: number
  constructor(status: number, message: string) {
    super(message)
    this.status = status
  }
}

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

/** FastAPI errors: {detail: "text"} or {detail: [{msg, loc}]} for validation. */
async function errorMessage(res: Response): Promise<string> {
  try {
    const { detail } = await res.json()
    if (typeof detail === 'string') return detail
    if (Array.isArray(detail) && detail[0]?.msg) return `${detail[0].loc?.at(-1) ?? 'field'}: ${detail[0].msg}`
  } catch {
    // not JSON
  }
  return `HTTP ${res.status}`
}

/** POST /api/sessions (multipart). Renders and preps the deck, so it takes a few seconds. */
export async function createSession(form: FormData): Promise<{ session_id: string; slide_count: number }> {
  const res = await fetch(serverUrl('/api/sessions'), { method: 'POST', body: form })
  if (!res.ok) throw new Error(await errorMessage(res))
  return res.json()
}

/** 404 = no session log yet; 502 = generation failed (retryable). First call takes ~15 s. */
export async function fetchScorecard(sessionId: string): Promise<Scorecard> {
  const res = await fetch(serverUrl(`/api/sessions/${encodeURIComponent(sessionId)}/scorecard`))
  if (!res.ok) throw new ApiError(res.status, await errorMessage(res))
  return res.json()
}

export function fetchToken(room: string, identity: string): Promise<{ url: string; token: string }> {
  const q = new URLSearchParams({ room, identity })
  return getJson(`/token?${q}`)
}
