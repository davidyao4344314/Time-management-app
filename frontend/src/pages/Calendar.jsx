import { useEffect, useRef, useState } from 'react'
import UoaTimetableImport from '../components/UoaTimetableImport'
import ActivityEditModal from '../components/ActivityEditModal'
import './Calendar.css'

const dayNames = [
  'Monday',
  'Tuesday',
  'Wednesday',
  'Thursday',
  'Friday',
  'Saturday',
  'Sunday',
]

const hours = Array.from({ length: 24 }, (_, hour) => hour)
const minutesPerDay = 24 * 60

function isValidCanvasUrl(value) {
  try {
    const url = new URL(value.trim())
    return url.protocol === 'https:'
      && url.pathname.toLowerCase().endsWith('.ics')
      && !url.username
      && !url.password
      && !url.hash
      && !/\s/.test(value.trim())
  } catch {
    return false
  }
}

function formatDate(date) {
  const year = date.getFullYear()
  const month = String(date.getMonth() + 1).padStart(2, '0')
  const day = String(date.getDate()).padStart(2, '0')

  return `${year}-${month}-${day}`
}

function getCurrentMonday() {
  const today = new Date()
  const monday = new Date(today)
  const daysSinceMonday = today.getDay() === 0 ? 6 : today.getDay() - 1

  monday.setDate(today.getDate() - daysSinceMonday)
  monday.setHours(12, 0, 0, 0)
  return monday
}

function createCalendarDays(start, count) {
  return Array.from({ length: count }, (_, index) => {
    const date = new Date(start)
    date.setDate(start.getDate() + index)

    return {
      name: dayNames[(date.getDay() + 6) % 7],
      date: formatDate(date),
      dateLabel: date.toLocaleDateString(undefined, {
        month: 'short',
        day: 'numeric',
      }),
    }
  })
}

function formatWeeklyActivities(data) {
  return data.map((activity) => ({
    calendarId: `${activity.event_type === 'exam' ? 'exam' : 'activity'}-${activity.id}-${activity.calendar_date}`,
    eventType: activity.event_type === 'exam' ? 'exam' : 'activity',
    id: activity.id,
    activityId: activity.activity_id ?? activity.id,
    name: activity.name,
    subject: activity.subject,
    category: activity.category,
    activityType: activity.activity_type,
    calendarDate: activity.calendar_date,
    startTime: activity.start_time,
    endTime: activity.end_time,
  }))
}

async function fetchActivitiesForWeek(weekStart, signal) {
  const response = await fetch(`/api/activities/week?week_start=${weekStart}&include_exams=true`, { signal })
  if (!response.ok) throw new Error('The server could not load the calendar activities.')
  return formatWeeklyActivities(await response.json())
}

function timeToMinutes(time) {
  if (typeof time !== 'string') {
    return null
  }

  const [hoursPart, minutesPart] = time.split(':').map(Number)

  if (!Number.isFinite(hoursPart) || !Number.isFinite(minutesPart)) {
    return null
  }

  return hoursPart * 60 + minutesPart
}

function formatTimeRange(startTime, endTime) {
  if (!startTime && !endTime) {
    return 'No time set'
  }

  return `${startTime || 'No start time'} – ${endTime || 'No end time'}`
}

function CalendarActivity({ activity, onDragStart, onEdit, untimedIndex }) {
  const wasDragged = useRef(false)
  const canEdit = activity.eventType !== 'exam'
  const startMinutes = timeToMinutes(activity.startTime)
  const endMinutes = timeToMinutes(activity.endTime)
  const hasTimeRange = (
    startMinutes !== null
    && endMinutes !== null
    && startMinutes < endMinutes
  )
  const position = hasTimeRange
    ? {
        top: `${(startMinutes / minutesPerDay) * 100}%`,
        height: `${((endMinutes - startMinutes) / minutesPerDay) * 100}%`,
      }
    : {
        top: `${0.25 + untimedIndex * 3.25}rem`,
        height: '3rem',
      }

  return (
    <article
      className="calendar-activity"
      data-event-type={activity.eventType}
      draggable={activity.eventType !== 'exam'}
      role={canEdit ? 'button' : undefined}
      tabIndex={canEdit ? 0 : undefined}
      aria-label={canEdit ? `Edit ${activity.name}` : undefined}
      onPointerDown={() => { wasDragged.current = false }}
      onDragStart={(event) => {
        wasDragged.current = true
        onDragStart(event, activity.calendarId)
      }}
      onClick={() => {
        if (canEdit && !wasDragged.current) onEdit(activity)
      }}
      onKeyDown={(event) => {
        if (canEdit && (event.key === 'Enter' || event.key === ' ')) {
          event.preventDefault()
          onEdit(activity)
        }
      }}
      style={position}
    >
      <h4>{activity.name}</h4>
      <p>{formatTimeRange(activity.startTime, activity.endTime)}</p>
    </article>
  )
}

