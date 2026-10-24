import type { RemoteTrack } from 'livekit-client'
import type { CtlMsg, UiMsg } from './contract'

export interface AvatarTracks {
  video: RemoteTrack | null
  audio: RemoteTrack | null
}

/** What the Session page talks to: the real agent over LiveKit, or the fake replay. */
export interface VivaLink {
  readonly kind: 'live' | 'fake'
  send(msg: CtlMsg): void
  onUi(handler: (msg: UiMsg) => void): () => void
  onAvatar(handler: (tracks: AvatarTracks) => void): () => void
  /** Seconds since the session started (scaled by replay speed in fake mode). */
  elapsed(): number
  close(): void
}

/** Tiny pub/sub used by both link implementations. */
export function emitter<T>() {
  const handlers = new Set<(value: T) => void>()
  return {
    on(handler: (value: T) => void) {
      handlers.add(handler)
      return () => void handlers.delete(handler)
    },
    emit(value: T) {
      handlers.forEach((h) => h(value))
    },
  }
}
