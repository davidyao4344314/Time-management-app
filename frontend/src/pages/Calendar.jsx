import { useEffect, useState } from 'react'
import UoaTimetableImport from '../components/UoaTimetableImport'
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

function getCurrentWeek() {
  const today = new Date()
  const monday = new Date(today)
  const daysSinceMonday = today.getDay() === 0 ? 6 : today.getDay() - 1

  monday.setDate(today.getDate() - daysSinceMonday)

  return dayNames.map((name, index) => {
    const date = new Date(monday)
    date.setDate(monday.getDate() + index)

    return {
      name,
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
    calendarId: `${activity.id}-${activity.calendar_date}`,
    id: activity.id,
    name: activity.name,
    activityType: activity.activity_type,
    calendarDate: activity.calendar_date,
    startTime: activity.start_time,
    endTime: activity.end_time,
  }))
}

async function fetchWeeklyActivities(signal) {
  const response = await fetch('/api/activities/week', { signal })

  if (!response.ok) {
    throw new Error('The server could not load the weekly activities.')
  }

  const data = await response.json()

  return formatWeeklyActivities(data)
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

function CalendarActivity({ activity, onDragStart, untimedIndex }) {
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
      draggable
      onDragStart={(event) => onDragStart(event, activity.calendarId)}
      style={position}
    >
      <h4>{activity.name}</h4>
      <p>{formatTimeRange(activity.startTime, activity.endTime)}</p>
    </article>
  )
}

function CalendarDay({ day, activities, onDragStart, onDrop }) {
  const orderedActivities = [...activities].sort((first, second) =>
    (first.startTime || '').localeCompare(second.startTime || ''),
  )

  return (
    <section
      aria-label={`${day.name}, ${day.dateLabel}`}
      className="calendar-day-timeline"
      onDragOver={(event) => event.preventDefault()}
      onDrop={(event) => onDrop(event, day)}
    >
      {orderedActivities.map((activity, index) => (
        <CalendarActivity
          activity={activity}
          key={activity.calendarId}
          onDragStart={onDragStart}
          untimedIndex={index}
        />
      ))}
    </section>
  )
}

function Calendar() {
  const [weekDays] = useState(getCurrentWeek)
  const [activities, setActivities] = useState([])
  const [isLoading, setIsLoading] = useState(true)
  const [error, setError] = useState('')
  const [moveError, setMoveError] = useState('')
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

  useEffect(() => {
    const controller = new AbortController()

    async function loadWeeklyActivities() {
      try {
        const weeklyActivities = await fetchWeeklyActivities(controller.signal)
        setActivities(weeklyActivities)
      } catch (requestError) {
        if (requestError.name !== 'AbortError') {
          setError('Could not load the weekly activities.')
        }
      } finally {
        if (!controller.signal.aborted) {
          setIsLoading(false)
        }
      }
    }

    loadWeeklyActivities()

    return () => controller.abort()
  }, [])

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

    if (!activity) {
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

      {isLoading && <p>Loading calendar...</p>}

      {error && <p role="alert">{error}</p>}

      {moveError && <p role="alert">{moveError}</p>}

      {!isLoading && !error && (
        <div className="calendar-scroll">
          <div className="calendar-layout">
            <div className="calendar-corner" aria-hidden="true" />

            {weekDays.map((day) => (
              <header className="calendar-day-header" key={day.date}>
                <h3>{day.name}</h3>
                <time dateTime={day.date}>{day.dateLabel}</time>
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
                key={day.date}
                onDragStart={handleDragStart}
                onDrop={handleDrop}
              />
            ))}
          </div>
        </div>
      )}
    </main>
  )
}

export default Calendar
