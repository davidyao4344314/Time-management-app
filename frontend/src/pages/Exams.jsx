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

const emptyDeleteExamForm = {
  method: 'id',
  examId: '',
  examName: '',
}

const examEditFieldLabels = {
  name: 'Name',
  category: 'Category',
  subject: 'Subject',
  date: 'Date',
  start_time: 'Start time',
  end_time: 'End time',
}

function getExamFieldValue(exam, columnName) {
  return exam[columnName] || ''
}

async function fetchExams(signal) {
  const response = await fetch('/api/exams', { signal })

  if (!response.ok) {
    throw new Error('The server could not load the exams.')
  }

  return response.json()
}

async function fetchExamsByName(examName) {
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

function ExamDetails({ exam }) {
  return (
    <div className="activity-search-details">
      <strong>{exam.name}</strong>
      <span>ID: {exam.id}</span>
      <span>Category: {exam.category || '—'}</span>
      <span>Subject: {exam.subject || '—'}</span>
      <span>Date: {exam.date}</span>
      <span>Start time: {exam.start_time}</span>
      <span>End time: {exam.end_time}</span>
    </div>
  )
}

function Exams() {
  const [exams, setExams] = useState([])
  const [isLoading, setIsLoading] = useState(true)
  const [loadError, setLoadError] = useState('')
  const [isFormOpen, setIsFormOpen] = useState(false)
  const [examForm, setExamForm] = useState(emptyExamForm)
  const [isSaving, setIsSaving] = useState(false)
  const [saveError, setSaveError] = useState('')
  const [isDeleteFormOpen, setIsDeleteFormOpen] = useState(false)
  const [deleteForm, setDeleteForm] = useState(emptyDeleteExamForm)
  const [deleteMatches, setDeleteMatches] = useState([])
  const [hasSearchedForDelete, setHasSearchedForDelete] = useState(false)
  const [selectedExamId, setSelectedExamId] = useState('')
  const [isSearchingForDelete, setIsSearchingForDelete] = useState(false)
  const [isDeleting, setIsDeleting] = useState(false)
  const [deleteError, setDeleteError] = useState('')
  const [isSearchFormOpen, setIsSearchFormOpen] = useState(false)
  const [searchName, setSearchName] = useState('')
  const [searchResults, setSearchResults] = useState([])
  const [hasSearched, setHasSearched] = useState(false)
  const [isSearching, setIsSearching] = useState(false)
  const [searchError, setSearchError] = useState('')
  const [deletingSearchResultId, setDeletingSearchResultId] = useState(null)
  const [editingExam, setEditingExam] = useState(null)
  const [editColumn, setEditColumn] = useState('name')
  const [editValue, setEditValue] = useState('')
  const [isSavingEdit, setIsSavingEdit] = useState(false)
  const [editError, setEditError] = useState('')

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

  function openAddForm() {
    closeDeleteForm()
    closeSearchForm()
    setIsFormOpen(true)
  }

  function openDeleteForm() {
    closeForm()
    closeSearchForm()
    setIsDeleteFormOpen(true)
  }

  function closeDeleteForm() {
    setIsDeleteFormOpen(false)
    setDeleteForm(emptyDeleteExamForm)
    setDeleteMatches([])
    setHasSearchedForDelete(false)
    setSelectedExamId('')
    setDeleteError('')
  }

  function handleDeleteFormChange(event) {
    const { name, value } = event.target

    if (name === 'method' || name === 'examName') {
      setDeleteMatches([])
      setHasSearchedForDelete(false)
      setSelectedExamId('')
      setDeleteError('')
    }

    setDeleteForm((currentForm) => ({
      ...currentForm,
      [name]: value,
    }))
  }

  function openSearchForm() {
    closeForm()
    closeDeleteForm()
    setIsSearchFormOpen(true)
  }

  function closeSearchForm() {
    setIsSearchFormOpen(false)
    setSearchName('')
    setSearchResults([])
    setHasSearched(false)
    setSearchError('')
    closeEditForm()
  }

  function handleSearchNameChange(event) {
    setSearchName(event.target.value)
    setSearchResults([])
    setHasSearched(false)
    setSearchError('')
  }

  function openEditForm(exam) {
    setEditingExam(exam)
    setEditColumn('name')
    setEditValue(exam.name)
    setEditError('')
  }

  function closeEditForm() {
    setEditingExam(null)
    setEditColumn('name')
    setEditValue('')
    setEditError('')
  }

  function handleEditColumnChange(event) {
    const columnName = event.target.value

    setEditColumn(columnName)
    setEditValue(getExamFieldValue(editingExam, columnName))
    setEditError('')
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

  async function deleteExamById(examId) {
    const response = await fetch(`/api/exams/${examId}`, {
      method: 'DELETE',
    })

    if (!response.ok) {
      const responseBody = await response.json()
      const errorMessage = typeof responseBody.detail === 'string'
        ? responseBody.detail
        : 'Could not delete the exam.'

      throw new Error(errorMessage)
    }
  }

  async function handleDeleteSubmit(event) {
    event.preventDefault()
    setDeleteError('')

    if (deleteForm.method === 'name') {
      const examName = deleteForm.examName.trim()

      if (!examName) {
        setDeleteError('Enter an exam name.')
        return
      }

      setIsSearchingForDelete(true)

      try {
        setDeleteMatches(await fetchExamsByName(examName))
        setSelectedExamId('')
        setHasSearchedForDelete(true)
      } catch (requestError) {
        setDeleteMatches([])
        setHasSearchedForDelete(false)
        setDeleteError(requestError.message)
      } finally {
        setIsSearchingForDelete(false)
      }

      return
    }

    const examId = deleteForm.examId.trim()

    if (!examId) {
      setDeleteError('Enter an exam ID.')
      return
    }

    const confirmed = window.confirm(
      `Permanently delete the exam with ID "${examId}"?`,
    )

    if (!confirmed) {
      return
    }

    setIsDeleting(true)

    try {
      await deleteExamById(examId)
      setExams(await fetchExams())
      closeDeleteForm()
    } catch (requestError) {
      setDeleteError(requestError.message)
    } finally {
      setIsDeleting(false)
    }
  }

  async function handleDeleteSelected() {
    if (!selectedExamId) {
      setDeleteError('Select an exam to delete.')
      return
    }

    const selectedExam = deleteMatches.find(
      (exam) => String(exam.id) === selectedExamId,
    )
    const confirmed = window.confirm(
      `Permanently delete "${selectedExam.name}" with ID ${selectedExam.id}?`,
    )

    if (!confirmed) {
      return
    }

    setIsDeleting(true)
    setDeleteError('')

    try {
      await deleteExamById(selectedExamId)
      const [allExams, matchingExams] = await Promise.all([
        fetchExams(),
        fetchExamsByName(deleteForm.examName.trim()),
      ])
      setExams(allExams)
      setDeleteMatches(matchingExams)
      setSelectedExamId('')
      setHasSearchedForDelete(true)
    } catch (requestError) {
      setDeleteError(requestError.message)
    } finally {
      setIsDeleting(false)
    }
  }

  async function handleSearchSubmit(event) {
    event.preventDefault()

    const examName = searchName.trim()

    if (!examName) {
      setSearchError('Enter an exam name.')
      return
    }

    setIsSearching(true)
    setSearchError('')

    try {
      setSearchResults(await fetchExamsByName(examName))
      setHasSearched(true)
    } catch (requestError) {
      setSearchResults([])
      setHasSearched(false)
      setSearchError(requestError.message)
    } finally {
      setIsSearching(false)
    }
  }

  async function handleSearchResultDelete(exam) {
    const confirmed = window.confirm(
      `Permanently delete "${exam.name}" with ID ${exam.id}?`,
    )

    if (!confirmed) {
      return
    }

    setDeletingSearchResultId(exam.id)
    setSearchError('')

    try {
      await deleteExamById(exam.id)
      const [allExams, matchingExams] = await Promise.all([
        fetchExams(),
        fetchExamsByName(searchName.trim()),
      ])
      setExams(allExams)
      setSearchResults(matchingExams)
      setHasSearched(true)
    } catch (requestError) {
      setSearchError(requestError.message)
    } finally {
      setDeletingSearchResultId(null)
    }
  }

  async function handleEditSubmit(event) {
    event.preventDefault()
    setIsSavingEdit(true)
    setEditError('')

    try {
      const response = await fetch(`/api/exams/${editingExam.id}`, {
        method: 'PUT',
        headers: {
          'Content-Type': 'application/json',
        },
        body: JSON.stringify({
          exam_id: editingExam.id,
          column_name: editColumn,
          new_value: editValue || null,
        }),
      })

      if (!response.ok) {
        const responseBody = await response.json()
        const errorMessage = typeof responseBody.detail === 'string'
          ? responseBody.detail
          : 'Could not update the exam.'

        throw new Error(errorMessage)
      }

      const updatedExam = await response.json()
      const nextSearchName = editColumn === 'name'
        ? updatedExam.name
        : searchName.trim()
      const [allExams, matchingExams] = await Promise.all([
        fetchExams(),
        fetchExamsByName(nextSearchName),
      ])

      setExams(allExams)
      setSearchName(nextSearchName)
      setSearchResults(matchingExams)
      setHasSearched(true)
      closeEditForm()
    } catch (requestError) {
      setEditError(requestError.message)
    } finally {
      setIsSavingEdit(false)
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
          onClick={openAddForm}
          type="button"
        >
          +
        </button>
        <button
          aria-expanded={isDeleteFormOpen}
          aria-label="Delete exam"
          className="add-activity-button"
          onClick={openDeleteForm}
          type="button"
        >
          -
        </button>
        <button
          aria-expanded={isSearchFormOpen}
          className="delete-all-activities-button"
          onClick={openSearchForm}
          type="button"
        >
          Search
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

      {isDeleteFormOpen && (
        <form className="add-activity-form" onSubmit={handleDeleteSubmit}>
          <h3>Delete Exam</h3>

          <div className="add-activity-fields">
            <label>
              Delete method
              <select
                name="method"
                onChange={handleDeleteFormChange}
                value={deleteForm.method}
              >
                <option value="id">Delete by ID</option>
                <option value="name">Delete by name</option>
              </select>
            </label>

            {deleteForm.method === 'id' && (
              <label>
                Exam ID
                <input
                  min="1"
                  name="examId"
                  onChange={handleDeleteFormChange}
                  required
                  step="1"
                  type="number"
                  value={deleteForm.examId}
                />
              </label>
            )}

            {deleteForm.method === 'name' && (
              <label>
                Exam name
                <input
                  name="examName"
                  onChange={handleDeleteFormChange}
                  required
                  type="text"
                  value={deleteForm.examName}
                />
              </label>
            )}
          </div>

          {deleteError && <p role="alert">{deleteError}</p>}

          <div className="add-activity-actions">
            <button
              disabled={isDeleting || isSearchingForDelete}
              type="submit"
            >
              {deleteForm.method === 'name'
                ? (isSearchingForDelete ? 'Searching...' : 'Search Exams')
                : (isDeleting ? 'Deleting...' : 'Delete Exam')}
            </button>
            <button onClick={closeDeleteForm} type="button">Cancel</button>
          </div>

          {deleteForm.method === 'name'
            && hasSearchedForDelete
            && deleteMatches.length === 0 && (
              <p>No exams found with that exact name.</p>
          )}

          {deleteForm.method === 'name' && deleteMatches.length > 0 && (
            <fieldset className="delete-name-results">
              <legend>Matching exams</legend>

              <ul className="delete-name-matches">
                {deleteMatches.map((exam) => (
                  <li key={exam.id}>
                    <label className="delete-name-match">
                      <input
                        checked={selectedExamId === String(exam.id)}
                        name="selectedExam"
                        onChange={(event) => setSelectedExamId(event.target.value)}
                        type="radio"
                        value={exam.id}
                      />
                      <span>
                        <strong>{exam.name}</strong>
                        <span>ID: {exam.id}</span>
                        <span>Category: {exam.category || '—'}</span>
                        <span>Subject: {exam.subject || '—'}</span>
                        <span>Date: {exam.date}</span>
                        <span>Start time: {exam.start_time}</span>
                        <span>End time: {exam.end_time}</span>
                      </span>
                    </label>
                  </li>
                ))}
              </ul>

              <button
                className="delete-selected-activity-button"
                disabled={isDeleting || !selectedExamId}
                onClick={handleDeleteSelected}
                type="button"
              >
                {isDeleting ? 'Deleting...' : 'Delete Selected Exam'}
              </button>
            </fieldset>
          )}
        </form>
      )}

      {isSearchFormOpen && (
        <form className="add-activity-form" onSubmit={handleSearchSubmit}>
          <h3>Search Exams</h3>

          <div className="add-activity-fields">
            <label>
              Exam name
              <input
                onChange={handleSearchNameChange}
                required
                type="text"
                value={searchName}
              />
            </label>
          </div>

          {searchError && <p role="alert">{searchError}</p>}

          <div className="add-activity-actions">
            <button disabled={isSearching} type="submit">
              {isSearching ? 'Searching...' : 'Search'}
            </button>
            <button onClick={closeSearchForm} type="button">Cancel</button>
          </div>

          {hasSearched && searchResults.length === 0 && (
            <p>No exams found with that exact name.</p>
          )}

          {searchResults.length > 0 && (
            <ul className="activity-search-results">
              {searchResults.map((exam) => (
                <li className="activity-search-card" key={exam.id}>
                  <ExamDetails exam={exam} />

                  <div className="activity-search-actions">
                    <button
                      disabled={deletingSearchResultId === exam.id}
                      onClick={() => handleSearchResultDelete(exam)}
                      type="button"
                    >
                      {deletingSearchResultId === exam.id
                        ? 'Deleting...'
                        : 'Delete'}
                    </button>
                    <button
                      onClick={() => openEditForm(exam)}
                      type="button"
                    >
                      Edit
                    </button>
                  </div>
                </li>
              ))}
            </ul>
          )}
        </form>
      )}

      {editingExam && (
        <div className="edit-activity-overlay">
          <form
            aria-labelledby="edit-exam-heading"
            aria-modal="true"
            className="add-activity-form edit-activity-form"
            onSubmit={handleEditSubmit}
            role="dialog"
          >
            <h3 id="edit-exam-heading">
              Edit {editingExam.name} (ID {editingExam.id})
            </h3>

            <div className="add-activity-fields">
              <label>
                Field to edit
                <select
                  onChange={handleEditColumnChange}
                  value={editColumn}
                >
                  {Object.entries(examEditFieldLabels).map(([column, label]) => (
                    <option key={column} value={column}>{label}</option>
                  ))}
                </select>
              </label>

              <div className="edit-current-value">
                <span>Current value</span>
                <strong>
                  {getExamFieldValue(editingExam, editColumn) || 'Not set'}
                </strong>
              </div>

              <label>
                New value
                <input
                  onChange={(event) => setEditValue(event.target.value)}
                  required={editColumn !== 'subject'}
                  type={editColumn === 'date'
                    ? 'date'
                    : editColumn === 'start_time' || editColumn === 'end_time'
                      ? 'time'
                      : 'text'}
                  value={editValue}
                />
              </label>
            </div>

            {editError && <p role="alert">{editError}</p>}

            <div className="add-activity-actions">
              <button disabled={isSavingEdit} type="submit">
                {isSavingEdit ? 'Saving...' : 'Save'}
              </button>
              <button onClick={closeEditForm} type="button">Cancel</button>
            </div>
          </form>
        </div>
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
