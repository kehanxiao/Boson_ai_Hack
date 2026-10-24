import styles from './LatencyHud.module.css'

const median = (xs: number[]) => {
  const s = [...xs].sort((a, b) => a - b)
  const mid = Math.floor(s.length / 2)
  return s.length % 2 ? s[mid] : (s[mid - 1] + s[mid]) / 2
}

const LABEL: Record<string, string> = {
  pause_to_interjection: 'pause → interject',
  cancel_to_silence: 'cancel → silence',
  answer_end_to_reply: 'answer → reply',
}

/** Small corner readout of whatever latency metrics arrive (last / median, ms). Unknown metrics show by name. */
export function LatencyHud({ latency }: { latency: Record<string, number[]> }) {
  const metrics = Object.entries(latency)
  if (metrics.length === 0) return null
  return (
    <aside className={styles.hud} aria-label="Latency">
      {metrics.map(([name, values]) => (
        <div key={name} className={styles.row}>
          <span>{LABEL[name] ?? name.replaceAll('_', ' ')}</span>
          <span>{values.at(-1)}</span>
          <span className={styles.median}>med {Math.round(median(values))}</span>
        </div>
      ))}
    </aside>
  )
}
