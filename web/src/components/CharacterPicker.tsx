import type { Character } from '../lib/contract'
import { ChoiceCard } from './ChoiceCard'
import styles from './Picker.module.css'

// interrupt_rate drives the agent's cooldown between interjections and its patience in Q&A.
const PACE: Record<string, string> = {
  high: 'Interrupts often, replies fast in Q&A',
  medium: 'Interrupts when it matters',
  low: 'Rarely interrupts, patient in Q&A',
}

interface Props {
  characters: Character[]
  value: string
  onChange: (id: string) => void
  customText: string
  onCustomText: (text: string) => void
}

export function CharacterPicker({ characters, value, onChange, customText, onCustomText }: Props) {
  return (
    <>
      <div className={styles.grid} role="radiogroup" aria-label="Examiner character">
        {characters.map((c) => {
          const [name, role] = c.name.split(', ')
          return (
            <ChoiceCard key={c.id} name="character" value={c.id} checked={value === c.id} onSelect={onChange} title={role ?? name}>
              <span className={styles.who}>{name}</span>
              <span>{PACE[c.interrupt_rate] ?? c.interrupt_rate}</span>
              <span className={styles.meter} aria-label={`Strictness ${c.strictness} of 5`}>
                Strictness{' '}
                {[1, 2, 3, 4, 5].map((i) => (
                  <i key={i} className={i <= c.strictness ? styles.on : ''} />
                ))}
              </span>
            </ChoiceCard>
          )
        })}
      </div>
      <label className={styles.field}>
        <span>Customise (optional)</span>
        <textarea
          rows={2}
          maxLength={2000}
          placeholder="e.g. A statistician who keeps asking about sample size and confidence intervals."
          value={customText}
          onChange={(e) => onCustomText(e.target.value)}
        />
        <small>Added to the character above, which keeps its voice and avatar.</small>
      </label>
    </>
  )
}
