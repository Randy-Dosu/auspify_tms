/** Step 4 UI tests: performance dashboard, difficulty table, leaderboard, progress. */

import React from 'react'
import { describe, expect, it } from 'vitest'
import { render, screen } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import App from '../App'
import { AuthProvider } from '../auth/AuthContext'

const TEACHER = { id: 2, full_name: 'Grace Mensah', email: 't@t.test', role: 'teacher', is_active: 1, created_at: '2026-11-06T19:00:00+00:00' }
const STUDENT = { id: 3, full_name: 'Kofi Boateng', email: 's@t.test', role: 'student', is_active: 1, created_at: '2026-11-06T19:00:00+00:00' }
const TOKEN = 'token.value'

function jsonResponse(data, status = 200) {
  return { ok: status < 400, status, text: async () => JSON.stringify(data) }
}

function mockApi(handlers) {
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

function renderApp(path, user, handlers) {
  localStorage.setItem('auspify.access_token', TOKEN)
  mockApi([{ method: 'GET', pattern: '^/auth/me$', data: () => ({ user }) }, ...handlers])
  return render(
    <MemoryRouter initialEntries={[path]}>
      <AuthProvider>
        <App />
      </AuthProvider>
    </MemoryRouter>,
  )
}

const EXAM_REPORT = {
  exam: { id: 1, title: 'Algebra Basics', subject: 'Mathematics', total_marks: 6, pass_marks: 3, duration_minutes: 30, is_published: true, end_time: null },
  summary: {
    attempt_count: 3,
    average_percentage: 36.11,
    highest_percentage: 100,
    lowest_percentage: 0,
    median_percentage: 8.33,
    average_score: 2.17,
    highest_score: 6,
    lowest_score: 0,
    passed_count: 1,
    failed_count: 2,
    pass_rate: 33.33,
  },
  distribution: [
    { band: '0-20%', count: 2 },
    { band: '21-40%', count: 0 },
    { band: '41-60%', count: 0 },
    { band: '61-80%', count: 0 },
    { band: '81-100%', count: 1 },
  ],
  questions: [
    { question_id: 11, question_text: 'What is 2 + 2?', question_type: 'single_choice', marks: 2, graded_count: 3, correct_count: 2, percent_correct: 66.67 },
    { question_id: 12, question_text: 'Which are prime?', question_type: 'multiple_choice', marks: 3, graded_count: 3, correct_count: 1, percent_correct: 33.33 },
  ],
}

const LEADERBOARD = {
  exam: { id: 1, title: 'Algebra Basics', total_marks: 6, pass_marks: 3, end_time: null },
  entries: [
    { rank: 1, student_id: 4, student_name: 'Student B', attempt_id: 20, score: 6, percentage: 100, passed: true, submitted_at: '2026-11-06T19:10:00+00:00' },
    { rank: 2, student_id: 3, student_name: 'Student A', attempt_id: 10, score: 0.5, percentage: 8.33, passed: false, submitted_at: '2026-11-06T19:05:00+00:00' },
  ],
}

describe('Step 4 — reports UI', () => {
  it('renders summary cards, difficulty table, leaderboard and CSV buttons', async () => {
    renderApp('/teacher/reports/1', TEACHER, [
      { method: 'GET', pattern: '^/reports/exam/1$', data: () => EXAM_REPORT },
      { method: 'GET', pattern: '^/reports/leaderboard/1$', data: () => LEADERBOARD },
    ])

    expect(await screen.findByRole('heading', { name: /performance/i })).toBeInTheDocument()
    expect(screen.getByText('36.11%')).toBeInTheDocument() // average card
    expect(screen.getAllByText('33.33%').length).toBeGreaterThan(0) // pass rate
    expect(screen.getAllByText('8.33%').length).toBeGreaterThan(0) // median
    expect(screen.getByRole('button', { name: /export report csv/i })).toBeInTheDocument()
    expect(screen.getByRole('button', { name: /export leaderboard csv/i })).toBeInTheDocument()

    expect(screen.getByText('What is 2 + 2?')).toBeInTheDocument()
    expect(screen.getByText('66.67%')).toBeInTheDocument()
    expect(screen.getByText('Student B')).toBeInTheDocument()
    expect(screen.getByText('passed')).toBeInTheDocument()
    expect(screen.getByText('failed')).toBeInTheDocument()
  })

  it('shows zeros (not an error) for an exam without attempts', async () => {
    renderApp('/teacher/reports/2', TEACHER, [
      {
        method: 'GET',
        pattern: '^/reports/exam/2$',
        data: () => ({
          ...EXAM_REPORT,
          summary: { ...EXAM_REPORT.summary, attempt_count: 0, average_percentage: 0, pass_rate: 0, passed_count: 0, failed_count: 0 },
          distribution: EXAM_REPORT.distribution.map((band) => ({ ...band, count: 0 })),
          questions: [],
        }),
      },
      { method: 'GET', pattern: '^/reports/leaderboard/2$', data: () => ({ ...LEADERBOARD, entries: [] }) },
    ])

    expect(await screen.findByText(/no attempts yet/i)).toBeInTheDocument()
    expect(screen.getByText(/no results yet/i)).toBeInTheDocument()
  })

  it('renders the student progress page with history and result links', async () => {
    renderApp('/student/progress', STUDENT, [
      {
        method: 'GET',
        pattern: '^/reports/student/3$',
        data: () => ({
          student: { id: 3, full_name: 'Kofi Boateng', email: 's@t.test' },
          summary: { exams_taken: 1, average_percentage: 75, best_percentage: 75, worst_percentage: 75, passed_count: 1, failed_count: 0, pass_rate: 100 },
          history: [
            {
              attempt_id: 10,
              exam_id: 1,
              exam_title: 'Algebra Basics',
              subject: 'Mathematics',
              status: 'submitted',
              score: 4.5,
              percentage: 75,
              passed: true,
              total_marks: 6,
              pass_marks: 3,
              submitted_at: '2026-11-06T19:05:00+00:00',
            },
          ],
          trend: [{ label: 'Algebra Basics', submitted_at: '2026-11-06T19:05:00+00:00', percentage: 75, score: 4.5 }],
        }),
      },
    ])

    expect(await screen.findByRole('heading', { name: /my progress/i })).toBeInTheDocument()
    expect(screen.getAllByText('75%').length).toBeGreaterThan(0)
    expect(screen.getByRole('link', { name: /view result/i })).toHaveAttribute('href', '/student/results/10')
    expect(screen.getByRole('button', { name: /export csv/i })).toBeInTheDocument()
  })

  it('renders a student report for a teacher', async () => {
    renderApp('/teacher/students/3', TEACHER, [
      {
        method: 'GET',
        pattern: '^/reports/student/3$',
        data: () => ({
          student: { id: 3, full_name: 'Kofi Boateng', email: 's@t.test' },
          summary: { exams_taken: 1, average_percentage: 8.33, best_percentage: 8.33, worst_percentage: 8.33, passed_count: 0, failed_count: 1, pass_rate: 0 },
          history: [
            {
              attempt_id: 10,
              exam_id: 1,
              exam_title: 'Algebra Basics',
              subject: 'Mathematics',
              status: 'submitted',
              score: 0.5,
              percentage: 8.33,
              passed: false,
              total_marks: 6,
              pass_marks: 3,
              submitted_at: '2026-11-06T19:05:00+00:00',
            },
          ],
          trend: [{ label: 'Algebra Basics', submitted_at: '2026-11-06T19:05:00+00:00', percentage: 8.33, score: 0.5 }],
        }),
      },
    ])

    expect(await screen.findByRole('heading', { name: 'Kofi Boateng' })).toBeInTheDocument()
    expect(screen.getByText('Algebra Basics')).toBeInTheDocument()
    expect(screen.getAllByText('8.33%').length).toBeGreaterThan(0)
  })
})
