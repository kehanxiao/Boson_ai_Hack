import { ChoiceCard } from './ChoiceCard'
import styles from './Picker.module.css'

const MODES = [
  { id: 'avatar', title: 'Face and voice', blurb: 'A talking avatar (Higgs Avatar). Uses one of the shared avatar slots.' },
  { id: 'voice', title: 'Voice only', blurb: 'No face. You hear the examiner about 1.4 s sooner, and no avatar slot is needed.' },
] as const

/** Whether the examiner appears as an avatar (SessionConfig.avatar). */
export function AvatarPicker({ avatar, onChange }: { avatar: boolean; onChange: (avatar: boolean) => void }) {
  return (
    <div className={styles.field}>
      <span id="avatar-mode-label">How the examiner appears</span>
      <div className={styles.grid} role="radiogroup" aria-labelledby="avatar-mode-label">
        {MODES.map((m) => (
          <ChoiceCard
            key={m.id}
            name="avatar"
            value={m.id}
            checked={(m.id === 'avatar') === avatar}
            onSelect={(v) => onChange(v === 'avatar')}
            title={m.title}
          >
            {m.blurb}
          </ChoiceCard>
        ))}
      </div>
    </div>
  )
}
