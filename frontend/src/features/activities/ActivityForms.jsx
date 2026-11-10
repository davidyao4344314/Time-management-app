export function AddActivityForm({
  activityForm, handleSubmit, handleFormChange, saveError, isSaving, closeForm,
}) {
  return (
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
            type="time"
            value={activityForm.start_time}
          />
        </label>

        <label>
          End time
          <input
            name="end_time"
            onChange={handleFormChange}
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
  )
}

export function DeleteActivityForm({
  deleteForm, handleDeleteSubmit, handleDeleteFormChange, deleteError, isDeleting, isSearching, closeDeleteForm, nameMatches, selectedActivityId, setSelectedActivityId, handleDeleteSelected,
}) {
  return (
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
                    <span>Start time: {activity.startTime || 'No time set'}</span>
                    <span>End time: {activity.endTime || 'No time set'}</span>
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
  )
}

export function ActivitySearchForm({
  handleSearchSubmit, handleSearchNameChange, searchName, searchError, isSearchingActivities, closeSearchForm, hasSearched, searchResults, deletingSearchResultId, handleSearchResultDelete, openEditForm,
}) {
  return (
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
                <span>Start time: {activity.startTime || 'No time set'}</span>
                <span>End time: {activity.endTime || 'No time set'}</span>
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
                <button
                  onClick={() => openEditForm(activity)}
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
  )
}
