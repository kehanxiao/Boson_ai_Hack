// Dev-only: derive viva.ui events from a session log (demo/sample-log.jsonl format).
// The real agent emits these itself; this approximates what it would send and when.
import type { ExaminerStateName, ReminderKind, UiMsg } from './contract'

export interface ReplayStep {
  t: number
  ui?: UiMsg
  /** Not a viva.ui event: lets the slide viewer follow the scripted presenter. */
  slide?: number
}

type LogLine = { t: number; kind: string; [key: string]: unknown }

const HOLD_FLOOR_S = 1.5
const speechSeconds = (text: string) => 0.6 + text.split(/\s+/).length * 0.33

export function parseJsonl(raw: string): LogLine[] {
  return raw
    .split('\n')
    .filter((line) => line.trim())
    .map((line) => JSON.parse(line) as LogLine)
}

export function logToSteps(lines: LogLine[], sessionId = 'demo'): ReplayStep[] {
  const steps: ReplayStep[] = []
  const state = (t: number, s: ExaminerStateName) => steps.push({ t, ui: { type: 'state', state: s } })
  let phase = 'presentation'
  let lastChunkT = 0
  let lastExaminerT = 0
  let holding = false

  for (const e of lines) {
    const t = e.t
    switch (e.kind) {
      case 'phase': {
        phase = String(e.phase)
        const map: Record<string, ExaminerStateName> = {
          presentation: 'listening', qa: 'qa', debrief: 'debrief', end: 'ended',
        }
        if (map[phase]) state(t, map[phase])
        if (phase === 'end') steps.push({ t, ui: { type: 'ended', session_id: sessionId } })
        break
      }
      case 'slide':
        steps.push({ t, slide: Number(e.index) })
        break
      case 'chunk':
        lastChunkT = t
        steps.push({ t, ui: { type: 'caption', role: 'presenter', text: String(e.text), lang: e.lang as string, t } })
        break
      case 'interjection':
        steps.push({ t, ui: { type: 'interjection', slide: Number(e.slide), reason: String(e.reason), t } })
        steps.push({ t, ui: { type: 'latency', metric: 'pause_to_interjection', ms: Math.round((t - lastChunkT) * 1000) } })
        break
      case 'examiner': {
        const text = String(e.text)
        steps.push({ t, ui: { type: 'caption', role: 'examiner', text, t } })
        if (phase === 'qa' && lastChunkT > lastExaminerT) {
          // Approximation: the log has no end-of-speech time, so measure from the chunk's commit.
          steps.push({ t, ui: { type: 'latency', metric: 'answer_end_to_reply', ms: Math.round((t - lastChunkT) * 1000) } })
        }
        lastExaminerT = t
        if (phase === 'presentation') {
          if (!holding) state(t, 'interjecting')
          state(t + speechSeconds(text) + (holding ? HOLD_FLOOR_S : 0), 'listening')
          holding = false
        }
        break
      }
      case 'reminder':
        steps.push({ t, ui: { type: 'reminder', kind: e.reminder as ReminderKind, acknowledged: null } })
        break
      case 'escalation':
        holding = true
        steps.push({ t, ui: { type: 'reminder', kind: e.for as ReminderKind, acknowledged: false } })
        state(t, 'holding_floor')
        break
      case 'ack':
        steps.push({ t, ui: { type: 'reminder', kind: e.for as ReminderKind, acknowledged: true } })
        break
      case 'factcheck':
        steps.push({
          t,
          ui: {
            type: 'factcheck',
            status: e.status as 'searching' | 'done',
            claim: e.claim as string | undefined,
            sources: e.sources as string[] | undefined,
          },
        })
        break
      // 'director' decisions are agent-internal: nothing to show.
    }
  }
  return steps.sort((a, b) => a.t - b.t) // stable: keeps same-t order
}
