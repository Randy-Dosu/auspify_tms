/**
 * Step 2 UI tests: exam list, role guard, exam taking, autosave, submit.
 * Network is mocked; components and routing are real.
 */

import React from 'react'
import { describe, expect, it, vi } from 'vitest'
import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter } from 'react-router-dom'
import App from '../App'
import { AuthProvider } from '../auth/AuthContext'

const TEACHER = { id: 2, full_name: 'Grace Mensah', email: 't@t.test', role: 'teacher', is_active: 1, created_at: '2026-11-06T19:00:00+00:00' }
const STUDENT = { id: 3, full_name: 'Kofi Boateng', email: 's@t.test', role: 'student', is_active: 1, created_at: '2026-11-06T19:00:00+00:00' }
const TOKEN = 'token.value.here'

function jsonResponse(data, status = 200) {
  return { ok: status < 400, status, text: async () => JSON.stringify(data) }
}

/** Route table driven mock: {method, pattern (regex string), data(body, path)} */
function mockRoutes(handlers) {
  const calls = []
  global.fetch = vi.fn(async (url, options = {}) => {
    const path = String(url).replace(/^\/api/, '')
    const method = (options.method || 'GET').toUpperCase()
    const body = options.body ? JSON.parse(options.body) : null
    calls.push({ method, path, body, headers: options.headers })
    for (const handler of handlers) {
      if (handler.method === method && new RegExp(handler.pattern).test(path)) {
        return jsonResponse(handler.data(body, path), handler.status || 200)
      }
    }
    return jsonResponse({ error: { code: 404, message: `no route ${method} ${path}` } }, 404)
  })
  return calls
}

function renderApp(path, user, extraHandlers = []) {
  localStorage.setItem('auspify.access_token', TOKEN)
  const calls = mockRoutes([
    { method: 'GET', pattern: '^/auth/me$', data: () => ({ user }) },
    ...extraHandlers,
  ])
  const view = render(
    <MemoryRouter initialEntries={[path]}>
      <AuthProvider>
        <App />
      </AuthProvider>
    </MemoryRouter>,
  )
  return { ...view, calls }
}

const EXAM_LIST = {
  exams: [
    {
      id: 1,
      title: 'Algebra Basics',
      subject: 'Mathematics',
      description: 'Chapter 1',
      duration_minutes: 30,
      total_marks: 6,
      pass_marks: 3,
      start_time: null,
      end_time: null,
      is_published: true,
      allow_retakes: false,
      question_count: 3,
      attempt_count: 1,
    },
  ],
}

describe('Step 2 — exam UI', () => {
  it('lists a teacher’s exams in the builder dashboard', async () => {
    renderApp('/teacher', TEACHER, [
      { method: 'GET', pattern: '^/exams$', data: () => EXAM_LIST },
    ])

    expect(await screen.findByRole('heading', { name: 'Exams' })).toBeInTheDocument()
    expect(await screen.findByText('Algebra Basics')).toBeInTheDocument()
    expect(screen.getByText('published')).toBeInTheDocument()
  })

  it('blocks a student from the teacher area with a 403 page', async () => {
    renderApp('/teacher', STUDENT, [{ method: 'GET', pattern: '^/exams$', data: () => EXAM_LIST }])

    expect(await screen.findByRole('heading', { name: /403/i })).toBeInTheDocument()
    expect(screen.queryByText('Algebra Basics')).not.toBeInTheDocument()
  })

  it('lets a student start an exam and shows the questions with a server timer', async () => {
    const { calls } = renderApp('/student', STUDENT, [
      {
        method: 'GET',
        pattern: '^/exams$',
        data: () => ({
          exams: [
            {
              ...EXAM_LIST.exams[0],
              question_count: undefined,
              attempt_count: undefined,
              attempt: null,
            },
          ],
        }),
      },
      {
        method: 'POST',
        pattern: '^/exams/1/start$',
        status: 201,
        data: () => ({ attempt: { id: 7, status: 'in_progress' } }),
      },
      {
        method: 'GET',
        pattern: '^/attempts/7$',
        data: () => ({
          attempt: { id: 7, status: 'in_progress', started_at: '2026-11-06T19:00:00+00:00' },
          exam: { id: 1, title: 'Algebra Basics', duration_minutes: 30, total_marks: 4, pass_marks: 2 },
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
          answers: {},
          time: { remaining_seconds: 300, expired: false },
        }),
      },
      {
        method: 'PUT',
        pattern: '^/attempts/7/answer$',
        data: () => ({ saved_at: 'now', time: { remaining_seconds: 280 } }),
      },
      {
        method: 'POST',
        pattern: '^/attempts/7/submit$',
        data: () => ({ attempt: { id: 7, status: 'submitted' } }),
      },
    ])

    await userEvent.click(await screen.findByRole('button', { name: /start exam/i }))

    expect(await screen.findByText('What is 2 + 2?')).toBeInTheDocument()
    expect(screen.getByText(/^0[45]:\d{2}$/)).toBeInTheDocument()
    expect(screen.getByText('Which are prime?')).toBeInTheDocument()

    // Selecting an option autosaves it (Q1, second radio = option id 102).
    const q1Radios = screen.getAllByRole('radio')
    expect(q1Radios).toHaveLength(2)
    await userEvent.click(q1Radios[1])
    await waitFor(() => {
      const save = calls.find((call) => call.method === 'PUT' && call.path === '/attempts/7/answer')
      expect(save).toBeTruthy()
      expect(save.body).toEqual({ question_id: 11, selected_option_ids: [102] })
    })
    expect(await screen.findByText('saved')).toBeInTheDocument()

    // Submitting asks for confirmation first.
    await userEvent.click(screen.getByRole('button', { name: /submit exam/i }))
    expect(await screen.findByRole('dialog', { name: /submit your exam/i })).toBeInTheDocument()
    await userEvent.click(screen.getByRole('button', { name: /yes, submit/i }))

    expect(await screen.findByRole('heading', { name: /exam submitted/i })).toBeInTheDocument()
    expect(calls.some((call) => call.method === 'POST' && call.path === '/attempts/7/submit')).toBe(true)
  })

  it('opens the exam editor with its questions for staff', async () => {
    renderApp('/teacher/exams/1', TEACHER, [
      {
        method: 'GET',
        pattern: '^/exams/1$',
        data: () => ({
          exam: {
            ...EXAM_LIST.exams[0],
            questions: [
              {
                id: 11,
                question_text: 'What is 2 + 2?',
                question_type: 'single_choice',
                marks: 2,
                negative_marks: 0,
                options: [
                  { id: 101, option_text: '4', is_correct: true },
                  { id: 102, option_text: '5', is_correct: false },
                ],
              },
            ],
          },
        }),
      },
    ])

    expect(await screen.findByRole('heading', { name: 'Algebra Basics' })).toBeInTheDocument()
    expect(await screen.findAllByText(/What is 2 \+ 2\?/)).not.toHaveLength(0)
    expect(screen.getByRole('button', { name: /add question/i })).toBeInTheDocument()
    // The correct option is visible to staff only.
    expect(screen.getByText(/✓ 4/)).toBeInTheDocument()
  })
})
