import assert from 'node:assert/strict'
import test from 'node:test'
import { prepareCalendarActivities } from '../src/pages/calendarDisplay.js'

function quiz(overrides = {}) {
  return {
    id: 21,
    activityId: 21,
    calendarId: 'exam-21-2026-10-09',
    eventType: 'exam',
    name: 'Quiz 9 Functions 2 [MATHS 102]',
    category: 'Canvas',
    subject: 'MATHS 102',
    activityType: 'one_time',
    calendarDate: '2026-10-09',
    startTime: null,
    endTime: null,
    ...overrides,
  }
}

test('four identical date-only quiz rows display as one block without fake times', () => {
  const rows = [21, 46, 71, 96].map((id) => quiz({
    id, activityId: id, calendarId: `exam-${id}-2026-10-09`,
  }))
  const displayed = prepareCalendarActivities(rows)
  assert.equal(displayed.length, 1)
  assert.equal(displayed[0].id, 21)
  assert.equal(displayed[0].startTime, null)
  assert.equal(displayed[0].endTime, null)
})

test('identical timed exam copies display once and preserve their time range', () => {
  const first = quiz({ startTime: '09:00', endTime: '11:15' })
  const duplicate = { ...first, id: 46, activityId: 46 }
  assert.deepEqual(prepareCalendarActivities([first, duplicate]), [first])
})

test('different dates or exam data are never collapsed just because the colour matches', () => {
  for (const difference of [
    { calendarDate: '2026-10-10' },
    { name: 'Quiz 10 Functions' },
    { subject: 'MATHS 108' },
    { category: 'University' },
    { activityType: 'daily' },
    { startTime: '10:00' },
    { endTime: '11:00' },
    { startTime: '10:00', endTime: '11:00' },
  ]) {
    const displayed = prepareCalendarActivities([quiz(), quiz({ id: 46, activityId: 46, ...difference })])
    assert.equal(displayed.length, 2, JSON.stringify(difference))
  }
})

test('an activity and an exam are kept separate even when all other fields match', () => {
  const displayed = prepareCalendarActivities([quiz(), quiz({ eventType: 'activity' })])
  assert.equal(displayed.length, 2)
})

test('separate editable activity IDs are not collapsed', () => {
  const first = quiz({ eventType: 'activity', startTime: '09:00', endTime: '10:00' })
  const second = { ...first, id: 46, activityId: 46 }
  assert.equal(prepareCalendarActivities([first, second]).length, 2)
})

test('contiguous ranges for the same activity still merge into the full duration', () => {
  const rows = [
    quiz({ eventType: 'activity', startTime: '11:00', endTime: '12:00' }),
    quiz({ eventType: 'activity', startTime: '09:00', endTime: '10:00' }),
    quiz({ eventType: 'activity', startTime: '10:00', endTime: '11:00' }),
  ]
  const displayed = prepareCalendarActivities(rows)
  assert.equal(displayed.length, 1)
  assert.equal(displayed[0].startTime, '09:00')
  assert.equal(displayed[0].endTime, '12:00')
})

test('time gaps and different days still prevent adjacent merging', () => {
  const rows = [
    quiz({ eventType: 'activity', startTime: '09:00', endTime: '10:00' }),
    quiz({ eventType: 'activity', startTime: '10:30', endTime: '11:00' }),
    quiz({ eventType: 'activity', calendarDate: '2026-10-10', startTime: '10:00', endTime: '11:00' }),
  ]
  assert.equal(prepareCalendarActivities(rows).length, 3)
})

test('date-only activities and incomplete exam identities are preserved', () => {
  for (const overrides of [
    { eventType: 'activity' },
    { name: '' },
    { calendarDate: null },
  ]) {
    assert.equal(prepareCalendarActivities([quiz(overrides), quiz(overrides)]).length, 2)
  }
})

test('display preprocessing never changes the fetched records', () => {
  const rows = [
    quiz(), quiz({ id: 46, activityId: 46 }),
    quiz({ eventType: 'activity', startTime: '09:00', endTime: '10:00' }),
    quiz({ eventType: 'activity', startTime: '10:00', endTime: '11:00' }),
  ]
  const original = structuredClone(rows)
  rows.forEach(Object.freeze)
  Object.freeze(rows)
  prepareCalendarActivities(rows)
  assert.deepEqual(rows, original)
})

test('an empty calendar remains empty', () => {
  assert.deepEqual(prepareCalendarActivities([]), [])
})
