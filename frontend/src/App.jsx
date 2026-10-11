import { lazy, Suspense, useEffect, useRef, useState } from 'react'
import './App.css'
import Home from './pages/Home'
import { pageFromUrl, urlForPage } from './navigation'

// Keep the Home screen light; other pages load on their first visit.
const pages = {
  Home,
  Activities: lazy(() => import('./pages/Activities')),
  Calendar: lazy(() => import('./pages/Calendar')),
  Exams: lazy(() => import('./pages/Exams')),
  'Screen Time': lazy(() => import('./pages/ScreenTime')),
  'AI Agent': lazy(() => import('./pages/AIAgent')),
  'AI Settings': lazy(() => import('./pages/AISettings')),
}

function App() {
  const [isSidebarOpen, setIsSidebarOpen] = useState(false)
  const [currentPage, setCurrentPage] = useState(() =>
    pageFromUrl(new URL(window.location.href))
  )
  const menu = useRef(null)
  const menuToggle = useRef(null)
  const Page = pages[currentPage]

  useEffect(() => {
    const navigateBack = () => {
      setCurrentPage(pageFromUrl(new URL(window.location.href)))
      setIsSidebarOpen(false)
      window.scrollTo({ top: 0, left: 0 })
    }
    window.addEventListener('popstate', navigateBack)
    return () => window.removeEventListener('popstate', navigateBack)
  }, [])

  useEffect(() => {
    document.title = `${currentPage} · Activities Planning App`
  }, [currentPage])

  useEffect(() => {
    if (!isSidebarOpen) return
    menu.current?.querySelector('[aria-current="page"]')?.focus()

    function closeOutside(event) {
      if (!menu.current?.contains(event.target) && !menuToggle.current?.contains(event.target)) {
        setIsSidebarOpen(false)
      }
    }
    function closeOnEscape(event) {
      if (event.key === 'Escape') {
        setIsSidebarOpen(false)
        menuToggle.current?.focus()
      }
    }
    document.addEventListener('click', closeOutside)
    document.addEventListener('focusin', closeOutside)
    document.addEventListener('keydown', closeOnEscape)
    return () => {
      document.removeEventListener('click', closeOutside)
      document.removeEventListener('focusin', closeOutside)
      document.removeEventListener('keydown', closeOnEscape)
    }
  }, [isSidebarOpen])

  function changePage(pageName) {
    if (pageName !== currentPage) {
      window.history.pushState(null, '', urlForPage(window.location.href, pageName))
    }
    setCurrentPage(pageName)
    setIsSidebarOpen(false)
    menuToggle.current?.focus()
    window.scrollTo({ top: 0, left: 0 })
  }

  return (
    <>
      <a className="skip-link" href="#page-content">Skip to content</a>
      <header className="top-bar top-bar-sticky">
        <h1>Activities Planning App</h1>
        <button
          ref={menuToggle}
          className="menu-toggle"
          type="button"
          aria-label={isSidebarOpen ? 'Close menu' : 'Open menu'}
          aria-expanded={isSidebarOpen}
          aria-controls={isSidebarOpen ? 'main-navigation' : undefined}
          onClick={() => setIsSidebarOpen(open => !open)}
        >
          ☰
        </button>

        {isSidebarOpen && (
          <nav ref={menu} id="main-navigation" className="menu" aria-label="Main navigation">
            <h2>Menu</h2>
            <ul>
              {Object.keys(pages).map(pageName => (
                <li key={pageName}>
                  <button type="button" aria-current={currentPage === pageName ? 'page' : undefined}
                    onClick={() => changePage(pageName)}>{pageName}</button>
                </li>
              ))}
            </ul>
          </nav>
        )}
      </header>

      <div id="page-content" tabIndex={-1}>
        <Suspense fallback={<main className="page"><p role="status">Loading {currentPage}…</p></main>}>
          <Page />
        </Suspense>
      </div>
    </>
  )
}

export default App
