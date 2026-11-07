import { useCallback, useEffect, useState } from 'react'
import { Link, useParams } from 'react-router-dom'
import {
  CartesianGrid,
  Line,
  LineChart,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from 'recharts'
import { downloadCsv, reportsApi } from '../../api/client'
import { Alert, Badge, PageHeader, Spinner } from '../../components/ui'

/** Teacher/admin view of one student's history and trend. */
export default function StudentReportPage() {
  const { studentId } = useParams()
  const [state, setState] = useState({ loading: true, report: null, error: '' })

  const load = useCallback(async () => {
    try {
      const report = await reportsApi.student(studentId)
      setState({ loading: false, report, error: '' })
    } catch (err) {
      setState({ loading: false, report: null, error: err.message })
    }
  }, [studentId])

  useEffect(() => {
    load()
  }, [load])

  if (state.loading) return <Spinner label="Loading the student report…" />
  if (state.error) {
    return (
      <>
        <Alert>{state.error}</Alert>
        <Link className="btn" to="/teacher">
          Back to exams
        </Link>
      </>
    )
  }

  const { report } = state
  const chartData = report.trend.map((point, index) => ({
    name: `#${index + 1}`,
    percentage: point.percentage,
    label: point.label,
  }))

  return (
    <>
      <PageHeader
        title={report.student.full_name}
        subtitle={`${report.student.email} · ${report.summary.exams_taken} graded attempt${report.summary.exams_taken === 1 ? '' : 's'}`}
        actions={
          <>
            <button
              type="button"
              className="btn secondary"
              onClick={() =>
                downloadCsv(
                  `/reports/student/${studentId}?format=csv`,
                  `student-${studentId}-report.csv`,
                )
              }
            >
              Export CSV
            </button>
            <Link className="btn" to="/teacher">
              Back
            </Link>
          </>
        }
      />

      <div className="stat-grid">
        <div className="stat-card">
          <span className="stat-label">Exams taken</span>
          <strong className="stat-value">{report.summary.exams_taken}</strong>
        </div>
        <div className="stat-card">
          <span className="stat-label">Average</span>
          <strong className="stat-value">{report.summary.average_percentage}%</strong>
        </div>
        <div className="stat-card">
          <span className="stat-label">Best</span>
          <strong className="stat-value">{report.summary.best_percentage}%</strong>
        </div>
        <div className="stat-card">
          <span className="stat-label">Pass rate</span>
          <strong className="stat-value">{report.summary.pass_rate}%</strong>
          <span className="stat-hint">
            {report.summary.passed_count} passed · {report.summary.failed_count} failed
          </span>
        </div>
      </div>

      <section className="card">
        <h2>Progress trend</h2>
        {chartData.length === 0 ? (
          <p className="muted">No graded attempts yet.</p>
        ) : (
          <div className="chart">
            <ResponsiveContainer width="100%" height={260}>
              <LineChart data={chartData} margin={{ top: 8, right: 16, bottom: 0, left: -18 }}>
                <CartesianGrid strokeDasharray="3 3" vertical={false} />
                <XAxis dataKey="name" tick={{ fontSize: 12 }} />
                <YAxis domain={[0, 100]} unit="%" tick={{ fontSize: 12 }} />
                <Tooltip formatter={(value, _name, item) => [`${value}%`, item.payload.label]} />
                <Line type="monotone" dataKey="percentage" stroke="#2563eb" strokeWidth={2} dot />
              </LineChart>
            </ResponsiveContainer>
          </div>
        )}
      </section>

      <section className="card table-card">
        <h2>History</h2>
        {report.history.length === 0 ? (
          <p className="muted">No attempts.</p>
        ) : (
          <table className="table">
            <thead>
              <tr>
                <th>Exam</th>
                <th className="num">Score</th>
                <th className="num">Percentage</th>
                <th>Result</th>
                <th>Status</th>
                <th>Submitted</th>
              </tr>
            </thead>
            <tbody>
              {report.history.map((entry) => (
                <tr key={entry.attempt_id}>
                  <td>{entry.exam_title}</td>
                  <td className="num">
                    {entry.score} / {entry.total_marks}
                  </td>
                  <td className="num">{entry.percentage}%</td>
                  <td>
                    <Badge tone={entry.passed ? 'success' : 'danger'}>
                      {entry.passed ? 'passed' : 'failed'}
                    </Badge>
                  </td>
                  <td className="muted small">{entry.status}</td>
                  <td className="small muted">
                    {entry.submitted_at ? new Date(entry.submitted_at).toLocaleString() : '—'}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </section>
    </>
  )
}
