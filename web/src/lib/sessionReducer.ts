// Folds viva.ui events into what the Session page renders.
import type { ExaminerStateName, ReminderKind, Role, UiMsg } from './contract'

export interface Caption {
  id: number
  role: Role
  text: string
  lang?: string
  t: number
}

export interface SessionView {
  examiner: ExaminerStateName | 'idle'
  captions: Caption[]
  reminder: { kind: ReminderKind; acknowledged: boolean | null; at: number } | null
  factcheck: { status: 'searching' | 'done'; sources?: string[]; at: number } | null
  latency: Record<string, number[]>
  interjections: { slide: number; reason: string; t: number }[]
  qaStartedAt: number | null
  ended: boolean
}

export const initialView: SessionView = {
  examiner: 'idle',
  captions: [],
  reminder: null,
  factcheck: null,
  latency: {},
  interjections: [],
  qaStartedAt: null,
  ended: false,
}

const MAX_CAPTIONS = 60
let captionId = 0

/** `at` = session-clock seconds when the event arrived. */
export function reduceUi(view: SessionView, { msg, at }: { msg: UiMsg; at: number }): SessionView {
  switch (msg.type) {
    case 'state':
      return {
        ...view,
        examiner: msg.state,
        qaStartedAt: msg.state === 'qa' && view.qaStartedAt === null ? at : view.qaStartedAt,
      }
    case 'caption': {
      const caption = { id: ++captionId, role: msg.role, text: msg.text, lang: msg.lang, t: msg.t }
      return { ...view, captions: [...view.captions, caption].slice(-MAX_CAPTIONS) }
    }
    case 'interjection':
      return { ...view, interjections: [...view.interjections, { slide: msg.slide, reason: msg.reason, t: msg.t }] }
    case 'reminder':
      return { ...view, reminder: { kind: msg.kind, acknowledged: msg.acknowledged, at } }
    case 'factcheck':
      return { ...view, factcheck: { status: msg.status, sources: msg.sources, at } }
    case 'latency': {
      const prev = view.latency[msg.metric] ?? []
      return { ...view, latency: { ...view.latency, [msg.metric]: [...prev, msg.ms].slice(-20) } }
    }
    case 'ended':
      return { ...view, ended: true }
    default:
      return view
  }
}
