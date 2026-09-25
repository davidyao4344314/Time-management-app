import { useEffect, useRef, useState } from 'react'
import './AISettings.css'

function AISettings() {
  const keyInput = useRef(null)
  const [configured, setConfigured] = useState(null)
  const [statusError, setStatusError] = useState('')
  const [saveError, setSaveError] = useState('')
  const [saveMessage, setSaveMessage] = useState('')
  const [isSaving, setIsSaving] = useState(false)

  useEffect(() => {
    const controller = new AbortController()

    async function loadStatus() {
      try {
        const response = await fetch('/api/ai/config/status', {
          cache: 'no-store',
          signal: controller.signal,
        })
        if (!response.ok) throw new Error('Status request failed')
        const data = await response.json()
        setConfigured(data.configured === true)
      } catch (error) {
        if (error.name !== 'AbortError') {
          setStatusError('Could not check API key status. Check the backend server.')
        }
      }
    }

    loadStatus()
    return () => controller.abort()
  }, [])

  async function handleSave(event) {
    event.preventDefault()
    setSaveError('')
    setSaveMessage('')
    setIsSaving(true)

    try {
      const response = await fetch('/api/ai/config', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ api_key: keyInput.current.value }),
      })
      if (!response.ok) throw new Error('Save request failed')
      const data = await response.json()
      if (data.configured !== true) throw new Error('Key was not saved')

      if (keyInput.current) keyInput.current.value = ''
      setConfigured(true)
      setStatusError('')
      setSaveMessage('API key saved locally.')
    } catch {
      setSaveError('Could not save the API key. Check the value and backend server.')
    } finally {
      setIsSaving(false)
    }
  }

  return (
    <main className="page">
      <h2>AI Settings</h2>
      <section className="ai-settings">
        {!statusError && (
          <p role="status">
            {configured === null ? 'Checking API key status...' :
              configured ? 'API key configured.' : 'API key not configured.'}
          </p>
        )}
        {statusError && <p role="alert">{statusError}</p>}

        <form className="ai-settings-form" onSubmit={handleSave}>
          <label htmlFor="openai-api-key">OpenAI API Key</label>
          <input
            id="openai-api-key"
            ref={keyInput}
            type="password"
            autoComplete="off"
            spellCheck={false}
            required
          />
          <button type="submit" disabled={isSaving}>
            {isSaving ? 'Saving...' : 'Save API Key'}
          </button>
        </form>
        {saveError && <p role="alert">{saveError}</p>}
        {saveMessage && <p role="status">{saveMessage}</p>}
      </section>
    </main>
  )
}

export default AISettings
