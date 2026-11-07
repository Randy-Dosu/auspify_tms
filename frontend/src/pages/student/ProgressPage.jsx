import { useCallback, useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
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
import { useAuth } from '../../auth/context'
import { Alert, Badge, PageHeader, Spinner } from '../../components/ui'

/** Student: own history, trend and CSV export. */
export default function ProgressPage() {
  const { user } = useAuth()
  const [state, setState] = useState({ loading: true, report: null, error: '' })

  const load = useCallback(async () => {
    try {
      const report = await reportsApi.student(user.id)
      setState({ loading: false, report, error: '' })
    } catch (err) {
      setState({ loading: false, report: null, error: err.message })
    }
  }, [user.id])

  useEffect(() => {
    load()
  }, [load])

  if (state.loading) return <Spinner label="Loading your progress…" />
  if (state.error) return <Alert>{state.error}</Alert>

  const { report } = state
  const chartData = report.trend.map((point, index) => ({
    name: `#${index + 1}`,
    percentage: point.percentage,
    label: point.label,
  }))

  return (
    <>
      <PageHeader
        title="My progress"
        subtitle={`${report.summary.exams_taken} graded attempt${report.summary.exams_taken === 1 ? '' : 's'}`}
        actions={
          <button
            type="button"
            className="btn secondary"
            onClick={() => downloadCsv(`/reports/student/${user.id}?format=csv`, 'my-progress.csv')}
          >
            Export CSV
          </button>
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
        </div>
      </div>

      <section className="card">
        <h2>Your trend</h2>
        {chartData.length === 0 ? (
          <p className="muted">Take an exam and your progress will appear here.</p>
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
          <p className="muted">No attempts yet.</p>
        ) : (
          <table className="table">
            <thead>
              <tr>
                <th>Exam</th>
                <th className="num">Score</th>
                <th className="num">Percentage</th>
                <th>Result</th>
                <th>Submitted</th>
                <th />
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
                  <td className="small muted">
                    {entry.submitted_at ? new Date(entry.submitted_at).toLocaleString() : '—'}
                  </td>
                  <td>
                    <Link className="btn secondary small-btn" to={`/student/results/${entry.attempt_id}`}>
                      View result
                    </Link>
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
