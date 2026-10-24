import type { Phase } from '../lib/contract'
import type { SessionView } from '../lib/sessionReducer'

interface Props {
  examiner: SessionView['examiner']
  status: 'idle' | 'connecting' | 'running' | 'error'
  onStart: () => void
  onPhase: (phase: Phase) => void
}

/** Start, then manual phase buttons (sent as viva.ctl phase messages). */
export function SessionControls({ examiner, status, onStart, onPhase }: Props) {
  if (status === 'idle' || status === 'error' || status === 'connecting') {
    return (
      <button className="primary" onClick={onStart} disabled={status === 'connecting'}>
        {status === 'connecting' ? 'Connecting…' : 'Start presentation'}
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
