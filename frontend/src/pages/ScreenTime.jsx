import { useState } from 'react'
import './ScreenTime.css'

function ScreenTime() {
  const [showImportMessage, setShowImportMessage] = useState(false)

  return (
    <main className="page">
      <h2>Screen Time</h2>

      <button
        className="screen-time-import-button"
        type="button"
        onClick={() => setShowImportMessage(true)}
      >
        Import Screen Time from Apple
      </button>
      {showImportMessage && (
        <p role="status">Apple Screen Time import is not connected yet.</p>
      )}

      <section>
        <h3>Today</h3>
        <p>0h 0m</p>
      </section>

      <section>
        <h3>Daily Limit</h3>
        <p>Not set</p>
      </section>

      <section>
        <h3>Apps / Categories</h3>
        <p>No screen time data available yet.</p>
      </section>
    </main>
  )
}

export default ScreenTime
