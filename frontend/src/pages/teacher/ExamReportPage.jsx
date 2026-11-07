import { useCallback, useEffect, useState } from 'react'
import { Link, useParams } from 'react-router-dom'
import {
  Bar,
  BarChart,
  CartesianGrid,
  Cell,
  Line,
  LineChart,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from 'recharts'
import { downloadCsv, reportsApi } from '../../api/client'
import { Alert, Badge, PageHeader, Spinner } from '../../components/ui'

/** Teacher/admin exam performance dashboard. */
export default function ExamReportPage() {
  const { examId } = useParams()
  const [state, setState] = useState({ loading: true, report: null, board: null, error: '' })
  const [exporting, setExporting] = useState(false)

  const load = useCallback(async () => {
    try {
      const [report, board] = await Promise.all([
        reportsApi.exam(examId),
        reportsApi.leaderboard(examId),
      ])
      setState({ loading: false, report, board, error: '' })
    } catch (err) {
      setState({ loading: false, report: null, board: null, error: err.message })
    }
  }, [examId])

  useEffect(() => {
    load()
  }, [load])

  async function exportCsv(path, filename) {
    setExporting(true)
    try {
      await downloadCsv(path, filename)
    } catch (err) {
      setState((current) => ({ ...current, error: err.message }))
    } finally {
      setExporting(false)
    }
  }

  if (state.loading) return <Spinner label="Building the report…" />
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

  const { report, board } = state
  const s = report.summary

  return (
    <>
      <PageHeader
        title={`${report.exam.title} — performance`}
        subtitle={`${s.attempt_count} graded attempt${s.attempt_count === 1 ? '' : 's'} · pass mark ${report.exam.pass_marks} of ${report.exam.total_marks}`}
        actions={
          <>
            <button
              type="button"
              className="btn secondary"
              disabled={exporting}
              onClick={() => exportCsv(`/reports/exam/${examId}?format=csv`, `exam-${examId}-report.csv`)}
            >
              Export report CSV
            </button>
            <button
              type="button"
              className="btn secondary"
              disabled={exporting}
              onClick={() => exportCsv(`/reports/leaderboard/${examId}?format=csv`, `leaderboard-${examId}.csv`)}
            >
              Export leaderboard CSV
            </button>
            <Link className="btn" to={`/teacher/exams/${examId}`}>
              Edit exam
            </Link>
          </>
        }
      />

      <div className="stat-grid">
        <StatCard label="Attempts" value={s.attempt_count} />
        <StatCard label="Average" value={`${s.average_percentage}%`} />
        <StatCard label="Median" value={`${s.median_percentage}%`} />
        <StatCard label="Highest" value={`${s.highest_percentage}%`} />
        <StatCard label="Lowest" value={`${s.lowest_percentage}%`} />
        <StatCard label="Pass rate" value={`${s.pass_rate}%`} hint={`${s.passed_count} passed · ${s.failed_count} failed`} />
      </div>

      {s.attempt_count === 0 && (
        <Alert tone="success">No attempts yet — every statistic below is zero until students take the exam.</Alert>
      )}

      <div className="grid two">
        <section className="card">
          <h2>Score distribution</h2>
          <div className="chart">
            <ResponsiveContainer width="100%" height={240}>
              <BarChart data={report.distribution} margin={{ top: 8, right: 8, bottom: 0, left: -20 }}>
                <CartesianGrid strokeDasharray="3 3" vertical={false} />
                <XAxis dataKey="band" tick={{ fontSize: 12 }} />
                <YAxis allowDecimals={false} tick={{ fontSize: 12 }} />
                <Tooltip />
                <Bar dataKey="count" name="Students" radius={[6, 6, 0, 0]}>
                  {report.distribution.map((entry) => (
                    <Cell key={entry.band} fill="#2563eb" />
                  ))}
                </Bar>
              </BarChart>
            </ResponsiveContainer>
          </div>
        </section>

        <section className="card">
          <h2>Score spread</h2>
          <div className="chart">
            <ResponsiveContainer width="100%" height={240}>
              <LineChart
                data={board.entries.map((entry) => ({ name: `#${entry.rank}`, score: entry.score }))}
                margin={{ top: 8, right: 12, bottom: 0, left: -20 }}
              >
                <CartesianGrid strokeDasharray="3 3" vertical={false} />
                <XAxis dataKey="name" tick={{ fontSize: 12 }} />
                <YAxis tick={{ fontSize: 12 }} domain={[0, report.exam.total_marks]} />
                <Tooltip />
                <Line type="monotone" dataKey="score" name="Score" stroke="#16a34a" strokeWidth={2} dot />
              </LineChart>
            </ResponsiveContainer>
          </div>
        </section>
      </div>

      <section className="card table-card">
        <h2>Question difficulty</h2>
        <p className="muted small">Share of graded attempts that answered each question correctly.</p>
        {report.questions.length === 0 ? (
          <p className="muted">This exam has no questions yet.</p>
        ) : (
          <table className="table">
            <thead>
              <tr>
                <th>#</th>
                <th>Question</th>
                <th>Type</th>
                <th className="num">Marks</th>
                <th className="num">Graded</th>
                <th className="num">Correct</th>
                <th>Difficulty</th>
              </tr>
            </thead>
            <tbody>
              {report.questions.map((question, index) => (
                <tr key={question.question_id}>
                  <td className="num">{index + 1}</td>
                  <td>{question.question_text}</td>
                  <td className="muted small">{question.question_type.replace('_', ' ')}</td>
                  <td className="num">{question.marks}</td>
                  <td className="num">{question.graded_count}</td>
                  <td className="num">{question.correct_count}</td>
                  <td>
                    <div className="difficulty">
                      <div className="difficulty-bar">
                        <span style={{ width: `${question.percent_correct}%` }} />
                      </div>
                      <span className="small">{question.percent_correct}%</span>
                    </div>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </section>

      <section className="card table-card">
        <h2>Leaderboard</h2>
        {board.entries.length === 0 ? (
          <p className="muted">No results yet.</p>
        ) : (
          <table className="table">
            <thead>
              <tr>
                <th className="num">Rank</th>
                <th>Student</th>
                <th className="num">Score</th>
                <th className="num">Percentage</th>
                <th>Result</th>
                <th>Submitted</th>
                <th />
              </tr>
            </thead>
            <tbody>
              {board.entries.map((entry) => (
                <tr key={entry.attempt_id}>
                  <td className="num">{entry.rank}</td>
                  <td>{entry.student_name}</td>
                  <td className="num">{entry.score}</td>
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
                    <Link className="btn secondary small-btn" to={`/teacher/students/${entry.student_id}`}>
                      Student report
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

function StatCard({ label, value, hint }) {
  return (
    <div className="stat-card">
      <span className="stat-label">{label}</span>
      <strong className="stat-value">{value}</strong>
      {hint && <span className="stat-hint">{hint}</span>}
    </div>
  )
}
