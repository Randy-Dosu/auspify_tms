import { useCallback, useEffect, useMemo, useState } from 'react'
import { Link, useParams } from 'react-router-dom'
import { examsApi } from '../../api/client'
import { Alert, Badge, Field, PageHeader, Spinner } from '../../components/ui'
import Modal from '../../components/Modal'

/** Convert a UTC ISO timestamp to the value a datetime-local input expects. */
function toLocalInput(iso) {
  if (!iso) return ''
  const date = new Date(iso)
  if (Number.isNaN(date.getTime())) return ''
  const pad = (n) => String(n).padStart(2, '0')
  return `${date.getFullYear()}-${pad(date.getMonth() + 1)}-${pad(date.getDate())}T${pad(date.getHours())}:${pad(date.getMinutes())}`
}

function fromLocalInput(value) {
  if (!value) return null
  const date = new Date(value)
  return Number.isNaN(date.getTime()) ? null : date.toISOString()
}

const EMPTY_QUESTION = {
  question_text: '',
  question_type: 'single_choice',
  marks: 1,
  negative_marks: 0,
  options: [
    { option_text: '', is_correct: true },
    { option_text: '', is_correct: false },
  ],
}

/** Teacher exam builder: settings + questions + options. */
export default function ExamEditorPage() {
  const { examId } = useParams()
  const [exam, setExam] = useState(null)
  const [settings, setSettings] = useState(null)
  const [questions, setQuestions] = useState([])
  const [loading, setLoading] = useState(true)
  const [saving, setSaving] = useState(false)
  const [message, setMessage] = useState('')
  const [error, setError] = useState('')
  const [fieldErrors, setFieldErrors] = useState({})
  const [editing, setEditing] = useState(null) // question object or EMPTY_QUESTION
  const [deleteTarget, setDeleteTarget] = useState(null)

  const load = useCallback(async () => {
    setLoading(true)
    try {
      const data = await examsApi.get(examId)
      setExam(data.exam)
      setSettings({
        title: data.exam.title,
        subject: data.exam.subject,
        description: data.exam.description,
        duration_minutes: data.exam.duration_minutes,
        pass_marks: data.exam.pass_marks,
        start_time: toLocalInput(data.exam.start_time),
        end_time: toLocalInput(data.exam.end_time),
        is_published: data.exam.is_published,
        allow_retakes: data.exam.allow_retakes,
      })
      setQuestions(data.exam.questions)
      setError('')
    } catch (err) {
      setError(err.message)
    } finally {
      setLoading(false)
    }
  }, [examId])

  useEffect(() => {
    load()
  }, [load])

  const lockedForEditing = useMemo(
    () => Boolean(exam?.is_published) && exam?.attempt_count > 0,
    [exam],
  )

  function onSettingChange(event) {
    const { name, value, type, checked } = event.target
    setSettings((current) => ({ ...current, [name]: type === 'checkbox' ? checked : value }))
  }

  async function saveSettings(event) {
    event.preventDefault()
    setSaving(true)
    setError('')
    setMessage('')
    setFieldErrors({})
    try {
      const payload = {
        title: settings.title.trim(),
        subject: settings.subject || '',
        description: settings.description || '',
        duration_minutes: Number(settings.duration_minutes),
        pass_marks: Number(settings.pass_marks),
        start_time: fromLocalInput(settings.start_time),
        end_time: fromLocalInput(settings.end_time),
        is_published: settings.is_published,
        allow_retakes: settings.allow_retakes,
      }
      const data = await examsApi.update(examId, payload)
      setExam(data.exam)
      setMessage('Settings saved.')
    } catch (err) {
      setError(err.message)
      setFieldErrors(err.fields || {})
    } finally {
      setSaving(false)
    }
  }

  async function saveQuestion(question) {
    setError('')
    setMessage('')
    setFieldErrors({})
    try {
      const payload = {
        question_text: question.question_text.trim(),
        question_type: question.question_type,
        marks: Number(question.marks),
        negative_marks: Number(question.negative_marks || 0),
        options: question.options.map((option) => ({
          option_text: option.option_text.trim(),
          is_correct: Boolean(option.is_correct),
        })),
      }
      if (question.id) await examsApi.updateQuestion(question.id, payload)
      else await examsApi.addQuestion(examId, payload)
      setEditing(null)
      setMessage('Question saved.')
      await load()
    } catch (err) {
      setError(err.message)
      setFieldErrors(err.fields || {})
    }
  }

  async function deleteQuestion() {
    const target = deleteTarget
    setDeleteTarget(null)
    try {
      await examsApi.deleteQuestion(target.id)
      setMessage('Question deleted.')
      await load()
    } catch (err) {
      setError(err.message)
    }
  }

  if (loading) return <Spinner label="Loading the exam…" />
  if (!exam) return <Alert>{error || 'Exam not found.'}</Alert>

  return (
    <>
      <PageHeader
        title={exam.title}
        subtitle={`${exam.total_marks} marks · ${exam.duration_minutes} minutes · ${questions.length} questions`}
        actions={
          <>
            <Badge tone={exam.is_published ? 'success' : 'neutral'}>
              {exam.is_published ? 'published' : 'draft'}
            </Badge>
            <Link className="btn secondary" to="/teacher">
              Back to exams
            </Link>
          </>
        }
      />

      <Alert>{error}</Alert>
      <Alert tone="success">{message}</Alert>

      <section className="card">
        <h2>Exam settings</h2>
        {lockedForEditing && (
          <p className="small muted">
            This exam is published and already has attempts, so its questions are locked.
            Settings can still be updated.
          </p>
        )}
        <form onSubmit={saveSettings} noValidate>
          <div className="grid two">
            <Field
              id="title"
              name="title"
              label="Title"
              value={settings.title}
              onChange={onSettingChange}
              error={fieldErrors.title?.[0]}
              required
            />
            <Field
              id="subject"
              name="subject"
              label="Subject"
              value={settings.subject}
              onChange={onSettingChange}
            />
            <Field
              id="duration_minutes"
              name="duration_minutes"
              label="Duration (minutes)"
              type="number"
              min="1"
              max="600"
              value={settings.duration_minutes}
              onChange={onSettingChange}
              error={fieldErrors.duration_minutes?.[0]}
              required
            />
            <Field
              id="pass_marks"
              name="pass_marks"
              label="Pass marks"
              type="number"
              min="0"
              step="0.5"
              value={settings.pass_marks}
              onChange={onSettingChange}
              error={fieldErrors.pass_marks?.[0]}
            />
            <Field
              id="start_time"
              name="start_time"
              label="Opens at (optional)"
              type="datetime-local"
              value={settings.start_time}
              onChange={onSettingChange}
              error={fieldErrors.start_time?.[0]}
            />
            <Field
              id="end_time"
              name="end_time"
              label="Closes at (optional)"
              type="datetime-local"
              value={settings.end_time}
              onChange={onSettingChange}
              error={fieldErrors.end_time?.[0]}
            />
          </div>

          <Field
            id="description"
            name="description"
            label="Description"
            value={settings.description}
            onChange={onSettingChange}
          />

          <div className="checkbox-row">
            <label>
              <input
                type="checkbox"
                name="is_published"
                checked={settings.is_published}
                onChange={onSettingChange}
              />{' '}
              Published (students can see it)
            </label>
            <label>
              <input
                type="checkbox"
                name="allow_retakes"
                checked={settings.allow_retakes}
                onChange={onSettingChange}
              />{' '}
              Allow retakes
            </label>
          </div>

          <button type="submit" className="btn" disabled={saving}>
            {saving ? 'Saving…' : 'Save settings'}
          </button>
        </form>
      </section>

      <section className="card">
        <div className="card-heading">
          <h2>Questions</h2>
          <button
            type="button"
            className="btn"
            onClick={() => setEditing({ ...EMPTY_QUESTION, options: EMPTY_QUESTION.options.map((o) => ({ ...o })) })}
            disabled={lockedForEditing}
          >
            + Add question
          </button>
        </div>

        {questions.length === 0 && <p className="muted">No questions yet.</p>}

        <ol className="question-list">
          {questions.map((question, index) => (
            <li key={question.id} className="question-item">
              <div className="question-head">
                <span className="question-index">Q{index + 1}</span>
                <span className="badge neutral">{question.question_type.replace('_', ' ')}</span>
                <span className="muted small">
                  {question.marks} mark{question.marks === 1 ? '' : 's'}
                  {question.negative_marks > 0 ? ` · −${question.negative_marks} negative` : ''}
                </span>
              </div>
              <p className="question-text">{question.question_text}</p>
              <ul className="option-list">
                {question.options.map((option) => (
                  <li key={option.id} className={option.is_correct ? 'correct' : undefined}>
                    {option.is_correct ? '✓ ' : '• '}
                    {option.option_text}
                  </li>
                ))}
              </ul>
              <div className="row-actions">
                <button
                  type="button"
                  className="btn secondary small-btn"
                  onClick={() => setEditing(question)}
                  disabled={lockedForEditing}
                >
                  Edit
                </button>
                <button
                  type="button"
                  className="btn danger small-btn"
                  onClick={() => setDeleteTarget(question)}
                  disabled={lockedForEditing}
                >
                  Delete
                </button>
              </div>
            </li>
          ))}
        </ol>
      </section>

      {editing && (
        <QuestionEditor
          question={editing}
          fieldErrors={fieldErrors}
          onCancel={() => {
            setEditing(null)
            setFieldErrors({})
          }}
          onSave={saveQuestion}
        />
      )}

      <Modal
        open={Boolean(deleteTarget)}
        title="Delete this question?"
        onClose={() => setDeleteTarget(null)}
        footer={
          <>
            <button type="button" className="btn secondary" onClick={() => setDeleteTarget(null)}>
              Cancel
            </button>
            <button type="button" className="btn danger" onClick={deleteQuestion}>
              Delete question
            </button>
          </>
        }
      >
        <p>{deleteTarget?.question_text}</p>
      </Modal>
    </>
  )
}

