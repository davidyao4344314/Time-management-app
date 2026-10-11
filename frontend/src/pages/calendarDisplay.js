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

export function timeToMinutes(time) {
  if (typeof time !== 'string' || !/^(?:[01]\d|2[0-3]):[0-5]\d$/.test(time)) return null
  const [hour, minute] = time.split(':').map(Number)
  return hour * 60 + minute
}

export function hasTimeRange(activity) {
  const start = timeToMinutes(activity.startTime)
  const end = timeToMinutes(activity.endTime)
  return start !== null && end !== null && start < end
}

// Allocate visual lanes within overlapping groups, without altering occurrences.
export function layoutCalendarDay(activities) {
  const prepared = prepareCalendarActivities(activities)
  const untimed = prepared.filter(activity => !hasTimeRange(activity))
  const timed = prepared.filter(hasTimeRange).map(activity => ({ ...activity }))
    .sort((a, b) => a.startTime.localeCompare(b.startTime) || a.endTime.localeCompare(b.endTime))
  let group = [], laneEnds = [], groupEnd = -1
  function finishGroup() {
    for (const activity of group) activity.laneCount = laneEnds.length
    group = []; laneEnds = []; groupEnd = -1
  }
  for (const activity of timed) {
    const start = timeToMinutes(activity.startTime), end = timeToMinutes(activity.endTime)
    if (start >= groupEnd) finishGroup()
    let lane = laneEnds.findIndex(laneEnd => laneEnd <= start)
    if (lane === -1) lane = laneEnds.length
    laneEnds[lane] = end
    activity.lane = lane
    group.push(activity)
    groupEnd = Math.max(groupEnd, end)
  }
  finishGroup()
  return { timed, untimed }
}
