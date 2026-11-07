import { useCallback, useEffect, useState } from 'react'
import { Link, useNavigate } from 'react-router-dom'
import { attemptsApi, examsApi } from '../../api/client'
import { Alert, Badge, PageHeader, Spinner } from '../../components/ui'

/** Student: exams currently open, with start / resume / completed state. */
export default function StudentExamsPage() {
  const navigate = useNavigate()
  const [exams, setExams] = useState([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')
  const [busyId, setBusyId] = useState(null)

  const load = useCallback(async () => {
    setLoading(true)
    try {
      const data = await examsApi.list()
      setExams(data.exams)
      setError('')
    } catch (err) {
      setError(err.message)
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => {
    load()
  }, [load])

  async function startOrResume(exam) {
    setError('')
    setBusyId(exam.id)
    try {
      const payload = await attemptsApi.start(exam.id)
      navigate(`/student/attempts/${payload.attempt.id}`)
    } catch (err) {
      setError(err.message)
      await load()
    } finally {
      setBusyId(null)
    }
  }

  return (
    <>
      <PageHeader title="My exams" subtitle="Exams that are open for you right now." />
      <Alert>{error}</Alert>
      {loading && <Spinner />}

      {!loading && exams.length === 0 && (
        <section className="card">
          <p className="muted">No exams are open right now. Check back later.</p>
        </section>
      )}

      <div className="grid two">
        {exams.map((exam) => {
          const attempt = exam.attempt
          const inProgress = attempt?.status === 'in_progress'
          const done = attempt && attempt.status !== 'in_progress'
          return (
            <section className="card exam-card" key={exam.id}>
              <div className="card-heading">
                <h2>{exam.title}</h2>
                <Badge tone={done ? 'success' : inProgress ? 'info' : 'neutral'}>
                  {done ? 'completed' : inProgress ? 'in progress' : 'available'}
                </Badge>
              </div>
              <p className="muted small">{exam.description || 'No description provided.'}</p>
              <dl className="data-list">
                <dt>Subject</dt>
                <dd>{exam.subject || '—'}</dd>
                <dt>Duration</dt>
                <dd>{exam.duration_minutes} minutes</dd>
                <dt>Marks</dt>
                <dd>
                  {exam.total_marks} total · {exam.pass_marks} to pass
                </dd>
                <dt>Closes</dt>
                <dd>{exam.end_time ? new Date(exam.end_time).toLocaleString() : 'Open-ended'}</dd>
              </dl>
              <div className="row-actions">
                {!done && (
                  <button
                    type="button"
                    className="btn"
                    disabled={busyId === exam.id}
                    onClick={() => startOrResume(exam)}
                  >
                    {busyId === exam.id
                      ? 'Opening…'
                      : inProgress
                        ? 'Resume exam'
                        : 'Start exam'}
                  </button>
                )}
                {done && (
                  <Link className="btn secondary" to={`/student/results/${attempt.id}`}>
                    View result
                  </Link>
                )}
              </div>
            </section>
          )
        })}
      </div>
    </>
  )
}
