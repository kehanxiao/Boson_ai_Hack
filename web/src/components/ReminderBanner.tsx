import type { SessionView } from '../lib/sessionReducer'
import styles from './ReminderBanner.module.css'

const TEXT = { t_minus_2: 'Two minutes left', time_up: "Time's up: wrap up now" } as const
const HIDE_ACKED_AFTER_S = 6

/** Reminders are visible as well as spoken, including whether the presenter acknowledged them. */
export function ReminderBanner({ reminder, now }: { reminder: SessionView['reminder']; now: number }) {
  if (!reminder) return null
  const { kind, acknowledged, at } = reminder
  if (acknowledged === true && now - at > HIDE_ACKED_AFTER_S) return null

  const tone = acknowledged === true ? styles.ok : acknowledged === false ? styles.bad : styles.pending
  const status =
    acknowledged === true ? 'Acknowledged' : acknowledged === false ? 'Not acknowledged: examiner has the floor' : 'Acknowledge it'

  return (
    <div className={`${styles.banner} ${tone}`} role="alert">
      <strong>{TEXT[kind]}</strong>
      <span>{status}</span>
    </div>
  )
}
