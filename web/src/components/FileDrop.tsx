import { useRef, useState } from 'react'
import styles from './FileDrop.module.css'

interface Props {
  label: string
  hint: string
  accept: string // e.g. ".pdf" or ".pdf,.txt,.md"
  file: File | null
  onFile: (file: File | null) => void
}

const sizeLabel = (bytes: number) =>
  bytes < 1024 * 1024 ? `${Math.max(1, Math.round(bytes / 1024))} KB` : `${(bytes / 1024 / 1024).toFixed(1)} MB`

const matches = (file: File, accept: string) =>
  accept.split(',').some((ext) => file.name.toLowerCase().endsWith(ext.trim().toLowerCase()))

/** Click or drag a file in. Rejects other file types with a visible message. */
export function FileDrop({ label, hint, accept, file, onFile }: Props) {
  const input = useRef<HTMLInputElement>(null)
  const [over, setOver] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const take = (f: File | undefined) => {
    if (!f) return
    if (!matches(f, accept)) {
      setError(`${f.name} isn't a ${accept} file`)
      return
    }
    setError(null)
    onFile(f)
  }

  return (
    <div
      className={`${styles.drop} ${over ? styles.over : ''} ${file ? styles.has : ''}`}
      onDragOver={(e) => {
        e.preventDefault()
        setOver(true)
      }}
      onDragLeave={() => setOver(false)}
      onDrop={(e) => {
        e.preventDefault()
        setOver(false)
        take(e.dataTransfer.files[0])
      }}
    >
      <input
        ref={input}
        type="file"
        accept={accept}
        aria-label={label}
        onChange={(e) => take(e.target.files?.[0])}
      />
      {file ? (
        <div className={styles.row}>
          <span className={styles.name}>{file.name}</span>
          <span className={styles.size}>{sizeLabel(file.size)}</span>
          <button
            type="button"
            onClick={() => {
              onFile(null)
              if (input.current) input.current.value = ''
            }}
          >
            Remove
          </button>
        </div>
      ) : (
        <button type="button" className={styles.pick} onClick={() => input.current?.click()}>
          <strong>{label}</strong>
          <span>{hint}</span>
        </button>
      )}
      {error && <p className={styles.error}>{error}</p>}
    </div>
  )
}