function mergeAdjacentActivities(activities) {
  const groups = new Map()
  const displayed = []
  const validTime = /^(?:[01]\d|2[0-3]):[0-5]\d$/

  for (const activity of activities) {
    // Untimed, incomplete and invalid ranges retain their existing display.
    if (!activity.calendarDate
      || !validTime.test(activity.startTime)
      || !validTime.test(activity.endTime)
      || activity.startTime >= activity.endTime) {
      displayed.push({ ...activity })
      continue
    }

    const originalId = activity.activityId ?? activity.id
    const identity = originalId != null
      ? ['id', originalId]
      : ['fields', activity.name, activity.subject, activity.category, activity.activityType]
    if (originalId == null && !activity.name) {
      displayed.push({ ...activity })
      continue
    }
    // Exam IDs and activity IDs belong to separate tables.
    const key = JSON.stringify([activity.calendarDate, activity.eventType, ...identity])
    if (!groups.has(key)) groups.set(key, [])
    groups.get(key).push(activity)
  }

  for (const group of groups.values()) {
    group.sort((first, second) => first.startTime.localeCompare(second.startTime)
      || first.endTime.localeCompare(second.endTime))
    let previous = null
    for (const activity of group) {
      if (previous && previous.endTime === activity.startTime) {
        previous.endTime = activity.endTime
      } else {
        // Only change display copies, never the fetched occurrences.
        previous = { ...activity }
        displayed.push(previous)
      }
    }
  }

  return displayed.sort((first, second) =>
    (first.startTime || '').localeCompare(second.startTime || ''),
  )
}

function CalendarDay({ day, isToday, activities, onDragStart, onDrop, onEdit }) {
  const orderedActivities = mergeAdjacentActivities(activities)

  return (
    <section
      aria-label={`${day.name}, ${day.dateLabel}`}
      className={`calendar-day-timeline${isToday ? ' calendar-today' : ''}`}
      onDragOver={(event) => event.preventDefault()}
      onDrop={(event) => onDrop(event, day)}
    >
      {orderedActivities.map((activity, index) => (
        <CalendarActivity
          activity={activity}
          key={`${activity.calendarId}-${activity.startTime}-${activity.endTime}-${index}`}
          onDragStart={onDragStart}
          onEdit={onEdit}
          untimedIndex={index}
        />
      ))}
    </section>
  )
}

