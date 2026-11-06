import { useCallback, useEffect, useState } from 'react'
import { Link, useLocation, useParams } from 'react-router-dom'
import { resultsApi } from '../../api/client'
import { Alert, Badge, PageHeader, Spinner } from '../../components/ui'

/** Graded result: score, percentage, pass/fail and (later) the review. */
export default function ResultPage() {
  const { attemptId } = useParams()
  const location = useLocation()
  const [state, setState] = useState({ loading: true, data: null, error: '' })

  const load = useCallback(async () => {
    try {
      const data = await resultsApi.get(attemptId)
      setState({ loading: false, data, error: '' })
    } catch (err) {
      setState({ loading: false, data: null, error: err.message })
    }
  }, [attemptId])

  useEffect(() => {
    load()
  }, [load])

  if (state.loading) return <Spinner label="Loading your result…" />
  if (state.error) {
    return (
      <>
        <Alert>{state.error}</Alert>
        <Link className="btn" to="/student">
          Back to my exams
        </Link>
      </>
    )
  }

  const { attempt, exam, result, review_available: reviewAvailable, review_reason: reviewReason, questions } = state.data
  const passed = result.passed

  return (
    <>
      <PageHeader
        title={exam.title}
        subtitle={`${exam.subject || 'Exam'} · submitted ${attempt.submitted_at ? new Date(attempt.submitted_at).toLocaleString() : ''}`}
        actions={
          <Link className="btn secondary" to="/student">
            Back to my exams
          </Link>
        }
      />

      {location.state?.auto && (
        <Alert tone="success">
          Time ran out and your exam was submitted automatically. Everything you had saved was graded.
        </Alert>
      )}

      <section className="card result-hero">
        <div>
          <p className="muted small" style={{ margin: 0 }}>
            Your score
          </p>
          <p className="result-score">
            {result.score}
            <span className="result-total"> / {exam.total_marks}</span>
          </p>
        </div>
        <div className="result-stats">
          <div>
            <span className="muted small">Percentage</span>
            <strong>{result.percentage}%</strong>
          </div>
          <div>
            <span className="muted small">Pass mark</span>
            <strong>{exam.pass_marks}</strong>
          </div>
          <div>
            <span className="muted small">Outcome</span>
            <Badge tone={passed ? 'success' : 'danger'}>{passed ? 'passed' : 'failed'}</Badge>
          </div>
          <div>
            <span className="muted small">Status</span>
            <Badge tone={attempt.status === 'submitted' ? 'info' : 'neutral'}>{attempt.status}</Badge>
          </div>
        </div>
      </section>

      {!reviewAvailable && (
        <section className="card">
          <h2>Question review</h2>
          <p className="muted">{reviewReason || 'The question review opens when the exam window closes.'}</p>
        </section>
      )}

      {reviewAvailable && Array.isArray(questions) && (
        <section className="card">
          <h2>Question review</h2>
          {questions.map((question, index) => (
            <article className="review-item" key={question.id}>
              <div className="question-head">
                <span className="question-index">Q{index + 1}</span>
                <Badge tone={question.is_correct ? 'success' : question.selected_option_ids.length ? 'danger' : 'neutral'}>
                  {question.is_correct ? 'correct' : question.selected_option_ids.length ? 'wrong' : 'not answered'}
                </Badge>
                <span className="marks-awarded">
                  {question.marks_awarded > 0 ? '+' : ''}
                  {question.marks_awarded} / {question.marks}
                </span>
              </div>
              <p className="question-text">{question.question_text}</p>
              <ul className="option-list">
                {question.options.map((option) => {
                  const chosen = question.selected_option_ids.includes(option.id)
                  const classes = [option.is_correct ? 'correct' : '', chosen ? 'chosen' : '']
                    .filter(Boolean)
                    .join(' ')
                  return (
                    <li key={option.id} className={classes}>
                      {chosen ? '◉ ' : '○ '}
                      {option.option_text}
                      {option.is_correct && <span className="tag">correct answer</span>}
                      {chosen && !option.is_correct && <span className="tag wrong">your answer</span>}
                    </li>
                  )
                })}
              </ul>
            </article>
          ))}
        </section>
      )}
    </>
  )
}
