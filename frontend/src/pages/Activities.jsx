import { useEffect, useState } from 'react'
import './Activities.css'

function Activities() {
  const [activities, setActivities] = useState([])
  const [isLoading, setIsLoading] = useState(true)
  const [error, setError] = useState('')

  useEffect(() => {
    const controller = new AbortController()

    async function loadActivities() {
      try {
        const response = await fetch('/api/activities/today', {
          signal: controller.signal,
        })

        if (!response.ok) {
          throw new Error('The server could not load the activities.')
        }

        const data = await response.json()
        const formattedActivities = data.map((activity) => ({
          id: activity[0],
          name: activity[1],
          category: activity[2],
          subject: activity[3],
          date: activity[4],
          startTime: activity[5],
          endTime: activity[6],
        }))

        setActivities(formattedActivities)
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

      <section className="activities-section" aria-labelledby="activities-heading">
        <h3 id="activities-heading">Today's Activities</h3>

        {isLoading && <p>Loading activities...</p>}

        {error && <p role="alert">{error}</p>}

        {!isLoading && !error && activities.length === 0 && (
          <p>No activities scheduled for today.</p>
        )}

        {!isLoading && !error && activities.length > 0 && (
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
    </main>
  )
}

export default Activities
