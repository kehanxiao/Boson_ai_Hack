import type { Phase } from '../lib/contract'
import type { SessionView } from '../lib/sessionReducer'
import type { LinkStatus } from '../lib/useVivaSession'

interface Props {
  examiner: SessionView['examiner']
  status: LinkStatus
  onStart: () => void
  onPhase: (phase: Phase) => void
}

const PENDING: Partial<Record<LinkStatus, string>> = {
  connecting: 'Connecting…',
  waiting: 'Waiting for the examiner…',
}

/** Start, then manual phase buttons (sent as viva.ctl phase messages). */
export function SessionControls({ examiner, status, onStart, onPhase }: Props) {
  if (status !== 'running') {
    return (
      <button className="primary" onClick={onStart} disabled={status in PENDING}>
        {PENDING[status] ?? 'Start presentation'}
      </button>
    )
  }
  const done = examiner === 'debrief' || examiner === 'ended'
  const inPresentation = !done && examiner !== 'qa'
  return (
    <div style={{ display: 'flex', gap: 8 }}>
      <button onClick={() => onPhase('qa')} disabled={!inPresentation}>
        Go to Q&amp;A
      </button>
      <button onClick={() => onPhase('end')} disabled={examiner === 'ended'}>
        End
      </button>
    </div>
  )
}
