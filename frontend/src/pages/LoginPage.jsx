import { useState } from 'react'
import { Link, Navigate, useLocation, useNavigate } from 'react-router-dom'
import { useAuth } from '../auth/context'
import { Alert, Field } from '../components/ui'

/** Login form. Errors come from the API and are intentionally generic. */
export default function LoginPage() {
  const { user, login } = useAuth()
  const navigate = useNavigate()
  const location = useLocation()
  const [form, setForm] = useState({ email: '', password: '' })
  const [error, setError] = useState('')
  const [submitting, setSubmitting] = useState(false)

  if (user) return <Navigate to="/dashboard" replace />

  const onChange = (event) =>
    setForm((current) => ({ ...current, [event.target.name]: event.target.value }))

  async function handleSubmit(event) {
    event.preventDefault()
    setError('')
    setSubmitting(true)
    try {
      await login(form.email.trim(), form.password)
      navigate(location.state?.from || '/dashboard', { replace: true })
    } catch (err) {
      setError(err.message || 'Unable to sign in.')
    } finally {
      setSubmitting(false)
    }
  }

  return (
    <main className="auth-page">
      <section className="card auth-card">
        <h1>Sign in</h1>
        <p className="muted small">Online Examination System</p>

        <form onSubmit={handleSubmit} noValidate>
          <Field
            id="email"
            name="email"
            label="Email"
            type="email"
            autoComplete="email"
            value={form.email}
            onChange={onChange}
            required
          />
          <Field
            id="password"
            name="password"
            label="Password"
            type="password"
            autoComplete="current-password"
            value={form.password}
            onChange={onChange}
            required
          />

          <Alert>{error}</Alert>

          <button type="submit" className="btn block" disabled={submitting}>
            {submitting ? 'Signing in…' : 'Sign in'}
          </button>
        </form>

        <p className="small muted auth-footer">
          New student? <Link to="/register">Create an account</Link>
        </p>
      </section>
    </main>
  )
}