function Calendar() {
  const today = formatDate(new Date())
  const [selectedWeek, setSelectedWeek] = useState(() => formatDate(getCurrentMonday()))
  const selectedWeekRef = useRef(selectedWeek)
  const weekDays = createCalendarDays(new Date(`${selectedWeek}T12:00:00`), 7)
  const [activities, setActivities] = useState([])
  const [isLoading, setIsLoading] = useState(true)
  const [error, setError] = useState('')
  const [moveError, setMoveError] = useState('')
  const [editingActivity, setEditingActivity] = useState(null)
  const [isLoadingEdit, setIsLoadingEdit] = useState(false)
  const [editError, setEditError] = useState('')
  const [editMessage, setEditMessage] = useState('')
  const editRequest = useRef(null)
  const [isCheckingCanvas, setIsCheckingCanvas] = useState(false)
  const [isCanvasModalOpen, setIsCanvasModalOpen] = useState(false)
  const [canvasUrl, setCanvasUrl] = useState('')
  const [canvasMessage, setCanvasMessage] = useState('')
  const [isImportingCanvas, setIsImportingCanvas] = useState(false)
  const [canvasError, setCanvasError] = useState('')
  const [isClearDuplicatesOpen, setIsClearDuplicatesOpen] = useState(false)
  const [isRemovingDuplicates, setIsRemovingDuplicates] = useState(false)
  const [duplicateMessage, setDuplicateMessage] = useState('')
  const [duplicateError, setDuplicateError] = useState('')

  async function fetchWeeklyActivities(signal) {
    // Refresh the visible week even if navigation happened during an import.
    let requestedWeek
    let result
    do {
      requestedWeek = selectedWeekRef.current
      result = await fetchActivitiesForWeek(requestedWeek, signal)
    } while (requestedWeek !== selectedWeekRef.current)
    return result
  }

  function selectWeek(weekStart) {
    if (weekStart === selectedWeekRef.current) return
    selectedWeekRef.current = weekStart
    setSelectedWeek(weekStart)
    setActivities([])
    setIsLoading(true)
    setError('')
    setMoveError('')
  }

  function moveWeek(offset) {
    // Calendar-day arithmetic keeps Monday correct across daylight saving.
    const monday = new Date(`${selectedWeekRef.current}T12:00:00`)
    monday.setDate(monday.getDate() + offset)
    selectWeek(formatDate(monday))
  }

  useEffect(() => {
    const controller = new AbortController()

    async function loadWeeklyActivities() {
      try {
        const weeklyActivities = await fetchActivitiesForWeek(selectedWeek, controller.signal)
        if (!controller.signal.aborted && selectedWeek === selectedWeekRef.current) {
          setActivities(weeklyActivities)
        }
      } catch {
        if (!controller.signal.aborted && selectedWeek === selectedWeekRef.current) {
          setError('Could not load the weekly activities.')
        }
      } finally {
        if (!controller.signal.aborted && selectedWeek === selectedWeekRef.current) {
          setIsLoading(false)
        }
      }
    }

    loadWeeklyActivities()

    return () => controller.abort()
  }, [selectedWeek])

  useEffect(() => () => editRequest.current?.abort(), [])

  async function openCalendarEdit(activity) {
    if (activity.eventType === 'exam') return
    editRequest.current?.abort()
    const controller = new AbortController()
    editRequest.current = controller
    setIsLoadingEdit(true)
    setEditError('')
    setEditMessage('')
    try {
      // Fetch the original row: a merged display block may have different times.
      const response = await fetch('/api/activities', { signal: controller.signal })
      if (!response.ok) throw new Error('Could not load the activity for editing.')
      const rows = await response.json()
      if (controller.signal.aborted) return
      const row = rows.find((item) => item.id === (activity.activityId ?? activity.id))
      if (!row) throw new Error('This activity no longer exists. Refresh the Calendar.')
      setEditingActivity({
        id: row.id, name: row.name, category: row.category, subject: row.subject,
        activityType: row.activity_type, date: row.date, weekday: row.weekday,
        startTime: row.start_time, endTime: row.end_time, source: row.source,
      })
    } catch (requestError) {
      if (!controller.signal.aborted) setEditError(requestError.message)
    } finally {
      if (!controller.signal.aborted) setIsLoadingEdit(false)
    }
  }

  async function handleCalendarEditSaved() {
    setEditMessage('Activity updated.')
    try {
      setActivities(await fetchWeeklyActivities())
      setError('')
    } catch {
      setEditError('The edit was saved, but the calendar could not refresh. Reload the page.')
    }
  }

  function handleDragStart(event, calendarId) {
    event.dataTransfer.setData('text/plain', calendarId)
    event.dataTransfer.effectAllowed = 'move'
  }

  async function handleCanvasImportClick() {
    if (isCheckingCanvas || isImportingCanvas) return

    setIsCheckingCanvas(true)
    setCanvasMessage('')
    setCanvasError('')

    try {
      const response = await fetch('/api/canvas/status')

      if (!response.ok) {
        throw new Error('Could not check the Canvas configuration.')
      }

      const status = await response.json()

      if (status.configured) {
        await importCanvas()
      } else {
        setIsCanvasModalOpen(true)
      }
    } catch (requestError) {
      setCanvasError(requestError.message)
    } finally {
      setIsCheckingCanvas(false)
    }
  }

  async function importCanvas(calendarUrl = null) {
    if (isImportingCanvas) return

    setIsImportingCanvas(true)
    setCanvasMessage('Importing from Canvas...')
    setCanvasError('')

    try {
      const response = await fetch('/api/canvas/import', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ calendar_url: calendarUrl }),
      })

      if (!response.ok) {
        const result = await response.json().catch(() => ({}))
        throw new Error(typeof result.detail === 'string'
          ? result.detail
          : 'Canvas import failed. Please try again.')
      }

      setIsCanvasModalOpen(false)
      setCanvasUrl('')
      setCanvasMessage('Canvas import completed.')

      try {
        setActivities(await fetchWeeklyActivities())
        setError('')
        // Activities and Exams already refetch when opened through navigation.
      } catch {
        setCanvasError('The import was saved, but the calendar could not refresh. Reload the page to see it.')
      }
    } catch (requestError) {
      setCanvasMessage('')
      setCanvasError(requestError instanceof TypeError
        ? 'Could not reach the backend. Check that it is running.'
        : requestError.message)
    } finally {
      setIsImportingCanvas(false)
    }
  }

  function handleCanvasSubmit(event) {
    event.preventDefault()
    if (isValidCanvasUrl(canvasUrl)) {
      importCanvas(canvasUrl.trim())
    }
  }

  function closeCanvasModal() {
    if (isImportingCanvas) return
    setIsCanvasModalOpen(false)
    setCanvasUrl('')
    setCanvasError('')
  }

  async function handleClearDuplicates() {
    if (isRemovingDuplicates) return
    setIsRemovingDuplicates(true)
    setDuplicateMessage('Removing duplicate activities...')
    setDuplicateError('')

    try {
      const response = await fetch('/api/activities/remove-duplicates', { method: 'POST' })
      const result = await response.json().catch(() => ({}))
      if (!response.ok) {
        throw new Error(typeof result.detail === 'string'
          ? result.detail : 'Could not remove duplicate activities. Please try again.')
      }

      setIsClearDuplicatesOpen(false)
      setDuplicateMessage(`Removed ${result.number_removed} duplicate activities.`)
      try {
        setActivities(await fetchWeeklyActivities())
        setError('')
        // The Activities page also refetches when opened through navigation.
      } catch {
        setDuplicateError('Duplicates were removed, but the calendar could not refresh. Reload the page to see the changes.')
      }
    } catch (requestError) {
      setDuplicateMessage('')
      setDuplicateError(requestError instanceof TypeError
        ? 'Could not reach the backend. Check that it is running.'
        : requestError.message)
    } finally {
      setIsRemovingDuplicates(false)
    }
  }

  async function handleDrop(event, destinationDay) {
    event.preventDefault()

    const calendarId = event.dataTransfer.getData('text/plain')
    const activity = activities.find(
      (calendarActivity) => calendarActivity.calendarId === calendarId,
    )

    if (!activity || activity.eventType === 'exam') {
      return
    }

    setMoveError('')

    try {
      const response = await fetch(`/api/activities/${activity.id}/move`, {
        method: 'PUT',
        headers: {
          'Content-Type': 'application/json',
        },
        body: JSON.stringify({
          activity_id: activity.id,
          activity_type: activity.activityType,
          destination_date: destinationDay.date,
          destination_weekday: destinationDay.name,
        }),
      })

      if (!response.ok) {
        const responseBody = await response.json()
        throw new Error(responseBody.detail || 'Could not save the calendar change.')
      }

      const refreshedActivities = await fetchWeeklyActivities()
      setActivities(refreshedActivities)
    } catch (requestError) {
      setMoveError(requestError.message)
    }
  }

  return (
    <main className="page">
      <div className="calendar-heading-row">
        <h2>Calendar</h2>
        <div className="calendar-import-actions" role="group" aria-label="Calendar week navigation">
          <button type="button" onClick={() => moveWeek(-7)}>Previous Week</button>
          <button type="button" onClick={() => selectWeek(formatDate(getCurrentMonday()))}>Today</button>
          <button type="button" onClick={() => moveWeek(7)}>Next Week</button>
        </div>
        <div className="calendar-import-actions">
        <button
          disabled={isCheckingCanvas || isImportingCanvas}
          onClick={handleCanvasImportClick}
          type="button"
        >
          {isImportingCanvas
            ? 'Importing from Canvas...'
            : isCheckingCanvas ? 'Checking...' : 'Import from Canvas'}
        </button>
        <UoaTimetableImport onImported={async () => {
          setActivities(await fetchWeeklyActivities())
          setError('')
        }} />
        <button
          type="button"
          disabled={isRemovingDuplicates}
          onClick={() => {
            setDuplicateMessage('')
            setDuplicateError('')
            setIsClearDuplicatesOpen(true)
          }}
        >
          {isRemovingDuplicates ? 'Removing duplicate activities...' : 'Clear Duplicate Activities'}
        </button>
        </div>
      </div>

      {!isCanvasModalOpen && canvasMessage && <p role="status">{canvasMessage}</p>}
      {!isCanvasModalOpen && canvasError && <p role="alert">{canvasError}</p>}

      {!isClearDuplicatesOpen && duplicateMessage && <p role="status">{duplicateMessage}</p>}
      {!isClearDuplicatesOpen && duplicateError && <p role="alert">{duplicateError}</p>}

      {isClearDuplicatesOpen && (
        <div className="canvas-modal-overlay">
          <section
            className="canvas-modal"
            role="dialog"
            aria-modal="true"
            aria-labelledby="clear-duplicates-heading"
            aria-describedby="clear-duplicates-description"
          >
            <h3 id="clear-duplicates-heading">Remove duplicate activities?</h3>
            <p id="clear-duplicates-description">One copy of each activity will be kept. Extra copies will be permanently deleted.</p>
            {duplicateMessage && <p role="status">{duplicateMessage}</p>}
            {duplicateError && <p role="alert">{duplicateError}</p>}
            <div className="canvas-modal-actions">
              <button type="button" disabled={isRemovingDuplicates} onClick={() => setIsClearDuplicatesOpen(false)}>
                Cancel
              </button>
              <button type="button" disabled={isRemovingDuplicates} onClick={handleClearDuplicates}>
                {isRemovingDuplicates ? 'Removing duplicate activities...' : 'Clear Duplicates'}
              </button>
            </div>
          </section>
        </div>
      )}

      {isCanvasModalOpen && (
        <div className="canvas-modal-overlay">
          <form
            aria-labelledby="canvas-modal-heading"
            aria-modal="true"
            className="canvas-modal"
            onSubmit={handleCanvasSubmit}
            role="dialog"
          >
            <h3 id="canvas-modal-heading">Connect Canvas calendar</h3>
            <label>
              Canvas iCal feed URL
              <input
                autoComplete="off"
                disabled={isImportingCanvas}
                onChange={(event) => setCanvasUrl(event.target.value)}
                placeholder="Paste your Canvas iCal feed URL"
                required
                spellCheck={false}
                type="url"
                value={canvasUrl}
              />
            </label>
            <p>Your feed URL will be saved locally for future imports.</p>
            {canvasUrl.trim() && !isValidCanvasUrl(canvasUrl) && (
              <p>Enter an HTTPS Canvas iCal feed URL ending in .ics.</p>
            )}
            {canvasMessage && <p role="status">{canvasMessage}</p>}
            {canvasError && <p role="alert">{canvasError}</p>}
            <div className="canvas-modal-actions">
              {isValidCanvasUrl(canvasUrl) && (
                <button disabled={isImportingCanvas} type="submit">
                  {isImportingCanvas ? 'Importing from Canvas...' : 'Import from Canvas'}
                </button>
              )}
              <button disabled={isImportingCanvas} onClick={closeCanvasModal} type="button">Close</button>
            </div>
          </form>
        </div>
      )}

      <p aria-live="polite">{weekDays[0].date} – {weekDays[6].date}</p>
      {isLoading && <p role="status">Loading calendar...</p>}

      {error && <p role="alert">{error}</p>}

      {moveError && <p role="alert">{moveError}</p>}
      {isLoadingEdit && <p role="status">Loading activity for editing...</p>}
      {editError && <p role="alert">{editError}</p>}
      {editMessage && <p role="status">{editMessage}</p>}
      {editingActivity && (
        <ActivityEditModal key={editingActivity.id} activity={editingActivity}
          onClose={() => setEditingActivity(null)} onSaved={handleCalendarEditSaved} />
      )}

      {!isLoading && (
        <div className="calendar-scroll" key={selectedWeek} tabIndex={0} role="region" aria-label="Monday to Sunday calendar">
          <div className="calendar-layout" style={{ '--calendar-day-count': weekDays.length }}>
            <div className="calendar-corner" aria-hidden="true" />

            {weekDays.map((day) => (
              <header
                className={`calendar-day-header${day.date === today ? ' calendar-today' : ''}`}
                key={day.date}
              >
                <h3>{day.name}</h3>
                <time dateTime={day.date} aria-current={day.date === today ? 'date' : undefined}>
                  {day.dateLabel}
                </time>
              </header>
            ))}

            <div className="calendar-time-column" aria-hidden="true">
              {hours.map((hour) => (
                <span
                  className="calendar-time-label"
                  key={hour}
                  style={{ top: `${(hour / 24) * 100}%` }}
                >
                  {String(hour).padStart(2, '0')}:00
                </span>
              ))}
            </div>

            {weekDays.map((day) => (
              <CalendarDay
                activities={activities.filter(
                  (activity) => activity.calendarDate === day.date,
                )}
                day={day}
                isToday={day.date === today}
                key={day.date}
                onDragStart={handleDragStart}
                onDrop={handleDrop}
                onEdit={openCalendarEdit}
              />
            ))}
          </div>
        </div>
      )}
    </main>
  )
}

export default Calendar
