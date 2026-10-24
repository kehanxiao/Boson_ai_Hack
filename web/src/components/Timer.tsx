import { mmss } from '../lib/format'
import styles from './Timer.module.css'

interface Props {
  label: string
  elapsedS: number
  limitS: number
  warnAtS?: number
}

/** Counts down; turns amber at T−warnAtS and red (counting overtime) past zero. */
export function Timer({ label, elapsedS, limitS, warnAtS = 120 }: Props) {
  const remaining = limitS - elapsedS
  const tone = remaining <= 0 ? styles.over : remaining <= warnAtS ? styles.warn : ''
  return (
    <div className={`${styles.timer} ${tone}`} aria-label={`${label} time remaining`}>
      <span className={styles.label}>{label}</span>
      <span className={styles.value}>{remaining <= 0 ? `+${mmss(-remaining)}` : mmss(remaining)}</span>
    </div>
  )
}
