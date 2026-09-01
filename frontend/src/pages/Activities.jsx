import { useEffect, useState } from 'react'
import './Activities.css'

function formatActivities(data) {
  return data.map((activity) => ({
    id: activity[0],
    name: activity[1],
    category: activity[2],
    subject: activity[3],
    date: activity[4],
    startTime: activity[5],
    endTime: activity[6],
  }))
}

function Activities() {
  const [activities, setActivities] = useState([])
  const [currentActivities, setCurrentActivities] = useState([])
  const [isLoading, setIsLoading] = useState(true)
  const [error, setError] = useState('')

  useEffect(() => {
    const controller = new AbortController()

    async function loadActivities() {
      try {
        const [todayResponse, currentResponse] = await Promise.all([
          fetch('/api/activities/today', { signal: controller.signal }),
          fetch('/api/activities/current', { signal: controller.signal }),
        ])

        if (!todayResponse.ok || !currentResponse.ok) {
          throw new Error('The server could not load the activities.')
        }

        const todayData = await todayResponse.json()
        const currentData = await currentResponse.json()

        setActivities(formatActivities(todayData))
        setCurrentActivities(formatActivities(currentData))
      } catch (requestError) {
        if (requestError.name !== 'AbortError') {
          setError('Could not load today\'s activities.')
        }
      } finally {
        if (!controller.signal.aborted) {
          setIsLoading(false)
        }
      }
    }

    loadActivities()

    return () => controller.abort()
  }, [])

  return (
    <main className="page">
      <h2>Activities</h2>

      {isLoading && <p>Loading activities...</p>}

      {error && <p role="alert">{error}</p>}

      {!isLoading && !error && (
        <>
          <section className="activities-section" aria-labelledby="current-activities-heading">
            <h3 id="current-activities-heading">Activities Due Now</h3>

            {currentActivities.length === 0 ? (
              <p>No activities due now.</p>
            ) : (
              <ul className="activities-list">
                {currentActivities.map((activity) => (
                  <li className="activities-card" key={activity.id}>
                    <div>
                      <h4>{activity.name}</h4>
                      {activity.category && <p>Category: {activity.category}</p>}
                      {activity.subject && <p>Subject: {activity.subject}</p>}
                    </div>
                    <p className="activities-time">
                      {activity.startTime} – {activity.endTime}
                    </p>
                  </li>
                ))}
              </ul>
            )}
          </section>

          <section className="activities-section" aria-labelledby="activities-heading">
            <h3 id="activities-heading">Today's Activities</h3>

            {activities.length === 0 ? (
              <p>No activities scheduled for today.</p>
            ) : (
              <ul className="activities-list">
                {activities.map((activity) => (
                  <li className="activities-card" key={activity.id}>
                    <div>
                      <h4>{activity.name}</h4>
                      {activity.category && <p>Category: {activity.category}</p>}
                      {activity.subject && <p>Subject: {activity.subject}</p>}
                      {activity.date && <p>Date: {activity.date}</p>}
                    </div>
                    <p className="activities-time">
                      {activity.startTime} – {activity.endTime}
                    </p>
                  </li>
                ))}
              </ul>
            )}
          </section>
        </>
      )}
    </main>
  )
}

export default Activities
