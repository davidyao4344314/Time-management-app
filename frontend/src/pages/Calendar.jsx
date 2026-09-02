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
    calendarId: `${activity[0]}-${activity[7]}`,
    id: activity[0],
    name: activity[1],
    category: activity[2],
    subject: activity[3],
    startTime: activity[5],
    endTime: activity[6],
    scheduledDate: activity[7],
  }))
}

function CalendarDay({ day, activities, onDragStart, onDrop }) {
  return (
    <section
      className="calendar-day"
      onDragOver={(event) => event.preventDefault()}
      onDrop={(event) => onDrop(event, day.date)}
    >
      <header className="calendar-day-header">
        <h3>{day.name}</h3>
        <time dateTime={day.date}>{day.dateLabel}</time>
      </header>

      <div className="calendar-day-activities">
        {activities.length === 0 ? (
          <p className="calendar-empty">No activities</p>
        ) : (
          activities.map((activity) => (
            <article
              className="calendar-activity"
              draggable="true"
              key={activity.calendarId}
              onDragStart={(event) => onDragStart(event, activity.calendarId)}
            >
              <h4>{activity.name}</h4>
              <p>{activity.startTime} – {activity.endTime}</p>
              {activity.subject && <p>{activity.subject}</p>}
            </article>
          ))
        )}
      </div>
    </section>
  )
}

function Calendar() {
  const [weekDays] = useState(getCurrentWeek)
  const [activities, setActivities] = useState([])
  const [isLoading, setIsLoading] = useState(true)
  const [error, setError] = useState('')

  useEffect(() => {
    const controller = new AbortController()

    async function loadWeeklyActivities() {
      try {
        const response = await fetch('/api/activities/week', {
          signal: controller.signal,
        })

        if (!response.ok) {
          throw new Error('The server could not load the weekly activities.')
        }

        const data = await response.json()
        setActivities(formatWeeklyActivities(data))
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

  function handleDrop(event, newDate) {
    event.preventDefault()

    const calendarId = event.dataTransfer.getData('text/plain')

    setActivities((currentActivities) =>
      currentActivities.map((activity) =>
        activity.calendarId === calendarId
          ? { ...activity, scheduledDate: newDate }
          : activity,
      ),
    )
  }

  return (
    <main className="page">
      <h2>Calendar</h2>

      {isLoading && <p>Loading calendar...</p>}

      {error && <p role="alert">{error}</p>}

      {!isLoading && !error && (
        <div className="calendar-grid">
          {weekDays.map((day) => (
            <CalendarDay
              activities={activities.filter(
                (activity) => activity.scheduledDate === day.date,
              )}
              day={day}
              key={day.date}
              onDragStart={handleDragStart}
              onDrop={handleDrop}
            />
          ))}
        </div>
      )}
    </main>
  )
}

export default Calendar
