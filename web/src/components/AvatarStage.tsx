import { useEffect, useRef } from 'react'
import type { Character } from '../lib/contract'
import type { AvatarTracks } from '../lib/link'
import styles from './AvatarStage.module.css'

interface Props {
  tracks: AvatarTracks
  character: Character
  speaking: boolean
}

/** Video + audio of participant `boson-avatar`; a placeholder until the avatar joins (or in voice-only / fake mode). */
export function AvatarStage({ tracks, character, speaking }: Props) {
  const videoRef = useRef<HTMLVideoElement>(null)
  const audioRef = useRef<HTMLAudioElement>(null)

  useEffect(() => {
    const el = videoRef.current
    if (!el || !tracks.video) return
    tracks.video.attach(el)
    return () => void tracks.video?.detach(el)
  }, [tracks.video])

  useEffect(() => {
    const el = audioRef.current
    if (!el || !tracks.audio) return
    tracks.audio.attach(el)
    return () => void tracks.audio?.detach(el)
  }, [tracks.audio])

  const initials = character.name
    .split(',')[0]
    .replace(/^Dr\.\s*/, '')
    .split(/\s+/)
    .map((w) => w[0])
    .join('')
    .slice(0, 2)

  return (
    <figure className={`${styles.stage} ${speaking ? styles.speaking : ''}`}>
      {tracks.video ? (
        <video ref={videoRef} autoPlay playsInline muted />
      ) : (
        <div className={styles.placeholder} aria-hidden>
          {initials}
        </div>
      )}
      <audio ref={audioRef} autoPlay />
      <figcaption>{character.name}</figcaption>
    </figure>
  )
}
