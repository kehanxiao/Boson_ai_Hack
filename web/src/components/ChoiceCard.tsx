import type { ReactNode } from 'react'
import styles from './ChoiceCard.module.css'

interface Props {
  name: string
  value: string
  checked: boolean
  onSelect: (value: string) => void
  title: string
  children?: ReactNode
}

/** A radio button styled as a selectable card. Keyboard and screen-reader friendly. */
export function ChoiceCard({ name, value, checked, onSelect, title, children }: Props) {
  return (
    <label className={`${styles.card} ${checked ? styles.checked : ''}`}>
      <input type="radio" name={name} value={value} checked={checked} onChange={() => onSelect(value)} />
      <span className={styles.title}>{title}</span>
      {children && <span className={styles.body}>{children}</span>}
    </label>
  )
}
