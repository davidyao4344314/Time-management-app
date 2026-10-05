import { useRef, useState } from 'react'
import './ExamClipboardImport.css'

const fields = [
  ['name', 'Name', 'text'],
  ['category', 'Category', 'text'],
  ['subject', 'Subject', 'text'],
  ['date', 'Date', 'date'],
  ['start_time', 'Start time', 'time'],
  ['end_time', 'End time', 'time'],
]

async function requestImport(path, body) {
  const response = await fetch(`/api/exams/import${path}`, {
    method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body),
  })
  const result = await response.json()
  if (!response.ok) throw new Error(typeof result.detail === 'string' ? result.detail : 'Check the table and exam fields, then try again.')
  return result
}

export default function ExamClipboardImport({ onClose, onImported, onBusyChange }) {
  const [text, setText] = useState('')
  const [preview, setPreview] = useState(null)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  const inFlight = useRef(false)

  async function submit(event) {
    event.preventDefault()
    if (inFlight.current) return
    inFlight.current = true
    setBusy(true)
    onBusyChange(true)
    setError('')
    try {
      if (preview === null) {
        const result = await requestImport('/preview', { text })
        setPreview(result.exams)
      } else {
        const exams = preview.map(exam => ({
          ...exam, subject: exam.subject || null,
          start_time: exam.start_time || null, end_time: exam.end_time || null,
        }))
        const result = await requestImport('', { exams })
        await onImported(result)
      }
    } catch (failure) {
      setError(failure.message || 'Could not reach the server. Your input has been kept.')
    } finally {
      inFlight.current = false
      setBusy(false)
      onBusyChange(false)
    }
  }

  function updateExam(index, name, value) {
    setPreview(current => current.map((exam, row) => row === index ? { ...exam, [name]: value } : exam))
    setError('')
  }

  return <form className="add-activity-form exam-clipboard-form" onSubmit={submit} aria-labelledby="exam-import-heading">
    <h3 id="exam-import-heading">Import Exams from Clipboard</h3>
    {preview === null ? <>
      <label htmlFor="exam-table-text">Paste your exam timetable</label>
      <p>Copy the full exam table from the website, then paste it here with ⌘V (Mac) or Ctrl+V. Tab-separated tables, one cell per line, and Markdown tables are supported.</p>
      <textarea id="exam-table-text" value={text} rows={8} maxLength={50000} required disabled={busy}
        placeholder="Paste the complete exam table, from Course (Class Number) through Book…"
        onChange={event => { setText(event.target.value); setError('') }} />
      <p>No exams are saved until you review the preview and click Import Exams.</p>
      <p>For a website copy, include all seven columns: Course (Class Number), Course Title, Exam Date, Time, Campus, Room, and Book. Headers are optional.</p>
    </> : <>
      <p>Review {preview.length} exam{preview.length === 1 ? '' : 's'} below. You can correct any field before importing.</p>
      <p>Source: Manual. Course title, campus, room, and book rules are ignored. Identical existing exams will be skipped.</p>
      {preview.map((exam, index) => <fieldset key={index} className="exam-import-row" disabled={busy}>
        <legend>Exam {index + 1}</legend>
        <div className="add-activity-fields">
          {fields.map(([name, label, type]) => <label key={name}>
            {label}
            <input type={type} value={exam[name] || ''}
              required={['name', 'category', 'date'].includes(name)}
              onChange={event => updateExam(index, name, event.target.value)} />
          </label>)}
        </div>
      </fieldset>)}
    </>}
    {error && <p role="alert">{error}</p>}
    <div className="add-activity-actions">
      <button type="submit" disabled={busy || (preview === null && !text.trim())}>
        {busy ? (preview === null ? 'Preparing preview…' : 'Importing exams…') : (preview === null ? 'Preview Exams' : 'Import Exams')}
      </button>
      {preview !== null && <button type="button" disabled={busy} onClick={() => { setPreview(null); setError('') }}>Edit pasted table</button>}
      <button type="button" onClick={onClose} disabled={busy}>Cancel</button>
    </div>
  </form>
}
