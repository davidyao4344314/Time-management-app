function removeDuplicateExamBlocks(activities) {
  const seenExams = new Set()

  return activities.filter((activity) => {
    // Keep editable activities separate: their IDs are used for edits and moves.
    if (activity.eventType !== 'exam' || !activity.calendarDate || !activity.name) {
      return true
    }

    // Match the exam data, not the row ID or import metadata. This also works
    // for date-only quizzes, whose start/end times are both null.
    const key = JSON.stringify([
      activity.calendarDate,
      activity.name,
      activity.category,
      activity.subject,
      activity.activityType,
      activity.startTime,
      activity.endTime,
    ])
    if (seenExams.has(key)) return false
    seenExams.add(key)
    return true
  })
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

export function prepareCalendarActivities(activities) {
  return mergeAdjacentActivities(removeDuplicateExamBlocks(activities))
}
