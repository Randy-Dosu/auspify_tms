import { useCallback, useEffect, useState } from 'react'
import { getHealth } from './api/client'

/**
 * Step 0 landing page.
 *
 * Its only job right now is to prove the full stack is wired up:
 * React (Vite) -> /api proxy -> Flask -> JSON back to the browser.
 * Login/register pages arrive in Step 1.
 */
export default function App() {
  const [state, setState] = useState({ status: 'loading', data: null, error: null })

  const checkHealth = useCallback(async () => {
    setState({ status: 'loading', data: null, error: null })
    try {
      const data = await getHealth()
      setState({ status: 'ok', data, error: null })
    } catch (err) {
      setState({ status: 'error', data: null, error: err.message })
    }
  }, [])

  // Check the connection once on mount. State is only updated after the
  // request settles, and never after the component unmounts.
  useEffect(() => {
    let cancelled = false
    ;(async () => {
      try {
        const data = await getHealth()
        if (!cancelled) setState({ status: 'ok', data, error: null })
      } catch (err) {
        if (!cancelled) setState({ status: 'error', data: null, error: err.message })
      }
    })()
    return () => {
      cancelled = true
    }
  }, [])

  const { status, data, error } = state

  return (
    <main className="page">
      <header style={{ marginBottom: '2rem' }}>
        <p className="small muted" style={{ margin: 0, letterSpacing: '0.08em', textTransform: 'uppercase' }}>
          Auspify TMS
        </p>
        <h1>Online Examination System</h1>
        <p className="muted" style={{ marginTop: 0 }}>
          Step 0 &mdash; project setup. Secure exams, timed tests, automatic results and
          performance reports.
        </p>
      </header>

      <section className="card">
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', gap: '1rem', flexWrap: 'wrap' }}>
          <h2 style={{ margin: 0 }}>Backend connection</h2>
          <StatusPill status={status} />
        </div>

        <p className="muted small" style={{ marginBottom: 0 }}>
          <code>GET /api/health</code> &rarr; proxied by Vite to the Flask API on port 5000.
        </p>

        {status === 'loading' && <p className="muted small">Contacting the API&hellip;</p>}

        {status === 'ok' && data && (
          <dl className="data-list">
            <dt>Status</dt>
            <dd>{data.status}</dd>
            <dt>Service</dt>
            <dd>{data.service}</dd>
            <dt>Version</dt>
            <dd>{data.version}</dd>
            <dt>Environment</dt>
            <dd>{data.environment}</dd>
            <dt>Server time (UTC)</dt>
            <dd>{data.timestamp}</dd>
          </dl>
        )}

        {status === 'error' && (
          <div className="alert error" role="alert">
            <strong>Could not reach the API.</strong> {error}
          </div>
        )}

        <div style={{ marginTop: '1.25rem' }}>
          <button className="btn" onClick={checkHealth} disabled={status === 'loading'}>
            {status === 'loading' ? 'Checking…' : 'Re-check connection'}
          </button>
        </div>
      </section>

      <section className="card">
        <h2>What Step 0 sets up</h2>
        <ul className="checklist">
          <li><code>backend/</code> &mdash; Flask app factory, config from environment, security headers, JSON error handling.</li>
          <li><code>backend/.env</code> &mdash; real secrets (git-ignored) with a committed <code>.env.example</code> template.</li>
          <li><code>frontend/</code> &mdash; Vite + React app calling the API through the dev proxy.</li>
          <li>No secret keys, database paths or credentials are hardcoded anywhere in the code.</li>
          <li>API responses expose no configuration &mdash; only service name, version, environment and time.</li>
        </ul>
        <p className="small muted" style={{ marginBottom: 0, marginTop: '1rem' }}>
          Next up: Step 1 &mdash; user authentication.
        </p>
      </section>

      <footer className="small muted">
        Run the backend on <code>:5000</code> and the frontend on <code>:5173</code>.
      </footer>
    </main>
  )
}

/** Small coloured pill reflecting the connection state. */
function StatusPill({ status }) {
  if (status === 'ok') return <span className="pill ok">● API reachable</span>
  if (status === 'error') return <span className="pill bad">● API unreachable</span>
  return <span className="pill pending">● Checking</span>
}
