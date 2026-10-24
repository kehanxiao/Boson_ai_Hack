import { Session } from './pages/Session'

// Tiny path router: /session/:id, /scorecard/:id, / (setup). Setup and Scorecard pages come in Stage 3.
export default function App() {
  const [, page, id] = window.location.pathname.split('/')
  const params = new URLSearchParams(window.location.search)

  if (page === 'session' && id) {
    return (
      <Session
        sessionId={decodeURIComponent(id)}
        fake={params.get('fake') === '1'}
        speed={Number(params.get('speed')) || 1}
        autostart={params.get('autostart') === '1'}
      />
    )
  }

  return (
    <main style={{ padding: 32, maxWidth: 560, lineHeight: 1.6 }}>
      <h1>Viva</h1>
      <p>Setup and Scorecard pages are coming in Stage 3. For now:</p>
      <ul>
        <li>
          <a href="/session/demo?fake=1">Demo session, replayed from the sample log</a> (
          <a href="/session/demo?fake=1&amp;speed=4">×4</a>)
        </li>
        <li>
          <a href="/session/demo">Demo session, live agent</a>
        </li>
      </ul>
    </main>
  )
}
