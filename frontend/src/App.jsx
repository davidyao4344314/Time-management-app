import { useState } from 'react'
import './App.css'
import Home from './pages/Home'
import Activities from './pages/Activities'
import Calendar from './pages/Calendar'
import Exams from './pages/Exams'

function App() {
  const [isSidebarOpen, setIsSidebarOpen] = useState(false)
  const [currentPage, setCurrentPage] = useState('Home')

  function changePage(pageName) {
    setCurrentPage(pageName)
    setIsSidebarOpen(false)
  }

  return (
    <>
      <header className="top-bar">
        <h1>activites pllaning app</h1>
        <button
          className="menu-toggle"
          type="button"
          aria-label={isSidebarOpen ? 'Close menu' : 'Open menu'}
          aria-expanded={isSidebarOpen}
          onClick={() => setIsSidebarOpen(!isSidebarOpen)}
        >
          ☰
        </button>

        {isSidebarOpen && (
          <nav className="menu" aria-label="Main navigation">
            <h2>Menu</h2>
            <ul>
              <li><button type="button" onClick={() => changePage('Home')}>Home</button></li>
              <li><button type="button" onClick={() => changePage('Activities')}>Activities</button></li>
              <li><button type="button" onClick={() => changePage('Calendar')}>Calendar</button></li>
              <li><button type="button" onClick={() => changePage('Exams')}>Exams</button></li>
            </ul>
          </nav>
        )}
      </header>

      {currentPage === 'Home' && <Home />}
      {currentPage === 'Activities' && <Activities />}
      {currentPage === 'Calendar' && <Calendar />}
      {currentPage === 'Exams' && <Exams />}
    </>
  )
}

export default App
