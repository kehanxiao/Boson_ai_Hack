import type { SessionView } from '../lib/sessionReducer'
import styles from './ExaminerState.module.css'

const LABEL: Record<SessionView['examiner'], string> = {
  idle: 'Not started',
  listening: 'Listening',
  interjecting: 'Interjecting',
  holding_floor: 'Holding the floor',
  qa: 'Q&A',
  debrief: 'Debrief',
  ended: 'Ended',
}

export function ExaminerState({ state }: { state: SessionView['examiner'] }) {
  return (
    <div className={`${styles.badge} ${styles[state]}`} role="status" aria-live="polite">
      <span className={styles.dot} />
      {LABEL[state]}
    </div>
  )
}
