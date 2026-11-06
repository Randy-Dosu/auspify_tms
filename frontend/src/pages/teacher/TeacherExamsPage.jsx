import { useCallback, useEffect, useState } from 'react'
import { Link, useNavigate } from 'react-router-dom'
import { examsApi } from '../../api/client'
import { Alert, Badge, PageHeader, Spinner } from '../../components/ui'
import Modal from '../../components/Modal'

/** Teacher/admin: list of exams with create / delete actions. */
export default function TeacherExamsPage() {
  const navigate = useNavigate()
  const [exams, setExams] = useState([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')
  const [pendingDelete, setPendingDelete] = useState(null)

  const load = useCallback(async () => {
    setLoading(true)
    try {
      const data = await examsApi.list()
      setExams(data.exams)
    } catch (err) {
      setError(err.message)
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => {
    load()
  }, [load])

  async function handleCreate() {
    setError('')
    try {
      const { exam } = await examsApi.create({
        title: 'Untitled exam',
        duration_minutes: 30,
        pass_marks: 0,
        is_published: false,
      })
      navigate(`/teacher/exams/${exam.id}`)
    } catch (err) {
      setError(err.message)
    }
  }

  async function confirmDelete() {
    const exam = pendingDelete
    setPendingDelete(null)
    try {
      await examsApi.remove(exam.id)
      await load()
    } catch (err) {
      setError(err.message)
    }
  }

  return (
    <>
      <PageHeader
        title="Exams"
        subtitle="Create exams, build questions and publish them to students."
        actions={
          <button type="button" className="btn" onClick={handleCreate}>
            + New exam
          </button>
        }
      />

      <Alert>{error}</Alert>
      {loading && <Spinner />}
      {!loading && exams.length === 0 && (
        <section className="card">
          <p className="muted">No exams yet. Create your first one.</p>
        </section>
      )}

      {!loading && exams.length > 0 && (
        <section className="card table-card">
          <table className="table">
            <thead>
              <tr>
                <th>Title</th>
                <th>Subject</th>
                <th className="num">Marks</th>
                <th className="num">Questions</th>
                <th className="num">Attempts</th>
                <th>Status</th>
                <th />
              </tr>
            </thead>
            <tbody>
              {exams.map((exam) => (
                <tr key={exam.id}>
                  <td>
                    <Link to={`/teacher/exams/${exam.id}`}>{exam.title}</Link>
                  </td>
                  <td className="muted">{exam.subject || '—'}</td>
                  <td className="num">{exam.total_marks}</td>
                  <td className="num">{exam.question_count}</td>
                  <td className="num">{exam.attempt_count}</td>
                  <td>
                    <Badge tone={exam.is_published ? 'success' : 'neutral'}>
                      {exam.is_published ? 'published' : 'draft'}
                    </Badge>
                  </td>
                  <td className="row-actions">
                    <Link className="btn secondary small-btn" to={`/teacher/exams/${exam.id}`}>
                      Edit
                    </Link>
                    <button
                      type="button"
                      className="btn danger small-btn"
                      onClick={() => setPendingDelete(exam)}
                    >
                      Delete
                    </button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </section>
      )}

      <Modal
        open={Boolean(pendingDelete)}
        title="Delete this exam?"
        onClose={() => setPendingDelete(null)}
        footer={
          <>
            <button type="button" className="btn secondary" onClick={() => setPendingDelete(null)}>
              Cancel
            </button>
            <button type="button" className="btn danger" onClick={confirmDelete}>
              Delete exam
            </button>
          </>
        }
      >
        <p>
          <strong>{pendingDelete?.title}</strong> and all of its questions will be removed.
          Exams that already have attempts cannot be deleted.
        </p>
      </Modal>
    </>
  )
}
