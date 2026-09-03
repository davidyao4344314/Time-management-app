import { useEffect, useState } from 'react'
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
  const [hoursPart, minutesPart] = time.split(':').map(Number)

  return hoursPart * 60 + minutesPart
}

function CalendarActivity({ activity, onDragStart }) {
  const startMinutes = timeToMinutes(activity.startTime)
  const endMinutes = timeToMinutes(activity.endTime)
  const top = (startMinutes / minutesPerDay) * 100
  const height = ((endMinutes - startMinutes) / minutesPerDay) * 100

  return (
    <article
      className="calendar-activity"
      draggable
      onDragStart={(event) => onDragStart(event, activity.calendarId)}
      style={{
        top: `${top}%`,
        height: `${height}%`,
      }}
    >
      <h4>{activity.name}</h4>
      <p>{activity.startTime} – {activity.endTime}</p>
    </article>
  )
}

function CalendarDay({ day, activities, onDragStart, onDrop }) {
  const orderedActivities = [...activities].sort((first, second) =>
    first.startTime.localeCompare(second.startTime),
  )

  return (
    <section
      aria-label={`${day.name}, ${day.dateLabel}`}
      className="calendar-day-timeline"
      onDragOver={(event) => event.preventDefault()}
      onDrop={(event) => onDrop(event, day)}
    >
      {orderedActivities.map((activity) => (
        <CalendarActivity
          activity={activity}
          key={activity.calendarId}
          onDragStart={onDragStart}
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
      <h2>Calendar</h2>

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
