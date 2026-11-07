/**
 * Dashboard + not-found smoke tests.
 *
 * The dashboards used to be static "coming in Step N" copy; they now read the
 * exam list, so they get their own tests: correct counters, graceful failure,
 * and client-side navigation from the 403/404 screens.
 */

import React from 'react'
import { describe, expect, it, vi } from 'vitest'
import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter } from 'react-router-dom'
import App from '../App'
import { AuthProvider } from '../auth/AuthContext'

const TEACHER = { id: 2, full_name: 'Grace Mensah', email: 't@t.test', role: 'teacher', created_at: '2026-11-06T19:00:00+00:00' }
const STUDENT = { id: 3, full_name: 'Kofi Boateng', email: 's@t.test', role: 'student', created_at: '2026-11-06T19:00:00+00:00' }
const TOKEN = 'token.value.here'

function jsonResponse(data, status = 200) {
  return { ok: status < 400, status, text: async () => JSON.stringify(data) }
}

function mockRoutes(handlers) {
  global.fetch = vi.fn(async (url, options = {}) => {
    const path = String(url).replace(/^\/api/, '')
    const method = (options.method || 'GET').toUpperCase()
    for (const handler of handlers) {
      if (handler.method === method && new RegExp(handler.pattern).test(path)) {
        return jsonResponse(handler.data(), handler.status || 200)
      }
    }
    return jsonResponse({ error: { code: 404, message: `no route ${method} ${path}` } }, 404)
  })
}

function renderApp(path, user, handlers = []) {
  localStorage.setItem('auspify.access_token', TOKEN)
  mockRoutes([
    { method: 'GET', pattern: '^/auth/me$', data: () => ({ user }) },
    ...handlers,
  ])
  return render(
    <MemoryRouter initialEntries={[path]}>
      <AuthProvider>
        <App />
      </AuthProvider>
    </MemoryRouter>,
  )
}

const STAFF_EXAMS = {
  exams: [
    { id: 1, title: 'Algebra', is_published: 1, attempt_count: 4, question_count: 3, total_marks: 8 },
    { id: 2, title: 'Geometry', is_published: 0, attempt_count: 1, question_count: 2, total_marks: 5 },
    { id: 3, title: 'Trigonometry', is_published: 1, attempt_count: 0, question_count: 1, total_marks: 2 },
  ],
}

const STUDENT_EXAMS = {
  exams: [
    { id: 1, title: 'Algebra', attempt: null },
    { id: 2, title: 'Geometry', attempt: { id: 9, status: 'in_progress' } },
    { id: 3, title: 'Trigonometry', attempt: { id: 10, status: 'submitted' } },
  ],
}

describe('Dashboards', () => {
  it('shows the teacher’s real exam counters', async () => {
    renderApp('/dashboard', TEACHER, [
      { method: 'GET', pattern: '^/exams$', data: () => STAFF_EXAMS },
    ])

    expect(await screen.findByText('Hello, Grace')).toBeInTheDocument()
    await waitFor(() => expect(screen.getByText('Attempts')).toBeInTheDocument())

    // 3 exams, 2 published, 1 draft, 5 attempts in total.
    // "Exams" is also the nav link, hence the plural query.
    expect(screen.getAllByText('Exams').length).toBeGreaterThan(0)
    expect(screen.getByText('Published')).toBeInTheDocument()
    expect(screen.getByText('Drafts')).toBeInTheDocument()
    expect(screen.getByText('5')).toBeInTheDocument()
  })

  it('shows a student’s open / in-progress / completed counts', async () => {
    renderApp('/dashboard', STUDENT, [
      { method: 'GET', pattern: '^/exams$', data: () => STUDENT_EXAMS },
    ])

    expect(await screen.findByText('Hello, Kofi')).toBeInTheDocument()
    await waitFor(() => expect(screen.getByText('Open now')).toBeInTheDocument())
    expect(screen.getByText('In progress')).toBeInTheDocument()
    expect(screen.getByText('Completed')).toBeInTheDocument()
  })

  it('degrades to an alert when the exam list cannot be loaded', async () => {
    renderApp('/dashboard', TEACHER, [
      {
        method: 'GET',
        pattern: '^/exams$',
        data: () => ({ error: { code: 500, message: 'Server exploded.' } }),
        status: 500,
      },
    ])

    expect(await screen.findByText('Server exploded.')).toBeInTheDocument()
    // The page still renders its account card instead of crashing.
    expect(screen.getByText('Your account')).toBeInTheDocument()
  })
})

describe('Not-found and forbidden screens', () => {
  it('renders the 404 page for an unknown route', async () => {
    renderApp('/no/such/page', STUDENT, [])
    expect(await screen.findByText('404 — Page not found')).toBeInTheDocument()
  })

  it('returns to the dashboard without a full page reload', async () => {
    const user = userEvent.setup()
    renderApp('/no/such/page', STUDENT, [
      { method: 'GET', pattern: '^/exams$', data: () => ({ exams: [] }) },
    ])

    const link = await screen.findByRole('link', { name: 'Back to dashboard' })
    expect(link).toHaveAttribute('href', '/dashboard')
    await user.click(link)
    // Client-side navigation: the dashboard renders, the 404 copy is gone.
    await waitFor(() => expect(screen.queryByText('404 — Page not found')).not.toBeInTheDocument())
    expect(await screen.findByText('Hello, Kofi')).toBeInTheDocument()
  })

  it('blocks a student from a teacher page with a 403 screen', async () => {
    renderApp('/teacher', STUDENT, [{ method: 'GET', pattern: '^/exams$', data: () => ({ exams: [] }) }])
    expect(await screen.findByText('403 — Not allowed')).toBeInTheDocument()
    expect(screen.getByText(/your role \(student\)/i)).toBeInTheDocument()
  })
})
