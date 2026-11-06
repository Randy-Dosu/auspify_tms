import { Link, useLocation, useParams } from 'react-router-dom'
import { PageHeader } from '../../components/ui'

/**
 * Confirmation shown after an attempt is submitted.
 * Step 3 replaces this with the graded result page at the same route.
 */
export default function SubmittedPage() {
  const { attemptId } = useParams()
  const location = useLocation()
  const auto = Boolean(location.state?.auto)

  return (
    <>
      <PageHeader
        title="Exam submitted"
        subtitle={
          auto
            ? 'Time ran out, so your exam was submitted automatically with the answers saved so far.'
            : 'Your answers were submitted successfully.'
        }
      />
      <section className="card">
        <p className="muted">
          Attempt #{attemptId} is closed. Your score is calculated on the server and will
          appear here once result publishing is enabled.
        </p>
        <Link className="btn" to="/student">
          Back to my exams
        </Link>
      </section>
    </>
  )
}
