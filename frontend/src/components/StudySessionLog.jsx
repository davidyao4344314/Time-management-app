import { useState } from 'react'
import useStudySessions from '../hooks/useStudySessions'
import './StudySessionLog.css'

const labels = { done: 'Done', partly_done: 'Partly done', missed: 'Missed' }

function SessionForm({ session, date, busy, saving, onSave }) {
  const [status, setStatus] = useState(session.completion?.status || 'done')
  const [minutes, setMinutes] = useState(session.completion?.actual_minutes ?? '')

  function changeStatus(value) {
    setStatus(value)
    if (value === 'missed') setMinutes(0)
    else if (Number(minutes) === 0) setMinutes('')
  }

  return (
    <li className="session-card">
      <div className="session-details">
        <h4>{session.name}</h4>
        <p>{session.subject || session.category}</p>
        <p>{session.start_time || session.end_time
          ? `${session.start_time || 'No start time'} – ${session.end_time || 'No end time'}` : 'No time set'}</p>
        <p className={`session-status ${session.completion ? `session-${session.completion.status}` : ''}`}>
          {session.completion?.automatic ? 'Missed automatically · 0 minutes'
            : session.completion ? `${labels[session.completion.status]} · ${session.completion.actual_minutes} min logged` : 'Not recorded'}
        </p>
      </div>
      <form className="session-form" aria-label={`Record ${session.name} on ${date}`} onSubmit={event => {
        event.preventDefault()
        onSave(session.activity_id, { status, actual_minutes: Number(minutes) })
      }}>
        <fieldset disabled={busy}>
          <legend className="session-sr-only">Session outcome</legend>
          <label>Outcome
            <select value={status} onChange={event => changeStatus(event.target.value)}>
              {Object.entries(labels).map(([value, label]) => <option key={value} value={value}>{label}</option>)}
            </select>
          </label>
          <label>Actual minutes
            <input type="number" min={status === 'missed' ? 0 : 1} max="1440" step="1" required
              value={minutes} disabled={status === 'missed'} onChange={event => setMinutes(event.target.value)} />
          </label>
          <button type="submit">{saving ? 'Saving…' : 'Save'}</button>
          {session.completion && !session.completion.automatic && <button type="button" onClick={() => onSave(session.activity_id, null)}>Clear record</button>}
        </fieldset>
      </form>
    </li>
  )
}

export default function StudySessionLog() {
  const { data, date, today, loading, error, savingId, selectDate, refresh, save } = useStudySessions()
  const logged = data?.sessions.filter(item => item.completion && !item.completion.automatic) || []
  const automaticallyMissed = data?.sessions.filter(item => item.completion?.automatic).length || 0
  const minutes = logged.reduce((sum, item) => sum + item.completion.actual_minutes, 0)

  return (
    <section className="session-log" aria-labelledby="session-log-heading">
      <h3 id="session-log-heading">Study session log</h3>
      <p>Record what you completed and how long you spent. Each recurring session is tracked separately.</p>
      <p>Unrecorded sessions are marked Missed after their scheduled day ends in Auckland time. You can correct them later.</p>
      <div className="session-toolbar">
        <label>Session date
          <input type="date" value={date} max={today || undefined} disabled={savingId !== null}
            onChange={event => selectDate(event.target.value)} />
        </label>
        <button type="button" disabled={loading || savingId !== null} onClick={refresh}>Reload records</button>
      </div>
      {error && <p role="alert">{error}</p>}
      {loading ? <p role="status">Loading session records…</p> : data && <>
        <p role="status">{logged.length} of {data.sessions.length} sessions recorded · {minutes} actual minutes
          {automaticallyMissed > 0 && ` · ${automaticallyMissed} missed automatically`}</p>
        {data.sessions.length === 0 ? <p>No activities scheduled or recorded for this date.</p> :
          <ul className="session-list">{data.sessions.map(session => (
            <SessionForm key={`${date}-${session.activity_id}-${session.completion?.status}-${session.completion?.actual_minutes}`}
              session={session} date={date} busy={savingId !== null} saving={savingId === session.activity_id} onSave={save} />
          ))}</ul>}
      </>}
    </section>
  )
}
