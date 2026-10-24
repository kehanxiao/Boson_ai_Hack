import type { Scorecard } from '../lib/contract'
import styles from './CriteriaScores.module.css'
import { ScoreMeter } from './ScoreMeter'

export function CriteriaScores({ criteria }: { criteria: Scorecard['criteria'] }) {
  return (
    <ul className={styles.list}>
      {criteria.map((c) => (
        <li key={c.name}>
          <div className={styles.head}>
            <span className={styles.name}>{c.name}</span>
            <ScoreMeter score={c.score_1_5} label={c.name} />
          </div>
          <p>{c.comment}</p>
        </li>
      ))}
    </ul>
  )
}
