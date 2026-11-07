/**
 * Automated accessibility audit (axe-core) for every screen.
 *
 * Each page is rendered with a mocked API, then axe runs against the rendered
 * DOM. Only "serious" and "critical" violations fail the build; everything is
 * printed so lower-impact findings stay visible.
 *
 * Colour contrast is deliberately covered elsewhere (scripts/ux_check.py),
 * because jsdom has no layout engine and axe skips contrast there.
 */

import React, { act } from 'react'
import { describe, expect, it, vi } from 'vitest'
import { render, screen } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import axe from 'axe-core'
import App from '../App'
import { AuthProvider } from '../auth/AuthContext'

const STUDENT = { id: 3, full_name: 'Kofi Boateng', email: 's@t.test', role: 'student', created_at: '2026-11-06T19:00:00+00:00' }
const TEACHER = { id: 2, full_name: 'Grace Mensah', email: 't@t.test', role: 'teacher', created_at: '2026-11-06T19:00:00+00:00' }
const TOKEN = 'token.value.here'

function jsonResponse(data, status = 200) {
  return { ok: status < 400, status, text: async () => JSON.stringify(data) }
}

function mockApi(handlers) {
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

const EXAM_CARD = {
  id: 1,
  title: 'Algebra Basics',
  description: 'Chapter 1',
  subject: 'Mathematics',
  duration_minutes: 30,
  total_marks: 6,
  pass_marks: 3,
  start_time: null,
  end_time: null,
  is_published: true,
  allow_retakes: false,
  question_count: 2,
  attempt_count: 1,
  attempt: null,
}

const ATTEMPT = {
  attempt: { id: 7, status: 'in_progress', started_at: '2026-11-06T19:00:00+00:00' },
  exam: { id: 1, title: 'Algebra Basics', subject: 'Mathematics', duration_minutes: 30, total_marks: 4, pass_marks: 2 },
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
    {
      id: 12,
      question_text: 'Which are prime?',
      question_type: 'multiple_choice',
      marks: 2,
      options: [
        { id: 201, option_text: '2' },
        { id: 202, option_text: '4' },
      ],
    },
  ],
  answers: { 11: [102] },
  time: { remaining_seconds: 240, expired: false },
}

const RESULT = {
  attempt: { id: 7, status: 'submitted', submitted_at: '2026-11-06T19:10:00+00:00' },
  exam: { id: 1, title: 'Algebra Basics', subject: 'Mathematics', total_marks: 4, pass_marks: 2, end_time: null },
  result: { score: 4, percentage: 100, passed: true, status: 'submitted' },
  review_available: true,
  review_reason: null,
  questions: [
    {
      id: 11,
      question_text: 'What is 2 + 2?',
      question_type: 'single_choice',
      marks: 2,
      marks_awarded: 2,
      is_correct: true,
      selected_option_ids: [102],
      options: [
        { id: 101, option_text: '3', is_correct: false },
        { id: 102, option_text: '4', is_correct: true },
      ],
    },
  ],
}

const STUDENT_REPORT = {
  student: { id: 3, full_name: 'Kofi Boateng', email: 's@t.test' },
  summary: { exams_taken: 1, average_percentage: 100, best_percentage: 100, worst_percentage: 100, passed_count: 1, failed_count: 0, pass_rate: 100 },
  history: [
    { attempt_id: 7, exam_id: 1, exam_title: 'Algebra Basics', score: 4, total_marks: 4, percentage: 100, passed: true, submitted_at: '2026-11-06T19:10:00+00:00' },
  ],
  trend: [{ label: 'Algebra Basics', percentage: 100, score: 4, submitted_at: '2026-11-06T19:10:00+00:00' }],
}

const EXAM_REPORT = {
  exam: { id: 1, title: 'Algebra Basics', subject: 'Mathematics', total_marks: 4, pass_marks: 2, duration_minutes: 30, is_published: true, end_time: null },
  summary: { attempt_count: 1, average_percentage: 100, highest_percentage: 100, lowest_percentage: 100, median_percentage: 100, average_score: 4, highest_score: 4, lowest_score: 4, passed_count: 1, failed_count: 0, pass_rate: 100 },
  distribution: [
    { band: '0-20%', count: 0 },
    { band: '21-40%', count: 0 },
    { band: '41-60%', count: 0 },
    { band: '61-80%', count: 0 },
    { band: '81-100%', count: 1 },
  ],
  questions: [
    { question_id: 11, question_text: 'What is 2 + 2?', question_type: 'single_choice', marks: 2, graded_count: 1, correct_count: 1, percent_correct: 100 },
  ],
}

