import { useEffect, useState } from 'react'
import './Activities.css'

const emptyExamForm = {
  name: '',
  category: '',
  subject: '',
  date: '',
  start_time: '',
  end_time: '',
}

async function fetchExams(signal) {
  const response = await fetch('/api/exams', { signal })

  if (!response.ok) {
    throw new Error('The server could not load the exams.')
  }

  return response.json()
}

function Exams() {
  const [exams, setExams] = useState([])
  const [isLoading, setIsLoading] = useState(true)
  const [loadError, setLoadError] = useState('')
  const [isFormOpen, setIsFormOpen] = useState(false)
  const [examForm, setExamForm] = useState(emptyExamForm)
  const [isSaving, setIsSaving] = useState(false)
  const [saveError, setSaveError] = useState('')

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

  function handleFormChange(event) {
    const { name, value } = event.target

    setExamForm((currentForm) => ({
      ...currentForm,
      [name]: value,
    }))
  }

  function closeForm() {
    setIsFormOpen(false)
    setSaveError('')
    setExamForm(emptyExamForm)
  }

  async function handleSubmit(event) {
    event.preventDefault()
    setIsSaving(true)
    setSaveError('')

    try {
      const response = await fetch('/api/exams', {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
        },
        body: JSON.stringify({
          ...examForm,
          subject: examForm.subject || null,
        }),
      })

      if (!response.ok) {
        const responseBody = await response.json()
        const errorMessage = typeof responseBody.detail === 'string'
          ? responseBody.detail
          : 'Could not save the exam.'

        throw new Error(errorMessage)
      }

      setExams(await fetchExams())
      closeForm()
    } catch (requestError) {
      setSaveError(requestError.message)
    } finally {
      setIsSaving(false)
    }
  }

  return (
    <main className="page">
      <div className="activities-heading-row">
        <h2>Exams</h2>
        <button
          aria-expanded={isFormOpen}
          aria-label="Add exam"
          className="add-activity-button"
          onClick={() => setIsFormOpen(true)}
          type="button"
        >
          +
        </button>
      </div>

      {isFormOpen && (
        <form className="add-activity-form" onSubmit={handleSubmit}>
          <h3>Add Exam</h3>

          <div className="add-activity-fields">
            <label>
              Name
              <input
                name="name"
                onChange={handleFormChange}
                required
                type="text"
                value={examForm.name}
              />
            </label>

            <label>
              Category
              <input
                name="category"
                onChange={handleFormChange}
                required
                type="text"
                value={examForm.category}
              />
            </label>

            <label>
              Subject
              <input
                name="subject"
                onChange={handleFormChange}
                type="text"
                value={examForm.subject}
              />
            </label>

            <label>
              Date
              <input
                name="date"
                onChange={handleFormChange}
                required
                type="date"
                value={examForm.date}
              />
            </label>

            <label>
              Start time
              <input
                name="start_time"
                onChange={handleFormChange}
                required
                type="time"
                value={examForm.start_time}
              />
            </label>

            <label>
              End time
              <input
                name="end_time"
                onChange={handleFormChange}
                required
                type="time"
                value={examForm.end_time}
              />
            </label>
          </div>

          {saveError && <p role="alert">{saveError}</p>}

          <div className="add-activity-actions">
            <button disabled={isSaving} type="submit">
              {isSaving ? 'Saving...' : 'Save Exam'}
            </button>
            <button onClick={closeForm} type="button">Cancel</button>
          </div>
        </form>
      )}

      {isLoading && <p>Loading exams...</p>}

      {loadError && <p role="alert">{loadError}</p>}

      {!isLoading && !loadError && (
        <section className="activities-section" aria-labelledby="all-exams-heading">
          <h3 id="all-exams-heading">All Exams</h3>

          {exams.length === 0 ? (
            <p>No exams found.</p>
          ) : (
            <ul className="activities-list">
              {exams.map((exam) => (
                <li className="activities-card" key={exam.id}>
                  <div>
                    <h4>{exam.name}</h4>
                    <p>ID: {exam.id}</p>
                    <p>Category: {exam.category}</p>
                    <p>Subject: {exam.subject || '—'}</p>
                    <p>Date: {exam.date}</p>
                  </div>
                  <p className="activities-time">
                    {exam.start_time} – {exam.end_time}
                  </p>
                </li>
              ))}
            </ul>
          )}
        </section>
      )}
    </main>
  )
}

export default Exams
