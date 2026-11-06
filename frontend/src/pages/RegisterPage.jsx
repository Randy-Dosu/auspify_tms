import { useState } from 'react'
import { Link, Navigate, useNavigate } from 'react-router-dom'
import { useAuth } from '../auth/context'
import { Alert, Field } from '../components/ui'

/**
 * Student self-registration.
 * The role is never sent from the browser: the API always creates students.
 */
export default function RegisterPage() {
  const { user, register } = useAuth()
  const navigate = useNavigate()
  const [form, setForm] = useState({ fullName: '', email: '', password: '', confirm: '' })
  const [errors, setErrors] = useState({})
  const [error, setError] = useState('')
  const [submitting, setSubmitting] = useState(false)

  if (user) return <Navigate to="/dashboard" replace />

  const onChange = (event) =>
    setForm((current) => ({ ...current, [event.target.name]: event.target.value }))

  /** Mirror of the server policy, for instant feedback only. */
  function validate() {
    const next = {}
    if (form.fullName.trim().length < 2) next.fullName = 'Enter your full name.'
    if (!/^[^@\s]+@[^@\s]+\.[A-Za-z]{2,}$/.test(form.email.trim()))
      next.email = 'Enter a valid email address.'
    if (form.password.length < 8) next.password = 'At least 8 characters.'
    else if (!/[A-Za-z]/.test(form.password) || !/[0-9]/.test(form.password))
      next.password = 'Use letters and numbers.'
    if (form.confirm !== form.password) next.confirm = 'Passwords do not match.'
    setErrors(next)
    return Object.keys(next).length === 0
  }

  async function handleSubmit(event) {
    event.preventDefault()
    setError('')
    if (!validate()) return
    setSubmitting(true)
    try {
      await register(form.fullName.trim(), form.email.trim(), form.password)
      navigate('/dashboard', { replace: true })
    } catch (err) {
      setError(err.message || 'Unable to create the account.')
    } finally {
      setSubmitting(false)
    }
  }

  return (
    <main className="auth-page">
      <section className="card auth-card">
        <h1>Create a student account</h1>
        <p className="muted small">
          Teacher and admin accounts are created by an administrator.
        </p>

        <form onSubmit={handleSubmit} noValidate>
          <Field
            id="fullName"
            name="fullName"
            label="Full name"
            value={form.fullName}
            onChange={onChange}
            error={errors.fullName}
            autoComplete="name"
            required
          />
          <Field
            id="email"
            name="email"
            label="Email"
            type="email"
            value={form.email}
            onChange={onChange}
            error={errors.email}
            autoComplete="email"
            required
          />
          <Field
            id="password"
            name="password"
            label="Password"
            type="password"
            value={form.password}
            onChange={onChange}
            error={errors.password}
            hint="At least 8 characters, with letters and numbers."
            autoComplete="new-password"
            required
          />
          <Field
            id="confirm"
            name="confirm"
            label="Confirm password"
            type="password"
            value={form.confirm}
            onChange={onChange}
            error={errors.confirm}
            autoComplete="new-password"
            required
          />

          <Alert>{error}</Alert>

          <button type="submit" className="btn block" disabled={submitting}>
            {submitting ? 'Creating account…' : 'Create account'}
          </button>
        </form>

        <p className="small muted auth-footer">
          Already registered? <Link to="/login">Sign in</Link>
        </p>
      </section>
    </main>
  )
}