const LEADERBOARD = {
  exam: { id: 1, title: 'Algebra Basics', end_time: null },
  entries: [
    { rank: 1, student_id: 3, student_name: 'Kofi Boateng', attempt_id: 7, score: 4, percentage: 100, passed: true, submitted_at: '2026-11-06T19:10:00+00:00' },
  ],
}

const BASE_HANDLERS = (user) => [
  { method: 'GET', pattern: '^/auth/me$', data: () => ({ user }) },
  { method: 'GET', pattern: '^/exams$', data: () => ({ exams: [EXAM_CARD] }) },
  { method: 'GET', pattern: '^/exams/1$', data: () => ({ exam: { ...EXAM_CARD, questions: [] } }) },
  { method: 'GET', pattern: '^/attempts/7$', data: () => ATTEMPT },
  { method: 'GET', pattern: '^/attempts/7/result$', data: () => RESULT },
  { method: 'GET', pattern: '^/reports/student/3$', data: () => STUDENT_REPORT },
  { method: 'GET', pattern: '^/reports/exam/1$', data: () => EXAM_REPORT },
  { method: 'GET', pattern: '^/reports/leaderboard/1$', data: () => LEADERBOARD },
]

const SCREENS = [
  { name: 'login', path: '/login', user: null },
  { name: 'register', path: '/register', user: null },
  { name: 'student dashboard', path: '/dashboard', user: STUDENT },
  { name: 'student exam list', path: '/student', user: STUDENT },
  { name: 'taking an exam', path: '/student/attempts/7', user: STUDENT },
  { name: 'result + review', path: '/student/results/7', user: STUDENT },
  { name: 'student progress', path: '/student/progress', user: STUDENT },
  { name: 'teacher exam list', path: '/teacher', user: TEACHER },
  { name: 'exam editor', path: '/teacher/exams/1', user: TEACHER },
  { name: 'exam report', path: '/teacher/reports/1', user: TEACHER },
  { name: 'student report', path: '/teacher/students/3', user: TEACHER },
  { name: 'not found', path: '/nope', user: STUDENT },
]

async function audit(context) {
  const results = await axe.run(context, {
    resultTypes: ['violations'],
    rules: {
      // jsdom has no layout/paint, so these cannot be evaluated meaningfully.
      'color-contrast': { enabled: false },
      'target-size': { enabled: false },
    },
  })
  return results.violations
}

describe('Accessibility (axe-core)', () => {
  it('the audit itself detects real problems (meta check)', async () => {
    // Guards against a silently-green suite: if axe stops working, this fails.
    const sandbox = document.createElement('div')
    const stray = document.createElement('img')
    stray.src = '/broken.png' // no alt text -> axe must flag image-alt
    const button = document.createElement('button') // no accessible name
    sandbox.append(stray, button)
    document.body.append(sandbox)

    try {
      const ids = (await audit(sandbox)).map((v) => v.id)
      expect(ids).toContain('image-alt')
      expect(ids).toContain('button-name')
    } finally {
      sandbox.remove()
    }
  })

  for (const screenDef of SCREENS) {
    it(`${screenDef.name} has no serious or critical violations`, async () => {
      if (screenDef.user) localStorage.setItem('auspify.access_token', TOKEN)
      else localStorage.removeItem('auspify.access_token')
      mockApi(BASE_HANDLERS(screenDef.user))

      const { container } = render(
        <MemoryRouter initialEntries={[screenDef.path]}>
          <AuthProvider>
            <App />
          </AuthProvider>
        </MemoryRouter>,
      )

      // Let the mocked fetches (and any follow-up state updates) settle so the
      // loaded state is audited - not the spinner.
      await screen.findByRole('heading')
      await act(async () => {
        await new Promise((resolve) => setTimeout(resolve, 0))
      })

      const violations = await audit(container)
      const blockers = violations.filter((v) => ['serious', 'critical'].includes(v.impact))
      const summary = blockers.map((v) => `${v.id} (${v.impact}): ${v.help} -> ${v.nodes.length} node(s)`)

      expect(summary, summary.join('\n')).toEqual([])
    })
  }
})
