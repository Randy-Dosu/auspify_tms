/**
 * Exam page behaviour added while debugging the site:
 *  - the countdown is derived from the server's remaining_seconds (an absolute
 *    deadline), so a slow interval cannot drift it;
 *  - leaving the page mid-attempt warns the student (beforeunload);
 *  - coming back to the tab re-reads the attempt from the server.
 */

import React from 'react'
import { describe, expect, it, vi } from 'vitest'
import { render, screen, waitFor } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import App from '../App'
import { AuthProvider } from '../auth/AuthContext'

const STUDENT = { id: 3, full_name: 'Kofi Boateng', email: 's@t.test', role: 'student', created_at: '2026-11-06T19:00:00+00:00' }
const TOKEN = 'token.value.here'

function jsonResponse(data, status = 200) {
  return { ok: status < 400, status, text: async () => JSON.stringify(data) }
}

function mockRoutes(handlers) {
  const calls = []
  global.fetch = vi.fn(async (url, options = {}) => {
    const path = String(url).replace(/^\/api/, '')
    const method = (options.method || 'GET').toUpperCase()
    calls.push({ method, path })
    for (const handler of handlers) {
      if (handler.method === method && new RegExp(handler.pattern).test(path)) {
        return jsonResponse(handler.data(), handler.status || 200)
      }
    }
    return jsonResponse({ error: { code: 404, message: `no route ${method} ${path}` } }, 404)
  })
  return calls
}

function attemptPayload(remainingSeconds) {
  return {
    attempt: { id: 7, status: 'in_progress', started_at: '2026-11-06T19:00:00+00:00' },
    exam: { id: 1, title: 'Algebra Basics', duration_minutes: 30, total_marks: 2, pass_marks: 1 },
    questions: [
      {
        id: 11,
        question_text: 'What is 2 + 2?',
        question_type: 'single_choice',
        marks: 2,
        options: [
          { id: 101, option_text: '3' },
          { id: 102, option_text: '4' },
        ],
      },
    ],
    answers: {},
    time: { remaining_seconds: remainingSeconds, expired: false },
  }
}

function renderAttempt(remainingSeconds = 125) {
  localStorage.setItem('auspify.access_token', TOKEN)
  const payload = attemptPayload(remainingSeconds)
  const calls = mockRoutes([
    { method: 'GET', pattern: '^/auth/me$', data: () => ({ user: STUDENT }) },
    { method: 'GET', pattern: '^/attempts/7$', data: () => payload },
  ])
  render(
    <MemoryRouter initialEntries={['/student/attempts/7']}>
      <AuthProvider>
        <App />
      </AuthProvider>
    </MemoryRouter>,
  )
  return calls
}

describe('Exam countdown', () => {
  it('renders the server’s remaining time as mm:ss', async () => {
    renderAttempt(125)
    expect(await screen.findByText('What is 2 + 2?')).toBeInTheDocument()
    expect(screen.getByText('02:05')).toBeInTheDocument()
  })
})

describe('Leaving the page mid-attempt', () => {
  it('warns before the tab closes or reloads', async () => {
    renderAttempt(125)
    await screen.findByText('What is 2 + 2?')

    const event = new Event('beforeunload', { cancelable: true })
    window.dispatchEvent(event)
    expect(event.defaultPrevented).toBe(true)
  })

  it('does not warn on ordinary pages', async () => {
    localStorage.setItem('auspify.access_token', TOKEN)
    mockRoutes([
      { method: 'GET', pattern: '^/auth/me$', data: () => ({ user: STUDENT }) },
      { method: 'GET', pattern: '^/exams$', data: () => ({ exams: [] }) },
    ])
    render(
      <MemoryRouter initialEntries={['/student']}>
        <AuthProvider>
          <App />
        </AuthProvider>
      </MemoryRouter>,
    )
    await screen.findByRole('heading', { name: 'My exams' })

    const event = new Event('beforeunload', { cancelable: true })
    window.dispatchEvent(event)
    expect(event.defaultPrevented).toBe(false)
  })
})

describe('Coming back to the tab', () => {
  it('re-reads the attempt from the server', async () => {
    const calls = renderAttempt(125)
    await screen.findByText('What is 2 + 2?')
    const before = calls.filter((call) => call.method === 'GET' && call.path === '/attempts/7').length

    document.dispatchEvent(new Event('visibilitychange'))
    await waitFor(() => {
      const after = calls.filter((call) => call.method === 'GET' && call.path === '/attempts/7').length
      expect(after).toBeGreaterThan(before)
    })
  })
})
