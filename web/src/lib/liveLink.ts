// Real agent link over LiveKit. Wiring per web/CLAUDE.md; signatures checked against livekit-client 2.23.
import { Room, RoomEvent, Track, type Participant, type RemoteTrack } from 'livekit-client'
import { fetchToken } from './api'
import { IDENTITY, TOPIC, type UiMsg } from './contract'
import { emitter, type AvatarTracks, type VivaLink } from './link'

export async function connectLive(sessionId: string): Promise<VivaLink> {
  const ui = emitter<UiMsg>()
  const avatar = emitter<AvatarTracks>()
  const tracks: AvatarTracks = { video: null, audio: null }
  let startedAt: number | null = null

  const room = new Room({ adaptiveStream: true, dynacast: true })

  room.registerTextStreamHandler(TOPIC.ui, async (reader) => {
    try {
      ui.emit(JSON.parse(await reader.readAll()) as UiMsg)
    } catch (err) {
      console.warn('[viva.ui] bad message', err)
    }
  })

  const setTrack = (track: RemoteTrack, p: Participant, present: boolean) => {
    if (p.identity !== IDENTITY.avatar) return
    if (track.kind === Track.Kind.Video) tracks.video = present ? track : null
    if (track.kind === Track.Kind.Audio) tracks.audio = present ? track : null
    avatar.emit({ ...tracks })
  }
  room.on(RoomEvent.TrackSubscribed, (track, _pub, p) => setTrack(track, p, true))
  room.on(RoomEvent.TrackUnsubscribed, (track, _pub, p) => setTrack(track, p, false))

  const { url, token } = await fetchToken(sessionId, IDENTITY.presenter)
  await room.connect(url, token)
  await room.startAudio() // called from the Start click, so autoplay is allowed
  // setMicrophoneEnabled publishes with source = microphone, which the agent listens for.
  await room.localParticipant.setMicrophoneEnabled(true)

  return {
    kind: 'live',
    send(msg) {
      if (msg.type === 'start') startedAt = performance.now()
      room.localParticipant
        .sendText(JSON.stringify(msg), { topic: TOPIC.ctl })
        .catch((err) => console.warn('[viva.ctl] send failed', err))
    },
    onUi: ui.on,
    onAvatar(handler) {
      handler({ ...tracks })
      return avatar.on(handler)
    },
    elapsed: () => (startedAt === null ? 0 : (performance.now() - startedAt) / 1000),
    close: () => void room.disconnect(),
  }
}
