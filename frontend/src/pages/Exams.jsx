import { useState } from 'react'
import useExamData, { fetchExams, fetchExamsByName } from '../features/exams/useExamData'
import { AddExamForm, DeleteExamForm, ExamSearchForm, EditExamForm } from '../features/exams/ExamForms'
import ExamClipboardImport from '../components/ExamClipboardImport'
import useModalFocus from '../hooks/useModalFocus'
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

function formatTimeRange(startTime, endTime) {
  if (!startTime && !endTime) {
    return 'No time set'
  }

  return `${startTime || 'No start time'} – ${endTime || 'No end time'}`
}

function getExamFieldValue(exam, columnName) {
  return exam[columnName] || ''
}

function Exams() {
  const { exams, setExams, isLoading, loadError } = useExamData()
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
  const editDialog = useModalFocus(Boolean(editingExam), closeEditForm, isSavingEdit)
  const [editError, setEditError] = useState('')
  const [isImportOpen, setIsImportOpen] = useState(false)
  const [isImportBusy, setIsImportBusy] = useState(false)
  const [importMessage, setImportMessage] = useState('')

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
    setIsImportOpen(false)
    closeDeleteForm()
    closeSearchForm()
    setIsFormOpen(true)
  }

  function openDeleteForm() {
    setIsImportOpen(false)
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
    setIsImportOpen(false)
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

  function openImportForm() {
    closeForm()
    closeDeleteForm()
    closeSearchForm()
    setImportMessage('')
    setIsImportOpen(true)
  }

  async function handleImported(result) {
    setIsImportOpen(false)
    setImportMessage(`Imported ${result.imported} exam${result.imported === 1 ? '' : 's'}. Skipped ${result.duplicates_skipped} duplicate${result.duplicates_skipped === 1 ? '' : 's'}.`)
    try {
      setExams(await fetchExams())
      setLoadError('')
    } catch {
      setLoadError('The import succeeded, but the exam list could not refresh. Refresh the page to see the saved exams.')
    }
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
          start_time: examForm.start_time || null,
          end_time: examForm.end_time || null,
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
          disabled={isImportBusy}
          type="button"
        >
          +
        </button>
        <button
          aria-expanded={isDeleteFormOpen}
          aria-label="Delete exam"
          className="add-activity-button"
          onClick={openDeleteForm}
          disabled={isImportBusy}
          type="button"
        >
          -
        </button>
        <button
          aria-expanded={isSearchFormOpen}
          className="delete-all-activities-button"
          onClick={openSearchForm}
          disabled={isImportBusy}
          type="button"
        >
          Search
        </button>
        <button aria-expanded={isImportOpen} className="delete-all-activities-button"
          disabled={isImportBusy} onClick={openImportForm} type="button">
          Import Exams from Clipboard
        </button>
      </div>

      {importMessage && <p role="status">{importMessage}</p>}
      {isImportOpen && <ExamClipboardImport onClose={() => setIsImportOpen(false)}
        onImported={handleImported} onBusyChange={setIsImportBusy} />}

      {isFormOpen && (
        <AddExamForm
          examForm={examForm}
          handleSubmit={handleSubmit}
          handleFormChange={handleFormChange}
          saveError={saveError}
          isSaving={isSaving}
          closeForm={closeForm}
        />
      )}

      {isDeleteFormOpen && (
        <DeleteExamForm
          deleteForm={deleteForm}
          handleDeleteSubmit={handleDeleteSubmit}
          handleDeleteFormChange={handleDeleteFormChange}
          deleteError={deleteError}
          isDeleting={isDeleting}
          isSearchingForDelete={isSearchingForDelete}
          closeDeleteForm={closeDeleteForm}
          hasSearchedForDelete={hasSearchedForDelete}
          deleteMatches={deleteMatches}
          selectedExamId={selectedExamId}
          setSelectedExamId={setSelectedExamId}
          handleDeleteSelected={handleDeleteSelected}
        />
      )}

      {isSearchFormOpen && (
        <ExamSearchForm
          handleSearchSubmit={handleSearchSubmit}
          handleSearchNameChange={handleSearchNameChange}
          searchName={searchName}
          searchError={searchError}
          isSearching={isSearching}
          closeSearchForm={closeSearchForm}
          hasSearched={hasSearched}
          searchResults={searchResults}
          deletingSearchResultId={deletingSearchResultId}
          handleSearchResultDelete={handleSearchResultDelete}
          openEditForm={openEditForm}
        />
      )}

      {editingExam && (
        <EditExamForm
          editingExam={editingExam}
          editDialog={editDialog}
          handleEditSubmit={handleEditSubmit}
          handleEditColumnChange={handleEditColumnChange}
          editColumn={editColumn}
          editValue={editValue}
          setEditValue={setEditValue}
          editError={editError}
          isSavingEdit={isSavingEdit}
          closeEditForm={closeEditForm}
        />
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
                    {formatTimeRange(exam.start_time, exam.end_time)}
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
