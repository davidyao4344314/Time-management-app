import { useEffect, useState } from 'react'
import './Home.css'

function Home() {
  const [schedule, setSchedule] = useState(null)
  const [scheduleError, setScheduleError] = useState('')
  const [activities, setActivities] = useState(null)
  const [activitiesError, setActivitiesError] = useState('')

  useEffect(() => {
    let controller
    let stopped = false
    let fetching = false

    async function refreshSchedule() {
      if (fetching) return
      fetching = true
      controller = new AbortController()
      const signal = controller.signal
      async function loadToday() {
        try {
          const response = await fetch('/api/activities/today', { signal })
          if (!response.ok) throw new Error()
          const data = await response.json()
          if (!Array.isArray(data)) throw new Error()
          if (!stopped) { setActivities(data); setActivitiesError('') }
        } catch (error) {
          if (!stopped && error.name !== 'AbortError') setActivitiesError('Could not load today’s activities. Retrying every minute.')
        }
      }
      const todayRequest = loadToday()
      try {
        const response = await fetch('/api/activities/current-next', {
          signal: controller.signal,
        })
        if (!response.ok) throw new Error('Could not load current and next activities.')
        const data = await response.json()
        if (!stopped) {
          setSchedule(data)
          setScheduleError('')
        }
      } catch (error) {
        if (!stopped && error.name !== 'AbortError') {
          setScheduleError('Could not load current and next activities. Check the backend server; retrying every minute.')
        }
      } finally {
        await todayRequest
        fetching = false
      }
    }

    refreshSchedule()
    const interval = setInterval(refreshSchedule, 60_000)
    return () => {
      stopped = true
      clearInterval(interval)
      controller?.abort()
    }
  }, [])

  return (
    <main className="page">
      <h2>Home</h2>

      {scheduleError ? (
        <p role="alert">{scheduleError}</p>
      ) : !schedule ? (
        <p role="status">Loading current and next activities...</p>
      ) : (
        <>
          <section className="today-activities">
            <h3>Current Activity</h3>
            {schedule.current?.length ? (
              <ul className="activity-list">
                {schedule.current.map((activity) => (
                  <li className="activity-card" key={activity.id}>
                    <h4>{activity.name}</h4>
                    <p className="activity-time">Until {activity.end_time}</p>
                  </li>
                ))}
              </ul>
            ) : <p>No activity right now</p>}
          </section>

          <section className="today-activities">
            <h3>Next Activity</h3>
            {schedule.next ? (
              <div className="activity-card">
                <h4>{schedule.next.name}</h4>
                <p className="activity-time">Starts at {schedule.next.start_time}</p>
              </div>
            ) : <p>No more scheduled activities today</p>}
          </section>
        </>
      )}

      <section className="today-activities">
        <h3>Today's Activities</h3>

        {activitiesError ? <p role="alert">{activitiesError}</p> : activities === null ? (
          <p role="status">Loading today’s activities...</p>
        ) : activities.length === 0 ? (
          <p>No activities scheduled for today.</p>
        ) : (
          <ul className="activity-list">
            {activities.map((activity) => (
              <li className="activity-card" key={activity.id}>
                <div>
                  <h4>{activity.name}</h4>
                  {(activity.subject || activity.category) && <p>{activity.subject || activity.category}</p>}
                </div>
                <p className="activity-time">
                  {!activity.start_time && !activity.end_time ? 'No time set'
                    : `${activity.start_time || 'No start time'} – ${activity.end_time || 'No end time'}`}
                </p>
              </li>
            ))}
          </ul>
        )}
      </section>
    </main>
  )
}

export default Home
