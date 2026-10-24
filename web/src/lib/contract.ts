// Mirror of PLAN.md → "Interfaces between A and B". Fixed contract: don't change without Role A.

export const IDENTITY = {
  agent: 'viva-agent',
  avatar: 'boson-avatar',
  presenter: 'presenter',
} as const

export const TOPIC = { ctl: 'viva.ctl', ui: 'viva.ui' } as const

// viva.ctl (web → agent)
export type Phase = 'presentation' | 'qa' | 'end'
export type CtlMsg =
  | { type: 'start' }
  | { type: 'slide'; index: number }
  | { type: 'phase'; phase: Phase }

// viva.ui (agent → web)
export type ExaminerStateName =
  | 'listening'
  | 'interjecting'
  | 'holding_floor'
  | 'qa'
  | 'debrief'
  | 'ended'
export type ReminderKind = 't_minus_2' | 'time_up'
export type Role = 'presenter' | 'examiner'

/** Agent-measured metrics (definitions in PLAN.md). The web side may add its own. */
export type LatencyMetric = 'pause_to_interjection' | 'cancel_to_silence' | 'answer_end_to_reply'

export type UiMsg =
  | { type: 'state'; state: ExaminerStateName }
  | { type: 'caption'; role: Role; text: string; lang?: string; t: number }
  | { type: 'interjection'; slide: number; reason: string; t: number }
  | { type: 'reminder'; kind: ReminderKind; acknowledged: boolean | null }
  | { type: 'factcheck'; status: 'searching' | 'done'; claim?: string; sources?: string[] }
  | { type: 'latency'; metric: LatencyMetric | (string & {}); ms: number }
  | { type: 'ended'; session_id: string }

// Server API
export interface Character {
  id: string
  name: string
  persona: string
  voice: string
  avatar_id: string
  interrupt_rate: string
  strictness: number
}

export interface SlideInfo {
  index: number
  image_url: string
  summary: string
  claims: string[]
  weak_points: string[]
  questions: string[]
}

export interface SessionConfig {
  session_id: string
  scenario: string
  time_limit_s: number
  qa_s: number
  notes: string
  instructions: string
  avatar?: boolean // false: voice only; missing means true
  character: Character
  slides: SlideInfo[]
}

export interface Scorecard {
  verdict: string
  criteria: { name: string; score_1_5: number; comment: string }[]
  improvements: string[]
  moments: {
    t: number
    slide: number
    kind: 'strong' | 'weak' | 'unacknowledged'
    quote: string
    note: string
  }[]
}
