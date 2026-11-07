import { useEffect, useState } from 'react'
import { Link, Navigate } from 'react-router-dom'
import { useAuth } from '../auth/context'
import { examsApi } from '../api/client'
import { Alert, Badge, PageHeader, Spinner } from '../components/ui'

/**
 * Sends each role to its own home. Used as the "/dashboard" target so a
 * logged-in user always lands on the right surface.
 */
export function DashboardRedirect() {
  const { user } = useAuth()
  if (!user) return <Navigate to="/login" replace />
  if (user.role === 'student') return <StudentDashboard />
  return <StaffDashboard />
}

function AccountCard() {
  const { user } = useAuth()
  return (
    <section className="card">
      <h2>Your account</h2>
      <dl className="data-list">
        <dt>Name</dt>
        <dd>{user.full_name}</dd>
        <dt>Email</dt>
        <dd>{user.email}</dd>
        <dt>Role</dt>
        <dd>
          <Badge tone={user.role === 'student' ? 'info' : 'success'}>{user.role}</Badge>
        </dd>
        <dt>Member since</dt>
        <dd>{user.created_at ? new Date(user.created_at).toLocaleDateString() : '—'}</dd>
      </dl>
    </section>
  )
}

/**
 * Loads the exam list once for the dashboard summary.
 * The dashboard must never break the page: a failed call degrades to a short
 * message instead of an error screen.
 */
function useExamSummary() {
  const [state, setState] = useState({ loading: true, exams: [], error: '' })

  useEffect(() => {
    let cancelled = false
    ;(async () => {
      try {
        const data = await examsApi.list()
        if (!cancelled) setState({ loading: false, exams: data.exams || [], error: '' })
      } catch (err) {
        if (!cancelled) setState({ loading: false, exams: [], error: err.message })
      }
    })()
    return () => {
      cancelled = true
    }
  }, [])

  return state
}

function Stat({ label, value, hint }) {
  return (
    <div className="stat-card">
      <span className="stat-label">{label}</span>
      <strong className="stat-value">{value}</strong>
      {hint && <span className="stat-hint">{hint}</span>}
    </div>
  )
}

/** Student home: what is open right now, plus a shortcut to progress. */
export function StudentDashboard() {
  const { user } = useAuth()
  const { loading, exams, error } = useExamSummary()

  const open = exams.filter((exam) => exam.attempt?.status !== 'submitted' && exam.attempt?.status !== 'expired')
  const inProgress = exams.filter((exam) => exam.attempt?.status === 'in_progress')
  const completed = exams.filter((exam) => exam.attempt && exam.attempt.status !== 'in_progress')

  return (
    <>
      <PageHeader
        title={`Hello, ${user.full_name.split(' ')[0]}`}
        subtitle="Your student dashboard."
        actions={
          <Link className="btn" to="/student">
            My exams
          </Link>
        }
      />

      {error && <Alert>{error}</Alert>}
      {loading ? (
        <Spinner label="Loading your exams…" />
      ) : (
        <div className="stat-grid">
          <Stat label="Open now" value={open.length} hint="exams you can start" />
          <Stat label="In progress" value={inProgress.length} hint="saved answers kept" />
          <Stat label="Completed" value={completed.length} hint="results available" />
          <Stat label="Your average" value="—" hint="open My progress for details" />
        </div>
      )}

      <div className="grid two">
        <AccountCard />
        <section className="card">
          <h2>What to do next</h2>
          <ul className="checklist">
            <li>
              <Link to="/student">Start or resume an exam</Link> — the timer is enforced by the server.
            </li>
            <li>
              <Link to="/student/progress">My progress</Link> — history, trend and CSV export.
            </li>
            <li>Answers save automatically while you work; submit when you are done.</li>
          </ul>
        </section>
      </div>
    </>
  )
}

/** Teacher and admin home: exam totals and a shortcut into the exam list. */
export function StaffDashboard() {
  const { user } = useAuth()
  const isAdmin = user.role === 'admin'
  const { loading, exams, error } = useExamSummary()

  const published = exams.filter((exam) => exam.is_published)
  const drafts = exams.length - published.length
  const attempts = exams.reduce((total, exam) => total + (exam.attempt_count || 0), 0)

  return (
    <>
      <PageHeader
        title={`Hello, ${user.full_name.split(' ')[0]}`}
        subtitle={isAdmin ? 'Administrator dashboard.' : 'Teacher dashboard.'}
        actions={
          <Link className="btn" to="/teacher">
            {isAdmin ? 'All exams' : 'My exams'}
          </Link>
        }
      />

      {error && <Alert>{error}</Alert>}
      {loading ? (
        <Spinner label="Loading your exams…" />
      ) : (
        <div className="stat-grid">
          <Stat label="Exams" value={exams.length} hint={isAdmin ? 'in the system' : 'created by you'} />
          <Stat label="Published" value={published.length} hint="visible to students" />
          <Stat label="Drafts" value={drafts} hint="not visible yet" />
          <Stat label="Attempts" value={attempts} hint="submitted or in progress" />
        </div>
      )}

      <div className="grid two">
        <AccountCard />
        <section className="card">
          <h2>{isAdmin ? 'Administration' : 'Your exams'}</h2>
          <p className="muted small">
            {isAdmin
              ? 'You can see and manage every exam and report in the system.'
              : 'Create exams, add questions and publish them to students.'}
          </p>
          <ul className="checklist">
            <li>
              <Link to="/teacher">Exam builder</Link> — questions, options, marks and timing.
            </li>
            <li>
              <strong>Report</strong> next to an exam — averages, distribution, difficulty and CSV.
            </li>
            <li>An exam with attempts is frozen: its questions can no longer change.</li>
          </ul>
        </section>
      </div>
    </>
  )
}
