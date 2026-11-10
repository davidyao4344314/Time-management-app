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

function ExamDetails({ exam }) {
  return (
    <div className="activity-search-details">
      <strong>{exam.name}</strong>
      <span>ID: {exam.id}</span>
      <span>Category: {exam.category || '—'}</span>
      <span>Subject: {exam.subject || '—'}</span>
      <span>Date: {exam.date}</span>
      <span>Start time: {exam.start_time || 'No time set'}</span>
      <span>End time: {exam.end_time || 'No time set'}</span>
    </div>
  )
}

export function AddExamForm({
  examForm, handleSubmit, handleFormChange, saveError, isSaving, closeForm,
}) {
  return (
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
            type="time"
            value={examForm.start_time}
          />
        </label>

        <label>
          End time
          <input
            name="end_time"
            onChange={handleFormChange}
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
  )
}

export function DeleteExamForm({
  deleteForm, handleDeleteSubmit, handleDeleteFormChange, deleteError, isDeleting, isSearchingForDelete, closeDeleteForm, hasSearchedForDelete, deleteMatches, selectedExamId, setSelectedExamId, handleDeleteSelected,
}) {
  return (
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
                    <span>Start time: {exam.start_time || 'No time set'}</span>
                    <span>End time: {exam.end_time || 'No time set'}</span>
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
  )
}

export function ExamSearchForm({
  handleSearchSubmit, handleSearchNameChange, searchName, searchError, isSearching, closeSearchForm, hasSearched, searchResults, deletingSearchResultId, handleSearchResultDelete, openEditForm,
}) {
  return (
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
  )
}

export function EditExamForm({
  editingExam, editDialog, handleEditSubmit, handleEditColumnChange, editColumn, editValue, setEditValue, editError, isSavingEdit, closeEditForm,
}) {
  return (
    <div className="edit-activity-overlay">
      <form
        ref={editDialog}
        tabIndex={-1}
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
              required={!['subject', 'start_time', 'end_time'].includes(editColumn)}
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
          <button disabled={isSavingEdit} onClick={closeEditForm} type="button">Cancel</button>
        </div>
      </form>
    </div>
  )
}
