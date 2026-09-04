import { useEffect, useState } from 'react'
import './Activities.css'

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

function formatActivities(data) {
  return data.map((activity) => ({
    id: activity.id,
    name: activity.name,
    category: activity.category,
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

async function fetchActivityData(signal) {
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

async function fetchActivitiesByName(activityName) {
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
            {activity.startTime} – {activity.endTime}
          </p>
        </li>
      ))}
    </ul>
  )
}

function Activities() {
  const [allActivities, setAllActivities] = useState([])
  const [todayActivities, setTodayActivities] = useState([])
  const [currentActivities, setCurrentActivities] = useState([])
  const [weeklyActivities, setWeeklyActivities] = useState([])
  const [isLoading, setIsLoading] = useState(true)
  const [loadError, setLoadError] = useState('')
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
  }

  function handleSearchNameChange(event) {
    setSearchName(event.target.value)
    setSearchResults([])
    setHasSearched(false)
    setSearchError('')
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
        <form className="add-activity-form" onSubmit={handleSubmit}>
          <h3>Add Activity</h3>

          <div className="add-activity-fields">
            <label>
              Name
              <input
                name="name"
                onChange={handleFormChange}
                required
                type="text"
                value={activityForm.name}
              />
            </label>

            <label>
              Category
              <input
                name="category"
                onChange={handleFormChange}
                required
                type="text"
                value={activityForm.category}
              />
            </label>

            <label>
              Subject
              <input
                name="subject"
                onChange={handleFormChange}
                type="text"
                value={activityForm.subject}
              />
            </label>

            <label>
              Activity type
              <select
                name="activity_type"
                onChange={handleFormChange}
                value={activityForm.activity_type}
              >
                <option value="daily">Daily</option>
                <option value="one_time">One time</option>
                <option value="weekly">Weekly</option>
              </select>
            </label>

            {activityForm.activity_type === 'one_time' && (
              <label>
                Date
                <input
                  name="date"
                  onChange={handleFormChange}
                  required
                  type="date"
                  value={activityForm.date}
                />
              </label>
            )}

            {activityForm.activity_type === 'weekly' && (
              <label>
                Weekday
                <select
                  name="weekday"
                  onChange={handleFormChange}
                  value={activityForm.weekday}
                >
                  <option>Monday</option>
                  <option>Tuesday</option>
                  <option>Wednesday</option>
                  <option>Thursday</option>
                  <option>Friday</option>
                  <option>Saturday</option>
                  <option>Sunday</option>
                </select>
              </label>
            )}

            <label>
              Start time
              <input
                name="start_time"
                onChange={handleFormChange}
                required
                type="time"
                value={activityForm.start_time}
              />
            </label>

            <label>
              End time
              <input
                name="end_time"
                onChange={handleFormChange}
                required
                type="time"
                value={activityForm.end_time}
              />
            </label>
          </div>

          {saveError && <p role="alert">{saveError}</p>}

          <div className="add-activity-actions">
            <button disabled={isSaving} type="submit">
              {isSaving ? 'Saving...' : 'Save Activity'}
            </button>
            <button onClick={closeForm} type="button">Cancel</button>
          </div>
        </form>
      )}

      {isDeleteFormOpen && (
        <form className="add-activity-form" onSubmit={handleDeleteSubmit}>
          <h3>Delete Activity</h3>

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
                Activity ID
                <input
                  min="1"
                  name="activityId"
                  onChange={handleDeleteFormChange}
                  required
                  step="1"
                  type="number"
                  value={deleteForm.activityId}
                />
              </label>
            )}

            {deleteForm.method === 'name' && (
              <label>
                Activity name
                <input
                  name="activityName"
                  onChange={handleDeleteFormChange}
                  required
                  type="text"
                  value={deleteForm.activityName}
                />
              </label>
            )}
          </div>

          {deleteError && <p role="alert">{deleteError}</p>}

          <div className="add-activity-actions">
            <button disabled={isDeleting || isSearching} type="submit">
              {deleteForm.method === 'name'
                ? (isSearching ? 'Searching...' : 'Search Activities')
                : (isDeleting ? 'Deleting...' : 'Delete Activity')}
            </button>
            <button onClick={closeDeleteForm} type="button">Cancel</button>
          </div>

          {deleteForm.method === 'name' && nameMatches.length > 0 && (
            <fieldset className="delete-name-results">
              <legend>Matching activities</legend>

              <ul className="delete-name-matches">
                {nameMatches.map((activity) => (
                  <li key={activity.id}>
                    <label className="delete-name-match">
                      <input
                        checked={selectedActivityId === String(activity.id)}
                        name="selectedActivity"
                        onChange={(event) => setSelectedActivityId(event.target.value)}
                        type="radio"
                        value={activity.id}
                      />
                      <span>
                        <strong>{activity.name}</strong>
                        <span>ID: {activity.id}</span>
                        <span>Category: {activity.category || '—'}</span>
                        <span>Subject: {activity.subject || '—'}</span>
                        <span>Activity type: {activity.activityType}</span>
                        <span>Date: {activity.date || '—'}</span>
                        <span>Weekday: {activity.weekday || '—'}</span>
                        <span>Start time: {activity.startTime}</span>
                        <span>End time: {activity.endTime}</span>
                      </span>
                    </label>
                  </li>
                ))}
              </ul>

              <button
                className="delete-selected-activity-button"
                disabled={isDeleting || !selectedActivityId}
                onClick={handleDeleteSelected}
                type="button"
              >
                {isDeleting ? 'Deleting...' : 'Delete Selected Activity'}
              </button>
            </fieldset>
          )}
        </form>
      )}

      {isSearchFormOpen && (
        <form className="add-activity-form" onSubmit={handleSearchSubmit}>
          <h3>Search Activities</h3>

          <div className="add-activity-fields">
            <label>
              Activity name
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
            <button disabled={isSearchingActivities} type="submit">
              {isSearchingActivities ? 'Searching...' : 'Search'}
            </button>
            <button onClick={closeSearchForm} type="button">Cancel</button>
          </div>

          {hasSearched && searchResults.length === 0 && (
            <p>No activities found with that exact name.</p>
          )}

          {searchResults.length > 0 && (
            <ul className="activity-search-results">
              {searchResults.map((activity) => (
                <li className="activity-search-card" key={activity.id}>
                  <div className="activity-search-details">
                    <strong>{activity.name}</strong>
                    <span>ID: {activity.id}</span>
                    <span>Category: {activity.category || '—'}</span>
                    <span>Subject: {activity.subject || '—'}</span>
                    <span>Activity type: {activity.activityType}</span>
                    <span>Date: {activity.date || '—'}</span>
                    <span>Weekday: {activity.weekday || '—'}</span>
                    <span>Start time: {activity.startTime}</span>
                    <span>End time: {activity.endTime}</span>
                  </div>

                  <div className="activity-search-actions">
                    <button
                      disabled={deletingSearchResultId === activity.id}
                      onClick={() => handleSearchResultDelete(activity)}
                      type="button"
                    >
                      {deletingSearchResultId === activity.id
                        ? 'Deleting...'
                        : 'Delete'}
                    </button>
                    <button disabled title="Editing is not implemented yet" type="button">
                      Edit
                    </button>
                  </div>
                </li>
              ))}
            </ul>
          )}
        </form>
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
