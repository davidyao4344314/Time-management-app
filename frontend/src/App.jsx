import { useState } from 'react'
import './App.css'

function App() {
  const [isSidebarOpen, setIsSidebarOpen] = useState(false)

  return (
    <>
      <header className="top-bar">
        <h1>activites pllaning app</h1>
        <button
          type="button"
          aria-label={isSidebarOpen ? 'Close menu' : 'Open menu'}
          aria-expanded={isSidebarOpen}
          onClick={() => setIsSidebarOpen(!isSidebarOpen)}
        >
          ☰
        </button>
      </header>

      {isSidebarOpen && (
        <aside className="sidebar">
          <h2>Menu</h2>
        </aside>
      )}
    </>
  )
}

export default App
