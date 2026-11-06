/** Step 3 UI tests: result page score, badge and question review. */

import React from 'react'
import { describe, expect, it } from 'vitest'
import { render, screen } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import App from '../App'
import { AuthProvider } from '../auth/AuthContext'

const STUDENT = { id: 3, full_name: 'Kofi Boateng', email: 's@t.test', role: 'student', is_active: 1, created_at: '2026-11-06T19:00:00+00:00' }
const TOKEN = 'token.value'

function jsonResponse(data, status = 200) {
  return { ok: status < 400, status, text: async () => JSON.stringify(data) }
}

function mock(handlers) {
  global.fetch = async (url, options = {}) => {
    const path = String(url).replace(/^\/api/, '')
    const method = (options.method || 'GET').toUpperCase()
    for (const handler of handlers) {
      if (handler.method === method && new RegExp(handler.pattern).test(path)) {
        return jsonResponse(handler.data(), handler.status || 200)
      }
    }
    return jsonResponse({ error: { code: 404, message: `no route ${method} ${path}` } }, 404)
  }
}

function renderPage(result) {
  localStorage.setItem('auspify.access_token', TOKEN)
  mock([
    { method: 'GET', pattern: '^/auth/me$', data: () => ({ user: STUDENT }) },
    { method: 'GET', pattern: '^/attempts/5/result$', data: () => result },
  ])
  return render(
    <MemoryRouter initialEntries={['/student/results/5']}>
      <AuthProvider>
        <App />
      </AuthProvider>
    </MemoryRouter>,
  )
}

const BASE = {
  attempt: { id: 5, status: 'submitted', submitted_at: '2026-11-06T19:10:00+00:00' },
  exam: { id: 1, title: 'Algebra Basics', subject: 'Mathematics', total_marks: 6, pass_marks: 3, end_time: '2026-11-06T18:00:00+00:00' },
}

describe('Step 3 — result page', () => {
  it('shows the score, percentage, outcome and per-question review', async () => {
    renderPage({
      ...BASE,
      result: { score: 4.5, percentage: 75.0, passed: true, status: 'submitted' },
      review_available: true,
      questions: [
        {
          id: 11,
          question_text: 'What is 2 + 2?',
          question_type: 'single_choice',
          marks: 2,
          negative_marks: 0,
          options: [
            { id: 101, option_text: '3', is_correct: false },
            { id: 102, option_text: '4', is_correct: true },
          ],
          selected_option_ids: [102],
          is_correct: true,
          marks_awarded: 2,
        },
        {
          id: 12,
          question_text: 'Which are prime?',
          question_type: 'multiple_choice',
          marks: 3,
          negative_marks: 1,
          options: [
            { id: 201, option_text: '2', is_correct: true },
            { id: 202, option_text: '4', is_correct: false },
          ],
          selected_option_ids: [202],
          is_correct: false,
          marks_awarded: -1,
        },
      ],
    })

    expect(await screen.findByText('4.5')).toBeInTheDocument()
    expect(screen.getByText('75%')).toBeInTheDocument()
    expect(screen.getByText('passed')).toBeInTheDocument()
    expect(screen.getByText('What is 2 + 2?')).toBeInTheDocument()
    expect(screen.getByText('correct', { selector: '.badge' })).toBeInTheDocument()
    expect(screen.getByText('wrong', { selector: '.badge' })).toBeInTheDocument()
    expect(screen.getByText('-1 / 3')).toBeInTheDocument()
    expect(screen.getAllByText('correct answer').length).toBeGreaterThan(0)
    expect(screen.getByText('your answer')).toBeInTheDocument()
  })

  it('hides the review while the exam window is open', async () => {
    renderPage({
      ...BASE,
      result: { score: 0, percentage: 0, passed: false, status: 'expired' },
      review_available: false,
      review_reason: 'Question review opens when the exam window closes.',
    })

    expect(await screen.findByText('failed')).toBeInTheDocument()
    expect(screen.getByText(/opens when the exam window closes/i)).toBeInTheDocument()
    expect(screen.queryByText('What is 2 + 2?')).not.toBeInTheDocument()
  })
})
