import { useState } from 'react'
import useActivityData, { fetchActivityData, fetchActivitiesByName } from '../features/activities/useActivityData'
import { AddActivityForm, DeleteActivityForm, ActivitySearchForm } from '../features/activities/ActivityForms'
import './Activities.css'
import ActivityEditModal from '../components/ActivityEditModal'

const emptyActivityForm = {
  name: '',
  category: '',
  subject: '',
  activity_type: 'daily',
  date: '',
  weekday: 'Monday',
  start_time: '',
  end_time: '',
}

const emptyDeleteForm = {
  method: 'id',
  activityId: '',
  activityName: '',
}

function formatTimeRange(startTime, endTime) {
  if (!startTime && !endTime) {
    return 'No time set'
  }

  return `${startTime || 'No start time'} – ${endTime || 'No end time'}`
}

function ActivityList({ activities, emptyMessage }) {
  if (activities.length === 0) {
    return <p>{emptyMessage}</p>
  }

  return (
    <ul className="activities-list">
      {activities.map((activity) => (
        <li
          className="activities-card"
          key={activity.calendarId || activity.id}
        >
          <div>
            <h4>{activity.name}</h4>
            {activity.category && <p>Category: {activity.category}</p>}
            {activity.subject && <p>Subject: {activity.subject}</p>}
            {activity.activityType && <p>Type: {activity.activityType}</p>}
            {activity.date && <p>Date: {activity.date}</p>}
            {activity.weekday && <p>Weekday: {activity.weekday}</p>}
          </div>
          <p className="activities-time">
            {formatTimeRange(activity.startTime, activity.endTime)}
          </p>
        </li>
      ))}
    </ul>
  )
}

