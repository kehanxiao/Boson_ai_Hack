import type { SessionView } from '../lib/sessionReducer'
import styles from './FactCheck.module.css'

const HIDE_DONE_AFTER_S = 15

const host = (url: string) => {
  try {
    return new URL(url).hostname.replace(/^www\./, '')
  } catch {
    return url
  }
}

/** Shows the examiner's live web search and the sources it used. */
export function FactCheck({ factcheck, now }: { factcheck: SessionView['factcheck']; now: number }) {
  if (!factcheck) return null
  if (factcheck.status === 'done' && now - factcheck.at > HIDE_DONE_AFTER_S) return null
  const searching = factcheck.status === 'searching'

  return (
    <div className={`${styles.chip} ${searching ? styles.searching : ''}`} role="status">
      <span className={styles.icon} aria-hidden>
        {searching ? '' : '✓'}
      </span>
      <span>{searching ? 'Checking a claim on the web…' : 'Claim checked'}</span>
      {factcheck.claim && <q className={styles.claim}>{factcheck.claim}</q>}
      {!searching &&
        factcheck.sources?.map((s) => (
          <a key={s} href={s} target="_blank" rel="noreferrer">
            {host(s)}
          </a>
        ))}
    </div>
  )
}
