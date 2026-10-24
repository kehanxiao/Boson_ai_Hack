import type { ReactNode } from 'react'
import { CriteriaScores } from '../components/CriteriaScores'
import { MomentList } from '../components/MomentList'
import { useScorecard } from '../lib/useScorecard'
import { useSessionConfig } from '../lib/useSessionConfig'
import styles from './Scorecard.module.css'

/** GET /api/sessions/{id}/scorecard: verdict, criteria, timestamped moments, top 3 improvements. */
export function Scorecard({ sessionId }: { sessionId: string }) {
  const { state, retry } = useScorecard(sessionId)
  const { config } = useSessionConfig(sessionId) // optional: slide thumbnails and examiner name

  return (
    <main className={styles.page}>
      <header className={styles.header}>
        <div>
          <h1>Scorecard</h1>
          {config && <p>Examined by {config.character.name}</p>}
        </div>
        <a className={styles.again} href="/">Practice again</a>
      </header>

      {state.status === 'writing' && (
        <Status title="The examiner is writing your scorecard…" body="This takes about 15 seconds." busy />
      )}
      {state.status === 'waiting' && (
        <Status
          title="Waiting for the session log…"
          body="The examiner uploads it as the session ends, then the scorecard takes about 15 seconds. This page updates by itself."
          busy
        />
      )}
      {state.status === 'failed' && (
        <Status title="The scorecard couldn't be written." body={state.message}>
          <button onClick={retry}>Try again</button>
        </Status>
      )}

      {state.status === 'ready' && (
        <>
          <section className={styles.verdict}>
            <h2>Verdict</h2>
            <p>{state.card.verdict}</p>
          </section>

          <section>
            <h2>Scores</h2>
            <CriteriaScores criteria={state.card.criteria} />
          </section>

          <section>
            <h2>Moments</h2>
            <MomentList moments={state.card.moments} slides={config?.slides ?? []} />
          </section>

          <section>
            <h2>Top 3 improvements</h2>
            <ol className={styles.improvements}>
              {state.card.improvements.map((text) => (
                <li key={text}>{text}</li>
              ))}
            </ol>
          </section>
        </>
      )}
    </main>
  )
}

function Status({ title, body, busy, children }: { title: string; body: string; busy?: boolean; children?: ReactNode }) {
  return (
    <div className={styles.status} role="status" aria-live="polite">
      {busy && <span className={styles.spinner} aria-hidden />}
      <div>
        <strong>{title}</strong>
        <p>{body}</p>
        {children}
      </div>
    </div>
  )
}
