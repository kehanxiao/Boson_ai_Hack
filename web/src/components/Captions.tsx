import { useEffect, useRef } from 'react'
import { LANG_LABEL, mmss } from '../lib/format'
import type { Caption } from '../lib/sessionReducer'
import styles from './Captions.module.css'

/** Rolling transcript; newest at the bottom, auto-scrolls (only this box, never the page). */
export function Captions({ captions }: { captions: Caption[] }) {
  const boxRef = useRef<HTMLElement>(null)
  useEffect(() => {
    const box = boxRef.current
    if (box) box.scrollTop = box.scrollHeight
  }, [captions.length])

  return (
    <section ref={boxRef} className={styles.captions} aria-label="Captions" aria-live="polite">
      {captions.length === 0 && <p className={styles.empty}>Captions appear here once the session starts.</p>}
      {captions.map((c) => (
        <div key={c.id} className={`${styles.line} ${styles[c.role]}`}>
          <div className={styles.meta}>
            <span>{c.role === 'examiner' ? 'Examiner' : 'You'}</span>
            <span className={styles.t}>{mmss(c.t)}</span>
            {c.lang && c.lang !== 'en' && <span className={styles.lang}>{LANG_LABEL[c.lang] ?? c.lang}</span>}
          </div>
          <p>{c.text}</p>
        </div>
      ))}
    </section>
  )
}
