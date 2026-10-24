import { serverUrl } from '../lib/api'
import type { Scorecard, SlideInfo } from '../lib/contract'
import { mmss } from '../lib/format'
import styles from './MomentList.module.css'

type Kind = Scorecard['moments'][number]['kind']

// Status: always icon + label, never colour alone.
const KIND: Record<Kind, { icon: string; label: string }> = {
  strong: { icon: '✓', label: 'Strong' },
  weak: { icon: '!', label: 'Weak' },
  unacknowledged: { icon: '✕', label: 'Ignored reminder' },
}

interface Props {
  moments: Scorecard['moments']
  slides: SlideInfo[]
}

/** Timestamped moments with the presenter's own words and the slide they were on. */
export function MomentList({ moments, slides }: Props) {
  const count = (k: Kind) => moments.filter((m) => m.kind === k).length
  const slideFor = (n: number) => slides.find((s) => s.index === n)

  return (
    <>
      <p className={styles.summary}>
        {(Object.keys(KIND) as Kind[])
          .filter((k) => count(k) > 0)
          .map((k) => `${count(k)} ${KIND[k].label.toLowerCase()}`)
          .join(' · ')}
      </p>
      <ol className={styles.list}>
        {moments.map((m) => {
          const slide = slideFor(m.slide)
          return (
            <li key={`${m.t}-${m.kind}`} className={`${styles.item} ${styles[m.kind]}`}>
              <div className={styles.meta}>
                <span className={styles.time}>{mmss(m.t)}</span>
                <span className={styles.badge}>
                  <span aria-hidden>{KIND[m.kind].icon}</span> {KIND[m.kind].label}
                </span>
              </div>
              <figure className={styles.thumb}>
                {slide && <img src={serverUrl(slide.image_url)} alt="" loading="lazy" />}
                <figcaption>Slide {m.slide}</figcaption>
              </figure>
              <div className={styles.body}>
                <blockquote>“{m.quote}”</blockquote>
                <p>{m.note}</p>
              </div>
            </li>
          )
        })}
      </ol>
    </>
  )
}
