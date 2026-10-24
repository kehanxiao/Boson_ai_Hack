import { mmss } from '../lib/format'
import styles from './DurationField.module.css'

interface Props {
  label: string
  seconds: number
  onChange: (seconds: number) => void
  min: number
  max: number
  step?: number
}

/** − / + stepper in 30-second steps; easier than typing a duration. */
export function DurationField({ label, seconds, onChange, min, max, step = 30 }: Props) {
  const set = (s: number) => onChange(Math.min(max, Math.max(min, s)))
  return (
    <div className={styles.field} role="group" aria-label={label}>
      <span className={styles.label}>{label}</span>
      <div className={styles.stepper}>
        <button type="button" onClick={() => set(seconds - step)} disabled={seconds <= min} aria-label={`Less ${label}`}>
          −
        </button>
        <output aria-live="polite">{mmss(seconds)}</output>
        <button type="button" onClick={() => set(seconds + step)} disabled={seconds >= max} aria-label={`More ${label}`}>
          +
        </button>
      </div>
    </div>
  )
}
