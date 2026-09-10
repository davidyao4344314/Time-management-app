import { useState } from 'react'
import '../pages/Activities.css'

const fieldLabels = {
  name: 'Name', category: 'Category', subject: 'Subject', activity_type: 'Activity type',
  date: 'Date', weekday: 'Weekday', start_time: 'Start time', end_time: 'End time',
}
const weekdays = ['Monday', 'Tuesday', 'Wednesday', 'Thursday', 'Friday', 'Saturday', 'Sunday']

export default function ActivityEditModal({ activity, onClose, onSaved }) {
  const values = {
    name: activity.name, category: activity.category, subject: activity.subject,
    activity_type: activity.activityType, date: activity.date, weekday: activity.weekday,
    start_time: activity.startTime, end_time: activity.endTime,
  }
  const [column, setColumn] = useState('name')
  const [value, setValue] = useState(activity.name || '')
  const [scheduleDate, setScheduleDate] = useState(activity.date || '')
  const [scheduleWeekday, setScheduleWeekday] = useState(activity.weekday || 'Monday')
  const [isSaving, setIsSaving] = useState(false)
  const [error, setError] = useState('')
  const fields = Object.keys(fieldLabels).filter((field) =>
    (field !== 'date' || activity.activityType === 'one_time')
    && (field !== 'weekday' || activity.activityType === 'weekly'),
  )

  function changeColumn(event) {
    const next = event.target.value
    setColumn(next)
    setValue(values[next] || (next === 'weekday' ? 'Monday' : ''))
    setError('')
  }

  async function save(event) {
    event.preventDefault()
    if (isSaving) return
    setIsSaving(true)
    setError('')
    let updated
    try {
      const body = { activity_id: activity.id, column_name: column, new_value: value || null }
      if (column === 'activity_type') {
        body.date = value === 'one_time' ? scheduleDate : null
        body.weekday = value === 'weekly' ? scheduleWeekday : null
      }
      const response = await fetch(`/api/activities/${activity.id}`, {
        method: 'PUT', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body),
      })
      const result = await response.json().catch(() => ({}))
      if (!response.ok) throw new Error(typeof result.detail === 'string' ? result.detail : 'Could not update the activity.')
      updated = result
    } catch (requestError) {
      setError(requestError instanceof TypeError ? 'Could not reach the backend. Your changes have not been cleared.' : requestError.message)
      setIsSaving(false)
      return
    }
    onClose()
    await onSaved(updated, column)
  }

  return (
    <div className="edit-activity-overlay">
      <form aria-labelledby="edit-activity-heading" aria-modal="true" className="add-activity-form edit-activity-form" onSubmit={save} role="dialog">
        <h3 id="edit-activity-heading">Edit {activity.name} (ID {activity.id})</h3>
        <p>Source: <strong>{activity.source || 'Manual'}</strong> (read-only)</p>
        {activity.source && activity.source !== 'Manual' && <p>Changes are saved locally only. The original feed is not changed.</p>}
        <div className="add-activity-fields">
          <label>Field to edit
            <select disabled={isSaving} value={column} onChange={changeColumn}>
              {fields.map((field) => <option key={field} value={field}>{fieldLabels[field]}</option>)}
            </select>
          </label>
          <div className="edit-current-value"><span>Current value</span><strong>{values[column] || 'Not set'}</strong></div>
          <label>New value
            {column === 'activity_type' ? (
              <select disabled={isSaving} value={value} onChange={(event) => setValue(event.target.value)}>
                <option value="daily">Daily</option><option value="one_time">One time</option><option value="weekly">Weekly</option>
              </select>
            ) : column === 'weekday' ? (
              <select disabled={isSaving} value={value} onChange={(event) => setValue(event.target.value)}>
                {weekdays.map((day) => <option key={day} value={day}>{day}</option>)}
              </select>
            ) : (
              <input disabled={isSaving} value={value} onChange={(event) => setValue(event.target.value)}
                required={!['subject', 'start_time', 'end_time'].includes(column)}
                type={column === 'date' ? 'date' : ['start_time', 'end_time'].includes(column) ? 'time' : 'text'} />
            )}
          </label>
          {column === 'activity_type' && value === 'one_time' && (
            <label>Date<input type="date" required disabled={isSaving} value={scheduleDate} onChange={(event) => setScheduleDate(event.target.value)} /></label>
          )}
          {column === 'activity_type' && value === 'weekly' && (
            <label>Weekday<select disabled={isSaving} value={scheduleWeekday} onChange={(event) => setScheduleWeekday(event.target.value)}>
              {weekdays.map((day) => <option key={day} value={day}>{day}</option>)}
            </select></label>
          )}
        </div>
        {error && <p role="alert">{error}</p>}
        <div className="add-activity-actions">
          <button disabled={isSaving} type="submit">{isSaving ? 'Saving...' : 'Save'}</button>
          <button disabled={isSaving} onClick={onClose} type="button">Cancel</button>
        </div>
      </form>
    </div>
  )
}
