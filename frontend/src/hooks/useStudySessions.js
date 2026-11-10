import { useEffect, useRef, useState } from 'react'

async function request(path, options = {}) {
  const response = await fetch(`/api/study-sessions${path}`, { cache: 'no-store', ...options })
  const data = response.status === 204 ? null : await response.json()
  if (!response.ok) throw new Error(typeof data?.detail === 'string' ? data.detail : 'Could not save the session record.')
  return data
}

export default function useStudySessions() {
  const [selectedDate, setSelectedDate] = useState('')
  const [data, setData] = useState(null)
  const [today, setToday] = useState('')
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')
  const [savingId, setSavingId] = useState(null)
  const [revision, setRevision] = useState(0)
  const active = useRef(false)
  const mutation = useRef(null)

  useEffect(() => {
    active.current = true
    return () => { active.current = false; mutation.current?.abort() }
  }, [])

  useEffect(() => {
    const controller = new AbortController()
    request(selectedDate ? `?session_date=${selectedDate}` : '', { signal: controller.signal })
      .then(result => {
        if (!controller.signal.aborted) { setData(result); setToday(result.today) }
      })
      .catch(failure => { if (!controller.signal.aborted) setError(failure.message) })
      .finally(() => { if (!controller.signal.aborted) setLoading(false) })
    return () => controller.abort()
  }, [selectedDate, revision])

  function selectDate(value) {
    if (mutation.current || !value || value === (selectedDate || data?.date)) return
    setError('')
    setData(null)
    setLoading(true)
    setSelectedDate(value)
  }

  function refresh() {
    if (mutation.current) return
    setError('')
    setData(null)
    setLoading(true)
    setRevision(value => value + 1)
  }

  async function save(activityId, completion) {
    if (!active.current || mutation.current || loading || !data) return
    const controller = new AbortController()
    mutation.current = controller
    setSavingId(activityId)
    setError('')
    try {
      const saved = await request(`/${activityId}/${data.date}`, {
        method: completion ? 'PUT' : 'DELETE', signal: controller.signal,
        ...(completion ? { headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(completion) } : {}),
      })
      if (!controller.signal.aborted && active.current) {
        if (completion) setData(current => ({ ...current,
          sessions: current.sessions.map(item => item.activity_id === activityId ? { ...item, completion: saved } : item),
        }))
        else { setData(null); setLoading(true); setRevision(value => value + 1) }
      }
    } catch (failure) {
      if (!controller.signal.aborted && active.current) setError(`${failure.message} Your changes are kept; retry Save or reload to check the saved record.`)
    } finally {
      mutation.current = null
      if (active.current) setSavingId(null)
    }
  }

  return { data, today, date: selectedDate || data?.date || '', loading, error, savingId, selectDate, refresh, save }
}