/** Add/edit form for a single question and its options. */
function QuestionEditor({ question, fieldErrors, onCancel, onSave }) {
  const [draft, setDraft] = useState(question)

  const update = (patch) => setDraft((current) => ({ ...current, ...patch }))

  function updateOption(index, patch) {
    const options = draft.options.map((option, i) => (i === index ? { ...option, ...patch } : option))
    update({ options })
  }

  function addOption() {
    if (draft.options.length >= 6) return
    update({ options: [...draft.options, { option_text: '', is_correct: false }] })
  }

  function removeOption(index) {
    if (draft.options.length <= 2) return
    update({ options: draft.options.filter((_, i) => i !== index) })
  }

  return (
    <section className="card">
      <h2>{question.id ? 'Edit question' : 'New question'}</h2>
      <Alert>{fieldErrors.options?.[0] || fieldErrors.negative_marks?.[0]}</Alert>

      <Field
        id="question_text"
        label="Question text"
        value={draft.question_text}
        onChange={(event) => update({ question_text: event.target.value })}
        error={fieldErrors.question_text?.[0]}
      />

      <div className="grid two">
        <div className="field">
          <label htmlFor="question_type">Type</label>
          <select
            id="question_type"
            value={draft.question_type}
            onChange={(event) => update({ question_type: event.target.value })}
          >
            <option value="single_choice">Single choice</option>
            <option value="multiple_choice">Multiple choice</option>
            <option value="true_false">True / false</option>
          </select>
        </div>
        <Field
          id="marks"
          label="Marks"
          type="number"
          min="0.5"
          step="0.5"
          value={draft.marks}
          onChange={(event) => update({ marks: event.target.value })}
          error={fieldErrors.marks?.[0]}
        />
        <Field
          id="negative_marks"
          label="Negative marks (wrong answer)"
          type="number"
          min="0"
          step="0.5"
          value={draft.negative_marks}
          onChange={(event) => update({ negative_marks: event.target.value })}
        />
      </div>

      <h3>Options</h3>
      <p className="small muted">
        Tick the correct option(s). 2 to 6 options are allowed.
      </p>
      <ul className="option-editor">
        {draft.options.map((option, index) => (
          <li key={index}>
            <input
              type="checkbox"
              aria-label={`Option ${index + 1} is correct`}
              checked={Boolean(option.is_correct)}
              onChange={(event) => updateOption(index, { is_correct: event.target.checked })}
            />
            <input
              type="text"
              aria-label={`Option ${index + 1} text`}
              placeholder={`Option ${index + 1}`}
              value={option.option_text}
              onChange={(event) => updateOption(index, { option_text: event.target.value })}
            />
            <button
              type="button"
              className="btn secondary small-btn"
              onClick={() => removeOption(index)}
              disabled={draft.options.length <= 2}
            >
              Remove
            </button>
          </li>
        ))}
      </ul>

      <div className="row-actions">
        <button type="button" className="btn secondary" onClick={addOption} disabled={draft.options.length >= 6}>
          + Option
        </button>
        <button type="button" className="btn secondary" onClick={onCancel}>
          Cancel
        </button>
        <button type="button" className="btn" onClick={() => onSave(draft)}>
          Save question
        </button>
      </div>
    </section>
  )
}
