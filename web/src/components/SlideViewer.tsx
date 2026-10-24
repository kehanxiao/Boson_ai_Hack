import { useEffect, useState } from 'react'
import { serverUrl } from '../lib/api'
import type { SlideInfo } from '../lib/contract'
import styles from './SlideViewer.module.css'

interface Props {
  slides: SlideInfo[]
  index: number // 1-based
  onChange: (index: number) => void
}

const NEXT_KEYS = new Set(['ArrowRight', 'PageDown'])
const PREV_KEYS = new Set(['ArrowLeft', 'PageUp'])

/** Big slide with prev/next. Arrow keys and presentation clickers (PageUp/PageDown) work too. */
export function SlideViewer({ slides, index, onChange }: Props) {
  const total = slides.length
  const slide = slides[index - 1]
  const [failed, setFailed] = useState<Set<number>>(new Set())
  const go = (i: number) => i >= 1 && i <= total && i !== index && onChange(i)

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.target instanceof HTMLInputElement || e.target instanceof HTMLTextAreaElement) return
      if (NEXT_KEYS.has(e.key)) go(index + 1)
      else if (PREV_KEYS.has(e.key)) go(index - 1)
      else return
      e.preventDefault()
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  })

  // Preload the next slide so "next" is instant.
  useEffect(() => {
    const next = slides[index]
    if (next) new Image().src = serverUrl(next.image_url)
  }, [slides, index])

  if (!slide) return null
  return (
    <section className={styles.viewer}>
      <div className={styles.frame}>
        {failed.has(slide.index) ? (
          <div className={styles.fallback}>
            <span>Slide {slide.index}</span>
            <p>{slide.summary}</p>
          </div>
        ) : (
          <img
            src={serverUrl(slide.image_url)}
            alt={`Slide ${slide.index}: ${slide.summary}`}
            onError={() => setFailed((s) => new Set(s).add(slide.index))}
          />
        )}
      </div>
      <nav className={styles.nav}>
        <button onClick={() => go(index - 1)} disabled={index <= 1} aria-label="Previous slide">
          ←
        </button>
        <span className={styles.count}>
          {index} / {total}
        </span>
        <button onClick={() => go(index + 1)} disabled={index >= total} aria-label="Next slide">
          →
        </button>
      </nav>
    </section>
  )
}
