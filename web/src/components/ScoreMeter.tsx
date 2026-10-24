import styles from './ScoreMeter.module.css'

/** Score out of 5 as a meter: fill colour carries severity, track is a faint step of the same hue.
 *  The number is printed in text ink, so the colour never carries the value alone. */
export function ScoreMeter({ score, label }: { score: number; label: string }) {
  const tone = score >= 4 ? styles.good : score === 3 ? styles.fair : styles.poor
  return (
    <div className={`${styles.meter} ${tone}`}>
      <div
        className={styles.track}
        role="meter"
        aria-label={label}
        aria-valuemin={1}
        aria-valuemax={5}
        aria-valuenow={score}
        aria-valuetext={`${score} out of 5`}
      >
        <div className={styles.fill} style={{ width: `${(score / 5) * 100}%` }} />
      </div>
      <span className={styles.value}>
        {score}
        <small>/5</small>
      </span>
    </div>
  )
}
