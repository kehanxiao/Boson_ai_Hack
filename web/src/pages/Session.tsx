import { useEffect, useState } from 'react'
import { AvatarStage } from '../components/AvatarStage'
import { ExaminerState } from '../components/ExaminerState'
import { FactCheck } from '../components/FactCheck'
import { LatencyHud } from '../components/LatencyHud'
import { ReminderBanner } from '../components/ReminderBanner'
import { SessionControls } from '../components/SessionControls'
import { SlideViewer } from '../components/SlideViewer'
import { Timer } from '../components/Timer'
import { startAgent } from '../lib/api'
import { useClock } from '../lib/useClock'
import { useSessionConfig } from '../lib/useSessionConfig'
import { useVivaSession } from '../lib/useVivaSession'
import styles from './Session.module.css'

interface Props {
  sessionId: string
  /** Replay demo/sample-log.jsonl instead of connecting to the agent (?fake=1). */
  fake: boolean
  speed: number
  autostart?: boolean
}

export function Session({ sessionId, fake, speed, autostart = false }: Props) {
  const { config, error: configError } = useSessionConfig(sessionId)
  const [slide, setSlide] = useState(1)
  const session = useVivaSession({ sessionId, fake, speed, onReplaySlide: setSlide, currentSlide: () => slide })
  const { view } = session
  const now = useClock(session.link, view.ended)

  // Live: get the agent (and its avatar) starting while the presenter reads the page.
  useEffect(() => {
    if (!fake) void startAgent(sessionId)
  }, [fake, sessionId])

  // Fake replay only (?fake=1&autostart=1): live mode needs a real click to start audio.
  const { start, status } = session
  useEffect(() => {
    if (fake && autostart && config && status === 'idle') void start()
  }, [fake, autostart, config, status, start])

  if (configError) return <p className={styles.message}>Could not load session “{sessionId}”: {configError}</p>
  if (!config) return <p className={styles.message}>Loading session…</p>

  const changeSlide = (index: number) => {
    setSlide(index)
    session.send({ type: 'slide', index })
  }
  const inQa = view.qaStartedAt !== null
  const speaking = view.examiner === 'interjecting' || view.examiner === 'holding_floor'

  return (
    <div className={styles.page}>
      <header className={styles.header}>
        <div className={styles.brand}>
          Viva{fake && <span className={styles.fake}>replay ×{speed}</span>}
        </div>
        <ExaminerState state={view.examiner} />
        <div className={styles.right}>
          <SessionControls
            examiner={view.examiner}
            status={session.status}
            hasQa={config.qa_s > 0}
            onStart={session.start}
            onPhase={(phase) => session.send({ type: 'phase', phase })}
          />
          <Timer
            label={inQa ? 'Q&A' : 'Presentation'}
            elapsedS={inQa ? now - (view.qaStartedAt ?? 0) : now}
            limitS={inQa ? config.qa_s : config.time_limit_s}
          />
        </div>
      </header>

      {session.error && <p className={styles.error}>{session.error}</p>}

      <main className={styles.main}>
        <div className={styles.slideArea}>
          <ReminderBanner reminder={view.reminder} now={now} />
          <SlideViewer slides={config.slides} index={slide} onChange={changeSlide} />
        </div>
        <aside className={styles.aside}>
          <AvatarStage tracks={session.avatar} character={config.character} speaking={speaking} voiceOnly={config.avatar === false} />
          <FactCheck factcheck={view.factcheck} now={now} />
          {view.ended && (
            <a className={styles.scorecard} href={`/scorecard/${encodeURIComponent(sessionId)}`}>
              View scorecard →
            </a>
          )}
        </aside>
      </main>

      <LatencyHud latency={view.latency} />
    </div>
  )
}
