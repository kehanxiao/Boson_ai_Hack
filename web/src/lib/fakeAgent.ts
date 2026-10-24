// Dev-only fake agent: replays demo/sample-log.jsonl as viva.ui events on a timer.
// Use with /session/demo?fake=1 (add &speed=4 to fast-forward).
import rawLog from '../../../demo/sample-log.jsonl?raw'
import type { AvatarTracks, VivaLink } from './link'
import { emitter } from './link'
import type { UiMsg } from './contract'
import { logToSteps, parseJsonl } from './fakeLog'

export function createFakeLink(opts: { speed?: number; onSlide?: (index: number) => void } = {}): VivaLink {
  const speed = opts.speed && opts.speed > 0 ? opts.speed : 1
  const ui = emitter<UiMsg>()
  const avatar = emitter<AvatarTracks>()
  const steps = logToSteps(parseJsonl(rawLog))
  const timers: number[] = []
  let startedAt: number | null = null

  const stop = () => timers.splice(0).forEach((id) => clearTimeout(id))

  const start = () => {
    stop()
    startedAt = performance.now()
    for (const step of steps) {
      const id = window.setTimeout(() => {
        if (step.ui) ui.emit(step.ui)
        if (step.slide !== undefined) opts.onSlide?.(step.slide)
      }, (step.t * 1000) / speed)
      timers.push(id)
    }
  }

  return {
    kind: 'fake',
    send(msg) {
      console.debug('[fake viva.ctl]', msg)
      if (msg.type === 'start') start()
      if (msg.type === 'phase' && msg.phase === 'end') {
        stop()
        ui.emit({ type: 'state', state: 'ended' })
        ui.emit({ type: 'ended', session_id: 'demo' })
      }
    },
    onUi: ui.on,
    onAvatar: avatar.on,
    elapsed: () => (startedAt === null ? 0 : ((performance.now() - startedAt) / 1000) * speed),
    close: stop,
  }
}
