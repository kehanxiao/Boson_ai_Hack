import { ChoiceCard } from './ChoiceCard'
import styles from './Picker.module.css'

// Ids match server/instructions.py SCENARIOS.
const SCENARIOS = [
  { id: 'thesis_defense', title: 'Thesis defense', blurb: 'A committee examiner probing your research and its evidence.' },
  { id: 'capstone_internship', title: 'Capstone / internship', blurb: 'A supervisor weighing rigour and real-world value.' },
  { id: 'assignment_oral', title: 'Assignment oral', blurb: 'An instructor checking you understand your own work.' },
] as const

export function ScenarioPicker({ value, onChange }: { value: string; onChange: (id: string) => void }) {
  return (
    <div className={styles.grid} role="radiogroup" aria-label="Scenario">
      {SCENARIOS.map((s) => (
        <ChoiceCard key={s.id} name="scenario" value={s.id} checked={value === s.id} onSelect={onChange} title={s.title}>
          {s.blurb}
        </ChoiceCard>
      ))}
    </div>
  )
}
