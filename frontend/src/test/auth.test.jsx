/**
 * Step 1 UI tests (jsdom, no browser needed).
 *
 * They exercise the real components with a mocked network layer: protected
 * routes, the login -> dashboard flow, error display, registration validation
 * and logout.
 */

import React from 'react'
import { describe, expect, it, vi } from 'vitest'
import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter } from 'react-router-dom'
import App from '../App'
import { AuthProvider } from '../auth/AuthContext'

const TEACHER = {
  id: 2,
  full_name: 'Grace Mensah',
  email: 'teacher@auspify.test',
  role: 'teacher',
  is_active: 1,
  created_at: '2026-11-06T19:00:00+00:00',
}

const STUDENT = { ...TEACHER, id: 3, full_name: 'Kofi Boateng', email: 'kofi@auspify.test', role: 'student' }
const TOKEN = 'header.payload.signature'

function jsonResponse(data, status = 200) {
  return { ok: status < 400, status, text: async () => JSON.stringify(data) }
}

/** Minimal fetch router: {"METHOD /path": handler} */
function mockApi(routes) {
  const calls = []
  global.fetch = vi.fn(async (url, options = {}) => {
    const path = String(url).replace(/^\/api/, '')
    const method = (options.method || 'GET').toUpperCase()
    const key = `${method} ${path}`
    calls.push({ key, headers: options.headers, body: options.body })
    const handler = routes[key]
    if (!handler) return jsonResponse({ error: { code: 404, message: `no route ${key}` } }, 404)
    return handler(options.body ? JSON.parse(options.body) : null)
  })
  return calls
}

function renderApp(initialPath = '/login') {
  return render(
    <MemoryRouter initialEntries={[initialPath]}>
      <AuthProvider>
        <App />
      </AuthProvider>
    </MemoryRouter>,
  )
}

describe('Step 1 — authentication UI', () => {
  it('redirects an anonymous visitor from /dashboard to the login page', async () => {
    mockApi({})
    renderApp('/dashboard')

    expect(await screen.findByRole('heading', { name: /sign in/i })).toBeInTheDocument()
    expect(screen.queryByRole('heading', { name: /hello/i })).not.toBeInTheDocument()
  })

  it('logs in, renders the role-based dashboard and sends the bearer token', async () => {
    const calls = mockApi({
      'POST /auth/login': () =>
        jsonResponse({ access_token: TOKEN, token_type: 'Bearer', expires_in_minutes: 30, user: TEACHER }),
      'GET /auth/me': () => jsonResponse({ user: TEACHER }),
    })

    renderApp('/login')

    await userEvent.type(screen.getByLabelText(/email/i), 'teacher@auspify.test')
    await userEvent.type(screen.getByLabelText(/password/i), 'TeacherPass1')
    await userEvent.click(screen.getByRole('button', { name: /sign in/i }))

    expect(await screen.findByRole('heading', { name: /hello, grace/i })).toBeInTheDocument()
    expect(screen.getByText('teacher@auspify.test')).toBeInTheDocument()
    expect(localStorage.getItem('auspify.access_token')).toBe(TOKEN)

    const loginCall = calls.find((call) => call.key === 'POST /auth/login')
    expect(loginCall.body).toBe(JSON.stringify({ email: 'teacher@auspify.test', password: 'TeacherPass1' }))
    // The password is only ever sent to /auth/login, never stored in the body of
    // other requests, and the token travels in the Authorization header.
    expect(calls.filter((call) => call.key !== 'POST /auth/login').every((call) => call.headers.Authorization === `Bearer ${TOKEN}`)).toBe(true)
  })

  it('shows the API error message for wrong credentials and stays on the form', async () => {
    mockApi({
      'POST /auth/login': () => jsonResponse({ error: { code: 401, message: 'Invalid email or password.' } }, 401),
    })

    renderApp('/login')
    await userEvent.type(screen.getByLabelText(/email/i), 'teacher@auspify.test')
    await userEvent.type(screen.getByLabelText(/password/i), 'wrongpass1')
    await userEvent.click(screen.getByRole('button', { name: /sign in/i }))

    expect(await screen.findByRole('alert')).toHaveTextContent('Invalid email or password.')
    expect(screen.getByRole('heading', { name: /sign in/i })).toBeInTheDocument()
    expect(localStorage.getItem('auspify.access_token')).toBeNull()
  })

  it('keeps the user signed in on reload by re-validating the stored token', async () => {
    localStorage.setItem('auspify.access_token', TOKEN)
    mockApi({ 'GET /auth/me': () => jsonResponse({ user: STUDENT }) })

    renderApp('/dashboard')

    expect(await screen.findByRole('heading', { name: /hello, kofi/i })).toBeInTheDocument()
  })

  it('clears a rejected token and falls back to the login page', async () => {
    localStorage.setItem('auspify.access_token', 'revoked.token.value')
    mockApi({ 'GET /auth/me': () => jsonResponse({ error: { code: 401, message: 'Token has been revoked.' } }, 401) })

    renderApp('/dashboard')

    expect(await screen.findByRole('heading', { name: /sign in/i })).toBeInTheDocument()
    expect(localStorage.getItem('auspify.access_token')).toBeNull()
  })

  it('logs out: revokes server-side and returns to the login page', async () => {
    localStorage.setItem('auspify.access_token', TOKEN)
    const calls = mockApi({
      'GET /auth/me': () => jsonResponse({ user: STUDENT }),
      'POST /auth/logout': () => jsonResponse({ message: 'Logged out.' }),
    })

    renderApp('/dashboard')
    await userEvent.click(await screen.findByRole('button', { name: /log out/i }))

    await waitFor(() => expect(screen.getByRole('heading', { name: /sign in/i })).toBeInTheDocument())
    expect(calls.some((call) => call.key === 'POST /auth/logout')).toBe(true)
    expect(localStorage.getItem('auspify.access_token')).toBeNull()
  })

  it('blocks registration with a weak password before calling the API', async () => {
    const calls = mockApi({})
    renderApp('/register')

    await userEvent.type(screen.getByLabelText(/full name/i), 'New Student')
    await userEvent.type(screen.getByLabelText(/^email/i), 'new@auspify.test')
    await userEvent.type(screen.getByLabelText(/^password/i), 'onlyletters')
    await userEvent.type(screen.getByLabelText(/confirm password/i), 'onlyletters')
    await userEvent.click(screen.getByRole('button', { name: /create account/i }))

    expect(await screen.findByText(/use letters and numbers/i)).toBeInTheDocument()
    expect(calls.some((call) => call.key === 'POST /auth/register')).toBe(false)
  })

  it('registers a student and lands on the student dashboard', async () => {
    mockApi({
      'POST /auth/register': () => jsonResponse({ access_token: TOKEN, token_type: 'Bearer', expires_in_minutes: 30, user: STUDENT }, 201),
      'GET /auth/me': () => jsonResponse({ user: STUDENT }),
    })

    renderApp('/register')
    await userEvent.type(screen.getByLabelText(/full name/i), 'Kofi Boateng')
    await userEvent.type(screen.getByLabelText(/^email/i), 'kofi@auspify.test')
    await userEvent.type(screen.getByLabelText(/^password/i), 'StudentPass1')
    await userEvent.type(screen.getByLabelText(/confirm password/i), 'StudentPass1')
    await userEvent.click(screen.getByRole('button', { name: /create account/i }))

    expect(await screen.findByRole('heading', { name: /hello, kofi/i })).toBeInTheDocument()
  })
})
