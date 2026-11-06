import { Navigate } from 'react-router-dom'
import { useAuth } from '../auth/context'
import { Badge, PageHeader } from '../components/ui'

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
        <dd>{new Date(user.created_at).toLocaleDateString()}</dd>
      </dl>
    </section>
  )
}

/** Student home. Exam lists and results arrive in Steps 2-3. */
export function StudentDashboard() {
  const { user } = useAuth()
  return (
    <>
      <PageHeader
        title={`Hello, ${user.full_name.split(' ')[0]}`}
        subtitle="Your student dashboard."
      />
      <div className="grid two">
        <AccountCard />
        <section className="card">
          <h2>Available exams</h2>
          <p className="muted small">
            Your exam list, countdown timer and results appear here once your teacher
            publishes an exam.
          </p>
          <p className="small">
            <Badge tone="info">Step 2</Badge> exam taking · <Badge tone="info">Step 3</Badge>{' '}
            automatic results · <Badge tone="info">Step 4</Badge> progress reports
          </p>
        </section>
      </div>
    </>
  )
}

/** Teacher and admin home. The exam builder arrives in Step 2. */
export function StaffDashboard() {
  const { user } = useAuth()
  const isAdmin = user.role === 'admin'
  return (
    <>
      <PageHeader
        title={`Hello, ${user.full_name.split(' ')[0]}`}
        subtitle={isAdmin ? 'Administrator dashboard.' : 'Teacher dashboard.'}
      />
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
            <li>Exam builder with questions and options — Step 2</li>
            <li>Results and per-question review — Step 3</li>
            <li>Performance reports and CSV export — Step 4</li>
          </ul>
        </section>
      </div>
    </>
  )
}
