import { useState } from 'react'

function isValidTimetableUrl(value) {
  try {
    const url = new URL(value.trim())
    return ['https:', 'http:', 'webcal:'].includes(url.protocol)
      && Boolean(url.hostname)
      && !url.username && !url.password && !url.hash
      && !/\s/.test(value.trim())
  } catch {
    return false
  }
}

export default function UoaTimetableImport({ onImported }) {
  const [isChecking, setIsChecking] = useState(false)
  const [isImporting, setIsImporting] = useState(false)
  const [isModalOpen, setIsModalOpen] = useState(false)
  const [timetableUrl, setTimetableUrl] = useState('')
  const [message, setMessage] = useState('')
  const [error, setError] = useState('')

  async function importTimetable(url = null) {
    if (isImporting) return
    setIsImporting(true)
    setMessage('Importing UoA timetable...')
    setError('')
    try {
      const response = await fetch('/api/uoa/import', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ timetable_url: url }),
      })
      const result = await response.json().catch(() => ({}))
      if (!response.ok) {
        throw new Error(typeof result.detail === 'string'
          ? result.detail : 'UoA timetable import failed. Please try again.')
      }
      setIsModalOpen(false)
      setTimetableUrl('')
      setMessage('UoA timetable imported successfully.'
        + (result.skipped ? ` ${result.skipped} events were skipped because they could not be converted.` : ''))
      try {
        await onImported()
      } catch {
        setError('The import was saved, but the calendar could not refresh. Reload the page to see it.')
      }
    } catch (requestError) {
      setMessage('')
      setError(requestError instanceof TypeError
        ? 'Could not reach the backend. Check that it is running.'
        : requestError.message)
    } finally {
      setIsImporting(false)
    }
  }

  async function handleClick() {
    if (isChecking || isImporting) return
    setIsChecking(true)
    setMessage('')
    setError('')
    try {
      const response = await fetch('/api/uoa/status')
      if (!response.ok) throw new Error('Could not check the UoA timetable configuration.')
      const status = await response.json()
      if (status.configured) await importTimetable()
      else setIsModalOpen(true)
    } catch {
      setError('Could not check the UoA timetable configuration. Check that the backend is running.')
    } finally {
      setIsChecking(false)
    }
  }

  function handleSubmit(event) {
    event.preventDefault()
    if (isValidTimetableUrl(timetableUrl)) importTimetable(timetableUrl.trim())
  }

  function closeModal() {
    if (isImporting) return
    setIsModalOpen(false)
    setTimetableUrl('')
    setError('')
  }

  return (
    <>
      <button disabled={isChecking || isImporting} onClick={handleClick} type="button">
        {isImporting ? 'Importing UoA timetable...' : isChecking ? 'Checking...' : 'Import UoA Timetable'}
      </button>
      {!isModalOpen && message && <p className="timetable-import-message" role="status">{message}</p>}
      {!isModalOpen && error && <p className="timetable-import-message" role="alert">{error}</p>}
      {isModalOpen && (
        <div className="canvas-modal-overlay">
          <form className="canvas-modal" role="dialog" aria-modal="true" aria-labelledby="uoa-modal-heading" onSubmit={handleSubmit}>
            <h3 id="uoa-modal-heading">Connect UoA timetable</h3>
            <label>
              UoA timetable subscription URL
              <input
                type="url"
                autoComplete="off"
                spellCheck={false}
                required
                disabled={isImporting}
                placeholder="Paste your UoA timetable subscription URL"
                value={timetableUrl}
                onChange={(event) => setTimetableUrl(event.target.value)}
              />
            </label>
            <p>Your subscription URL will be saved locally for future imports.</p>
            {timetableUrl.trim() && !isValidTimetableUrl(timetableUrl) && (
              <p>Enter a valid HTTP, HTTPS or webcal subscription URL.</p>
            )}
            {message && <p role="status">{message}</p>}
            {error && <p role="alert">{error}</p>}
            <div className="canvas-modal-actions">
              <button disabled={isImporting || !isValidTimetableUrl(timetableUrl)} type="submit">
                {isImporting ? 'Importing UoA timetable...' : 'Import UoA Timetable'}
              </button>
              <button disabled={isImporting} onClick={closeModal} type="button">Close</button>
            </div>
          </form>
        </div>
      )}
    </>
  )
}
