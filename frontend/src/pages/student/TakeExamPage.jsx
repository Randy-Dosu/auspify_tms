import { useCallback, useEffect, useRef, useState } from 'react'
import { useNavigate, useParams } from 'react-router-dom'
import { attemptsApi } from '../../api/client'
import { Alert, Badge, Spinner } from '../../components/ui'
import Modal from '../../components/Modal'

/** mm:ss */
function formatTime(totalSeconds) {
  const safe = Math.max(0, totalSeconds)
  const minutes = Math.floor(safe / 60)
  const seconds = safe % 60
  return `${String(minutes).padStart(2, '0')}:${String(seconds).padStart(2, '0')}`
}

/**
 * Exam-taking page.
 *
 * The countdown is driven by `remaining_seconds` from the server and is only a
 * display. The API re-checks the deadline on every save and submit, so editing
 * the browser timer cannot extend the exam.
 */
export default function TakeExamPage() {
  const { attemptId } = useParams()
  const navigate = useNavigate()
  const [state, setState] = useState({ status: 'loading', data: null, error: '' })
  const [answers, setAnswers] = useState({})
  const [remaining, setRemaining] = useState(0)
  const [saveState, setSaveState] = useState({ questionId: null, status: 'idle' })
  const [confirmOpen, setConfirmOpen] = useState(false)
  const [submitting, setSubmitting] = useState(false)
  const submittedRef = useRef(false)

  // --- Load / resume ------------------------------------------------------
  const load = useCallback(async () => {
    try {
      const data = await attemptsApi.get(attemptId)
      if (data.attempt.status !== 'in_progress') {
        submittedRef.current = true
        navigate(`/student/results/${attemptId}`, { replace: true })
        return
      }
      setState({ status: 'ready', data, error: '' })
      setAnswers(data.answers || {})
      setRemaining(data.time.remaining_seconds)
    } catch (err) {
      setState({ status: 'error', data: null, error: err.message })
    }
  }, [attemptId, navigate])

  useEffect(() => {
    load()
  }, [load])

  // --- Countdown ----------------------------------------------------------
  const submit = useCallback(
    async (auto = false) => {
      if (submittedRef.current) return
      submittedRef.current = true
      setSubmitting(true)
      setConfirmOpen(false)
      try {
        await attemptsApi.submit(attemptId)
        navigate(`/student/results/${attemptId}`, { replace: true, state: { auto } })
      } catch (err) {
        submittedRef.current = false
        setState((current) => ({ ...current, error: err.message }))
        setSubmitting(false)
      }
    },
    [attemptId, navigate],
  )

  useEffect(() => {
    if (state.status !== 'ready') return undefined
    const interval = setInterval(() => {
      setRemaining((current) => {
        if (current <= 1) {
          clearInterval(interval)
          // Time is up: submit automatically (the server would reject more answers).
          submit(true)
          return 0
        }
        return current - 1
      })
    }, 1000)
    return () => clearInterval(interval)
  }, [state.status, submit])

  // --- Answering ----------------------------------------------------------
  async function choose(question, optionId) {
    const current = answers[question.id] || []
    let next
    if (question.question_type === 'multiple_choice') {
      next = current.includes(optionId)
        ? current.filter((id) => id !== optionId)
        : [...current, optionId]
    } else {
      next = current.includes(optionId) ? [] : [optionId]
    }
    setAnswers((all) => ({ ...all, [question.id]: next }))
    setSaveState({ questionId: question.id, status: 'saving' })
    try {
      await attemptsApi.answer(attemptId, { question_id: question.id, selected_option_ids: next })
      setSaveState({ questionId: question.id, status: 'saved' })
    } catch (err) {
      if (err.status === 409) {
        // The server closed the attempt (time expired) - go to the result.
        submittedRef.current = true
        navigate(`/student/results/${attemptId}`, { replace: true, state: { auto: true } })
        return
      }
      setSaveState({ questionId: question.id, status: 'error' })
      setState((current) => ({ ...current, error: err.message }))
    }
  }

  if (state.status === 'loading') return <Spinner label="Loading your exam…" />
  if (state.status === 'error') {
    return (
      <>
        <Alert>{state.error}</Alert>
        <button type="button" className="btn" onClick={() => navigate('/student')}>
          Back to my exams
        </button>
      </>
    )
  }

  const { data } = state
  const answeredCount = data.questions.filter((q) => (answers[q.id] || []).length > 0).length
  const unanswered = data.questions.length - answeredCount
  const lowTime = remaining <= 60

  return (
    <>
      <header className="exam-header">
        <div>
          <h1>{data.exam.title}</h1>
          <p className="muted small">
            {data.questions.length} questions · {data.exam.total_marks} marks ·{' '}
            {answeredCount} answered
          </p>
        </div>
        <div className={`timer ${lowTime ? 'low' : ''}`} aria-live="polite">
          <span className="timer-label">Time left</span>
          <span className="timer-value">{formatTime(remaining)}</span>
        </div>
      </header>

      <Alert>{state.error}</Alert>

      <div className="exam-layout">
        <nav className="question-nav" aria-label="Question navigation">
          {data.questions.map((question, index) => (
            <a
              key={question.id}
              href={`#q-${question.id}`}
              className={(answers[question.id] || []).length ? 'answered' : ''}
            >
              {index + 1}
            </a>
          ))}
        </nav>

        <div className="question-stack">
          {data.questions.map((question, index) => {
            const selected = answers[question.id] || []
            const saving = saveState.questionId === question.id
            return (
              <section className="card question-block" id={`q-${question.id}`} key={question.id}>
                <div className="question-head">
                  <span className="question-index">Q{index + 1}</span>
                  <Badge tone="neutral">{question.question_type.replace('_', ' ')}</Badge>
                  <span className="muted small">
                    {question.marks} mark{question.marks === 1 ? '' : 's'}
                  </span>
                  {saving && saveState.status === 'saving' && (
                    <span className="save-state">saving…</span>
                  )}
                  {saving && saveState.status === 'saved' && (
                    <span className="save-state saved">saved</span>
                  )}
                </div>
                <p className="question-text">{question.question_text}</p>
                <ul className="answer-options">
                  {question.options.map((option) => {
                    const checked = selected.includes(option.id)
                    return (
                      <li key={option.id}>
                        <label className={checked ? 'option checked' : 'option'}>
                          <input
                            type={question.question_type === 'multiple_choice' ? 'checkbox' : 'radio'}
                            name={`q-${question.id}`}
                            checked={checked}
                            onChange={() => choose(question, option.id)}
                          />
                          <span>{option.option_text}</span>
                        </label>
                      </li>
                    )
                  })}
                </ul>
              </section>
            )
          })}

          <section className="card submit-bar">
            <div>
              <strong>{answeredCount}</strong> of {data.questions.length} answered
              {unanswered > 0 && <span className="muted"> · {unanswered} left</span>}
            </div>
            <button
              type="button"
              className="btn"
              onClick={() => setConfirmOpen(true)}
              disabled={submitting}
            >
              {submitting ? 'Submitting…' : 'Submit exam'}
            </button>
          </section>
        </div>
      </div>

      <Modal
        open={confirmOpen}
        title="Submit your exam?"
        onClose={() => setConfirmOpen(false)}
        footer={
          <>
            <button type="button" className="btn secondary" onClick={() => setConfirmOpen(false)}>
              Keep working
            </button>
            <button type="button" className="btn" onClick={() => submit(false)} disabled={submitting}>
              Yes, submit
            </button>
          </>
        }
      >
        {unanswered > 0 ? (
          <p>
            You still have <strong>{unanswered}</strong> unanswered question
            {unanswered === 1 ? '' : 's'}. Unanswered questions score zero.
          </p>
        ) : (
          <p>All questions answered. You cannot change your answers after submitting.</p>
        )}
      </Modal>
    </>
  )
}
