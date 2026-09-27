import { useRef, useState } from 'react'
import './AISettings.css'

function AISettings() {
  const keyInput = useRef(null)
  const [saveError, setSaveError] = useState('')
  const [saveMessage, setSaveMessage] = useState('')

  function handleSave(event) {
    event.preventDefault()
    setSaveError('')
    setSaveMessage('')

    if (!keyInput.current.value.trim()) {
      setSaveError('Enter an API key first.')
      keyInput.current.focus()
      return
    }

    // Placeholder only: do not send or store the secret.
    keyInput.current.value = ''
    setSaveMessage('API key ready to be saved.')
  }

  return (
    <main className="page">
      <h2>AI Settings</h2>
      <section className="ai-settings">
        <p>Not configured</p>
        <p id="ai-settings-note">Frontend placeholder only. No API key is saved.</p>

        <form className="ai-settings-form" onSubmit={handleSave} noValidate>
          <label htmlFor="openai-api-key">OpenAI API Key</label>
          <input
            id="openai-api-key"
            ref={keyInput}
            type="password"
            autoComplete="off"
            autoCapitalize="none"
            spellCheck={false}
            aria-describedby="ai-settings-note"
            required
          />
          <button type="submit">Save API Key</button>
        </form>
        {saveError && <p role="alert">{saveError}</p>}
        {saveMessage && <p role="status">{saveMessage}</p>}
      </section>
    </main>
  )
}

export default AISettings
