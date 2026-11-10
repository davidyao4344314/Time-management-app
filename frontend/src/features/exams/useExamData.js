import { useEffect, useState } from 'react'

export async function fetchExams(signal) {
  const response = await fetch('/api/exams', { signal })

  if (!response.ok) {
    throw new Error('The server could not load the exams.')
  }

  return response.json()
}

export async function fetchExamsByName(examName) {
  const response = await fetch(
    `/api/exams/search?name=${encodeURIComponent(examName)}`,
  )

  if (!response.ok) {
    const responseBody = await response.json()
    const errorMessage = typeof responseBody.detail === 'string'
      ? responseBody.detail
      : 'Could not search for exams.'

    throw new Error(errorMessage)
  }

  return response.json()
}

export default function useExamData() {
  const [exams, setExams] = useState([])
  const [isLoading, setIsLoading] = useState(true)
  const [loadError, setLoadError] = useState('')

  useEffect(() => {
    const controller = new AbortController()

    async function loadExams() {
      try {
        setExams(await fetchExams(controller.signal))
      } catch (requestError) {
        if (requestError.name !== 'AbortError') {
          setLoadError('Could not load the exams.')
        }
      } finally {
        if (!controller.signal.aborted) {
          setIsLoading(false)
        }
      }
    }

    loadExams()

    return () => controller.abort()
  }, [])

  return { exams, setExams, isLoading, loadError }
}
