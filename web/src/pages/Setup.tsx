import { useState, type FormEvent } from 'react'
import characterPresets from '../../../demo/characters.json'
import { CharacterPicker } from '../components/CharacterPicker'
import { DurationField } from '../components/DurationField'
import { FileDrop } from '../components/FileDrop'
import { ScenarioPicker } from '../components/ScenarioPicker'
import { createSession } from '../lib/api'
import type { Character } from '../lib/contract'
import styles from './Setup.module.css'

const characters = characterPresets as Character[]

/** The 5 inputs → POST /api/sessions → /session/{id}. */
export function Setup() {
  const [scenario, setScenario] = useState('capstone_internship')
  const [character, setCharacter] = useState('supervisor')
  const [customText, setCustomText] = useState('')
  const [slides, setSlides] = useState<File | null>(null)
  const [supportDoc, setSupportDoc] = useState<File | null>(null)
  const [timeLimit, setTimeLimit] = useState(300)
  const [qa, setQa] = useState(120)
  const [notes, setNotes] = useState('')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const submit = async (e: FormEvent) => {
    e.preventDefault()
    if (!slides) return setError('Add your slides PDF first.')
    const form = new FormData()
    form.set('scenario', scenario)
    form.set('character', character)
    form.set('custom_text', customText)
    form.set('time_limit_s', String(timeLimit))
    form.set('qa_s', String(qa))
    form.set('notes', notes)
    form.set('slides', slides)
    if (supportDoc) form.set('support_doc', supportDoc)
    setBusy(true)
    setError(null)
    try {
      const { session_id } = await createSession(form)
      window.location.assign(`/session/${encodeURIComponent(session_id)}`)
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err))
      setBusy(false)
    }
  }

  return (
    <main className={styles.page}>
      <header className={styles.header}>
        <h1>Viva</h1>
        <p>Defend your slides in front of an AI examiner that listens, interrupts and keeps time.</p>
      </header>

      <form className={styles.form} onSubmit={submit}>
        <fieldset disabled={busy}>
          <section>
            <h2><span>1</span>Scenario</h2>
            <ScenarioPicker value={scenario} onChange={setScenario} />
          </section>

          <section>
            <h2><span>2</span>Examiner</h2>
            <CharacterPicker
              characters={characters}
              value={character}
              onChange={setCharacter}
              customText={customText}
              onCustomText={setCustomText}
            />
          </section>

          <section>
            <h2><span>3</span>Slides</h2>
            <FileDrop label="Slides PDF" hint="Required. Drop a PDF here or click to choose." accept=".pdf" file={slides} onFile={setSlides} />
            <div className={styles.gap} />
            <FileDrop
              label="Supporting document"
              hint="Optional: report, abstract or notes (PDF, TXT or MD)."
              accept=".pdf,.txt,.md"
              file={supportDoc}
              onFile={setSupportDoc}
            />
          </section>

          <section>
            <h2><span>4</span>Time</h2>
            <div className={styles.row}>
              <DurationField label="Presentation" seconds={timeLimit} onChange={setTimeLimit} min={60} max={3600} />
              <DurationField label="Q&A" seconds={qa} onChange={setQa} min={0} max={1800} />
            </div>
          </section>

          <section>
            <h2><span>5</span>Anything else</h2>
            <textarea
              rows={3}
              maxLength={2000}
              placeholder="e.g. Focus on my evaluation methodology."
              value={notes}
              onChange={(e) => setNotes(e.target.value)}
              aria-label="Notes for the examiner"
            />
          </section>
        </fieldset>

        <footer className={styles.footer}>
          {error && <p className={styles.error} role="alert">{error}</p>}
          <button type="submit" className="primary" disabled={busy || !slides}>
            {busy ? 'The examiner is reading your slides…' : 'Prepare my examiner'}
          </button>
          {busy && <p className={styles.note}>This takes about 5–10 seconds.</p>}
          <p className={styles.note}>
            No deck handy? <a href="/session/demo?fake=1">Watch a replayed demo session</a>.
          </p>
        </footer>
      </form>
    </main>
  )
}
