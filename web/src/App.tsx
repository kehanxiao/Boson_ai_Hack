import { Session } from './pages/Session'
import { Setup } from './pages/Setup'

// Tiny path router: / (setup), /session/:id, /scorecard/:id (Scorecard page still to come).
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

  return <Setup />
}
