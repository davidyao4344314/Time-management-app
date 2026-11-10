import { useEffect, useState } from 'react'

function formatActivities(data) {
  return data.map((activity) => ({
    id: activity.id,
    name: activity.name,
    category: activity.category,
    source: activity.source,
    subject: activity.subject,
    activityType: activity.activity_type,
    date: activity.date,
    weekday: activity.weekday,
    startTime: activity.start_time,
    endTime: activity.end_time,
  }))
}

function formatWeeklyActivities(data) {
  return data.map((activity) => ({
    calendarId: `${activity.id}-${activity.calendar_date}`,
    id: activity.id,
    name: activity.name,
    category: activity.category,
    subject: activity.subject,
    activityType: activity.activity_type,
    date: activity.calendar_date,
    startTime: activity.start_time,
    endTime: activity.end_time,
  }))
}

export async function fetchActivityData(signal) {
  const responses = await Promise.all([
    fetch('/api/activities', { signal }),
    fetch('/api/activities/today', { signal }),
    fetch('/api/activities/current', { signal }),
    fetch('/api/activities/week', { signal }),
  ])

  if (responses.some((response) => !response.ok)) {
    throw new Error('The server could not load the activities.')
  }

  const [allData, todayData, currentData, weekData] = await Promise.all(
    responses.map((response) => response.json()),
  )

  return {
    allActivities: formatActivities(allData),
    todayActivities: formatActivities(todayData),
    currentActivities: formatActivities(currentData),
    weeklyActivities: formatWeeklyActivities(weekData),
  }
}

export async function fetchActivitiesByName(activityName) {
  const response = await fetch(
    `/api/activities/search?name=${encodeURIComponent(activityName)}`,
  )

  if (!response.ok) {
    const responseBody = await response.json()
    const errorMessage = typeof responseBody.detail === 'string'
      ? responseBody.detail
      : 'Could not search for activities.'

    throw new Error(errorMessage)
  }

  return formatActivities(await response.json())
}

export default function useActivityData() {
  const [allActivities, setAllActivities] = useState([])
  const [todayActivities, setTodayActivities] = useState([])
  const [currentActivities, setCurrentActivities] = useState([])
  const [weeklyActivities, setWeeklyActivities] = useState([])
  const [isLoading, setIsLoading] = useState(true)
  const [loadError, setLoadError] = useState('')

  function updateActivityLists(activityData) {
    setAllActivities(activityData.allActivities)
    setTodayActivities(activityData.todayActivities)
    setCurrentActivities(activityData.currentActivities)
    setWeeklyActivities(activityData.weeklyActivities)
  }

  useEffect(() => {
    const controller = new AbortController()

    async function loadActivities() {
      try {
        const activityData = await fetchActivityData(controller.signal)
        updateActivityLists(activityData)
      } catch (requestError) {
        if (requestError.name !== 'AbortError') {
          setLoadError('Could not load the activities.')
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

  return { allActivities, todayActivities, currentActivities, weeklyActivities, isLoading, loadError, updateActivityLists }
}