function Activities() {
  const { allActivities, todayActivities, currentActivities, weeklyActivities, isLoading, loadError, updateActivityLists } = useActivityData()
  const [isFormOpen, setIsFormOpen] = useState(false)
  const [activityForm, setActivityForm] = useState(emptyActivityForm)
  const [isSaving, setIsSaving] = useState(false)
  const [saveError, setSaveError] = useState('')
  const [isDeleteFormOpen, setIsDeleteFormOpen] = useState(false)
  const [deleteForm, setDeleteForm] = useState(emptyDeleteForm)
  const [isDeleting, setIsDeleting] = useState(false)
  const [deleteError, setDeleteError] = useState('')
  const [nameMatches, setNameMatches] = useState([])
  const [selectedActivityId, setSelectedActivityId] = useState('')
  const [isSearching, setIsSearching] = useState(false)
  const [isDeletingAll, setIsDeletingAll] = useState(false)
  const [deleteAllError, setDeleteAllError] = useState('')
  const [isSearchFormOpen, setIsSearchFormOpen] = useState(false)
  const [searchName, setSearchName] = useState('')
  const [searchResults, setSearchResults] = useState([])
  const [hasSearched, setHasSearched] = useState(false)
  const [isSearchingActivities, setIsSearchingActivities] = useState(false)
  const [searchError, setSearchError] = useState('')
  const [deletingSearchResultId, setDeletingSearchResultId] = useState(null)
  const [editingActivity, setEditingActivity] = useState(null)

  function handleFormChange(event) {
    const { name, value } = event.target

    setActivityForm((currentForm) => ({
      ...currentForm,
      [name]: value,
    }))
  }

  function closeForm() {
    setIsFormOpen(false)
    setSaveError('')
    setActivityForm(emptyActivityForm)
  }

  function openAddForm() {
    closeSearchForm()
    setIsDeleteFormOpen(false)
    setDeleteError('')
    setDeleteAllError('')
    setDeleteForm(emptyDeleteForm)
    setIsFormOpen(true)
  }

  function handleDeleteFormChange(event) {
    const { name, value } = event.target

    if (name === 'method' || name === 'activityName') {
      setNameMatches([])
      setSelectedActivityId('')
      setDeleteError('')
    }

    setDeleteForm((currentForm) => ({
      ...currentForm,
      [name]: value,
    }))
  }

  function openDeleteForm() {
    closeForm()
    closeSearchForm()
    setDeleteAllError('')
    setIsDeleteFormOpen(true)
  }

  function closeDeleteForm() {
    setIsDeleteFormOpen(false)
    setDeleteError('')
    setDeleteForm(emptyDeleteForm)
    setNameMatches([])
    setSelectedActivityId('')
  }

  function openSearchForm() {
    closeForm()
    closeDeleteForm()
    setDeleteAllError('')
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

  function openEditForm(activity) {
    setEditingActivity(activity)
  }

  function closeEditForm() {
    setEditingActivity(null)
  }

  async function handleSubmit(event) {
    event.preventDefault()
    setIsSaving(true)
    setSaveError('')

    try {
      const response = await fetch('/api/activities', {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
        },
        body: JSON.stringify({
          ...activityForm,
          subject: activityForm.subject || null,
          date: activityForm.activity_type === 'one_time'
            ? activityForm.date
            : null,
          weekday: activityForm.activity_type === 'weekly'
            ? activityForm.weekday
            : null,
          start_time: activityForm.start_time || null,
          end_time: activityForm.end_time || null,
        }),
      })

      if (!response.ok) {
        const responseBody = await response.json()
        throw new Error(responseBody.detail || 'Could not save the activity.')
      }

      const activityData = await fetchActivityData()
      updateActivityLists(activityData)
      closeForm()
    } catch (requestError) {
      setSaveError(requestError.message)
    } finally {
      setIsSaving(false)
    }
  }

  async function deleteActivityById(activityId) {
    const response = await fetch(`/api/activities/${activityId}`, {
      method: 'DELETE',
    })

    if (!response.ok) {
      const responseBody = await response.json()
      const errorMessage = typeof responseBody.detail === 'string'
        ? responseBody.detail
        : 'Could not delete the activity.'

      throw new Error(errorMessage)
    }

    const activityData = await fetchActivityData()
    updateActivityLists(activityData)
    closeDeleteForm()
  }

  async function handleDeleteSubmit(event) {
    event.preventDefault()
    setDeleteError('')

    if (deleteForm.method === 'name') {
      const activityName = deleteForm.activityName.trim()

      if (!activityName) {
        setDeleteError('Enter an activity name.')
        return
      }

      setIsSearching(true)

      try {
        const matches = await fetchActivitiesByName(activityName)
        setNameMatches(matches)
        setSelectedActivityId('')

        if (matches.length === 0) {
          setDeleteError(`No activities found with the name "${activityName}".`)
        }
      } catch (requestError) {
        setNameMatches([])
        setDeleteError(requestError.message)
      } finally {
        setIsSearching(false)
      }

      return
    }

    const activityId = deleteForm.activityId.trim()

    if (!activityId) {
      setDeleteError('Enter an activity ID.')
      return
    }

    const confirmed = window.confirm(
      `Permanently delete the activity with ID "${activityId}"?`,
    )

    if (!confirmed) {
      return
    }

    setIsDeleting(true)

    try {
      await deleteActivityById(activityId)
    } catch (requestError) {
      setDeleteError(requestError.message)
    } finally {
      setIsDeleting(false)
    }
  }

  async function handleDeleteSelected() {
    if (!selectedActivityId) {
      setDeleteError('Select an activity to delete.')
      return
    }

    const selectedActivity = nameMatches.find(
      (activity) => String(activity.id) === selectedActivityId,
    )
    const confirmed = window.confirm(
      `Permanently delete "${selectedActivity.name}" with ID ${selectedActivity.id}?`,
    )

    if (!confirmed) {
      return
    }

    setIsDeleting(true)
    setDeleteError('')

    try {
      await deleteActivityById(selectedActivityId)
    } catch (requestError) {
      setDeleteError(requestError.message)
    } finally {
      setIsDeleting(false)
    }
  }

  async function handleSearchSubmit(event) {
    event.preventDefault()

    const activityName = searchName.trim()

    if (!activityName) {
      setSearchError('Enter an activity name.')
      return
    }

    setIsSearchingActivities(true)
    setSearchError('')

    try {
      const matches = await fetchActivitiesByName(activityName)
      setSearchResults(matches)
      setHasSearched(true)
    } catch (requestError) {
      setSearchResults([])
      setHasSearched(false)
      setSearchError(requestError.message)
    } finally {
      setIsSearchingActivities(false)
    }
  }

  async function handleSearchResultDelete(activity) {
    const confirmed = window.confirm(
      `Permanently delete "${activity.name}" with ID ${activity.id}?`,
    )

    if (!confirmed) {
      return
    }

    setDeletingSearchResultId(activity.id)
    setSearchError('')

    try {
      await deleteActivityById(activity.id)
      const matches = await fetchActivitiesByName(searchName.trim())
      setSearchResults(matches)
      setHasSearched(true)
    } catch (requestError) {
      setSearchError(requestError.message)
    } finally {
      setDeletingSearchResultId(null)
    }
  }

  async function handleEditSaved(updatedActivity, columnName) {
    try {
      const nextSearchName = columnName === 'name' ? updatedActivity.name : searchName.trim()
      const [activityData, matches] = await Promise.all([
        fetchActivityData(), fetchActivitiesByName(nextSearchName),
      ])
      updateActivityLists(activityData)
      setSearchName(nextSearchName)
      setSearchResults(matches)
      setHasSearched(true)
    } catch {
      setSearchError('The edit was saved, but the lists could not refresh. Reload the page.')
    }
  }

  async function handleDeleteAll() {
    setDeleteAllError('')

    const confirmed = window.confirm(
      'Are you sure you want to permanently delete all activities? This cannot be undone.',
    )

    if (!confirmed) {
      return
    }

    setIsDeletingAll(true)

    try {
      const response = await fetch('/api/activities/all', {
        method: 'DELETE',
      })

      if (!response.ok) {
        const responseBody = await response.json()
        const errorMessage = typeof responseBody.detail === 'string'
          ? responseBody.detail
          : 'Could not delete all activities.'

        throw new Error(errorMessage)
      }

      const activityData = await fetchActivityData()
      updateActivityLists(activityData)
      closeForm()
      closeDeleteForm()
      closeSearchForm()
    } catch (requestError) {
      setDeleteAllError(requestError.message)
    } finally {
      setIsDeletingAll(false)
    }
  }

  return (
    <main className="page">
      <div className="activities-heading-row">
        <h2>Activities</h2>
        <button
          aria-expanded={isFormOpen}
          aria-label="Add activity"
          className="add-activity-button"
          onClick={openAddForm}
          type="button"
        >
          +
        </button>
        <button
          aria-expanded={isDeleteFormOpen}
          aria-label="Delete activity"
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
        <button
          className="delete-all-activities-button"
          disabled={isDeletingAll}
          onClick={handleDeleteAll}
          type="button"
        >
          {isDeletingAll ? 'Deleting...' : 'Delete All'}
        </button>
      </div>

      {deleteAllError && <p role="alert">{deleteAllError}</p>}

      {isFormOpen && (
        <AddActivityForm
          activityForm={activityForm}
          handleSubmit={handleSubmit}
          handleFormChange={handleFormChange}
          saveError={saveError}
          isSaving={isSaving}
          closeForm={closeForm}
        />
      )}

      {isDeleteFormOpen && (
        <DeleteActivityForm
          deleteForm={deleteForm}
          handleDeleteSubmit={handleDeleteSubmit}
          handleDeleteFormChange={handleDeleteFormChange}
          deleteError={deleteError}
          isDeleting={isDeleting}
          isSearching={isSearching}
          closeDeleteForm={closeDeleteForm}
          nameMatches={nameMatches}
          selectedActivityId={selectedActivityId}
          setSelectedActivityId={setSelectedActivityId}
          handleDeleteSelected={handleDeleteSelected}
        />
      )}

      {isSearchFormOpen && (
        <ActivitySearchForm
          handleSearchSubmit={handleSearchSubmit}
          handleSearchNameChange={handleSearchNameChange}
          searchName={searchName}
          searchError={searchError}
          isSearchingActivities={isSearchingActivities}
          closeSearchForm={closeSearchForm}
          hasSearched={hasSearched}
          searchResults={searchResults}
          deletingSearchResultId={deletingSearchResultId}
          handleSearchResultDelete={handleSearchResultDelete}
          openEditForm={openEditForm}
        />
      )}

      {editingActivity && (
        <ActivityEditModal key={editingActivity.id} activity={editingActivity} onClose={closeEditForm} onSaved={handleEditSaved} />
      )}

      {isLoading && <p>Loading activities...</p>}

      {loadError && <p role="alert">{loadError}</p>}

      {!isLoading && !loadError && (
        <>
          <section className="activities-section" aria-labelledby="all-activities-heading">
            <h3 id="all-activities-heading">All Activities</h3>
            <ActivityList
              activities={allActivities}
              emptyMessage="No activities found."
            />
          </section>

          <section className="activities-section" aria-labelledby="current-activities-heading">
            <h3 id="current-activities-heading">Activities Due Now</h3>
            <ActivityList
              activities={currentActivities}
              emptyMessage="No activities due now."
            />
          </section>

          <section className="activities-section" aria-labelledby="activities-heading">
            <h3 id="activities-heading">Today's Activities</h3>
            <ActivityList
              activities={todayActivities}
              emptyMessage="No activities scheduled for today."
            />
          </section>

          <section className="activities-section" aria-labelledby="weekly-activities-heading">
            <h3 id="weekly-activities-heading">Weekly Activities</h3>
            <ActivityList
              activities={weeklyActivities}
              emptyMessage="No activities scheduled this week."
            />
          </section>
        </>
      )}
    </main>
  )
}

export default Activities
