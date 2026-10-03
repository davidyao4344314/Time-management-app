import { useEffect, useRef, useState } from 'react'
import './AISettings.css'

const modelLabels = {
  'gpt-6-luna': 'GPT-6 Luna (lowest-cost option)',
  'gpt-6-sol': 'GPT-6 Sol',
  'gpt-6.1-sol': 'GPT-6.1 Sol',
  'gpt-6-astra': 'GPT-6 Astra',
}

const effortLabels = {
  none: 'None',
  low: 'Low',
  medium: 'Medium',
  high: 'High',
  xhigh: 'Extra high',
  max: 'Maximum',
}

function AISettings() {
  const keyInput = useRef(null)
  const keyRequest = useRef(null)
  const [configured, setConfigured] = useState(null)
  const [loadingKeyStatus, setLoadingKeyStatus] = useState(true)
  const [isSavingKey, setIsSavingKey] = useState(false)
  const [saveError, setSaveError] = useState('')
  const [saveMessage, setSaveMessage] = useState('')
  const [models, setModels] = useState([])
  const [model, setModel] = useState('')
  const [reasoningEffort, setReasoningEffort] = useState('')
  const [modelError, setModelError] = useState('')
  const [modelMessage, setModelMessage] = useState('')
  const [isSavingModel, setIsSavingModel] = useState(false)
  const [maxRecentTurns, setMaxRecentTurns] = useState(5)
  const [memoryBounds, setMemoryBounds] = useState({ min: 5, max: 100 })
  const [memoryLoaded, setMemoryLoaded] = useState(false)
  const [memoryError, setMemoryError] = useState('')
  const [memoryMessage, setMemoryMessage] = useState('')
  const [isSavingMemory, setIsSavingMemory] = useState(false)

  useEffect(() => {
    const controller = new AbortController()
    async function loadKeyStatus() {
      try {
        const response = await fetch('/api/ai/config/status', {
          signal: controller.signal, cache: 'no-store',
        })
        if (!response.ok) throw new Error()
        const result = await response.json()
        if (typeof result.configured !== 'boolean') throw new Error()
        setConfigured(result.configured)
      } catch (error) {
        if (error.name !== 'AbortError') setSaveError('Could not check configuration. Is the backend running?')
      } finally {
        if (!controller.signal.aborted) setLoadingKeyStatus(false)
      }
    }
    loadKeyStatus()
    return () => {
      controller.abort()
      keyRequest.current?.abort()
    }
  }, [])

  useEffect(() => {
    const controller = new AbortController()

    async function loadModelSettings() {
      try {
        const response = await fetch('/api/ai/model-config', { signal: controller.signal })
        if (!response.ok) throw new Error('Could not load model settings. Is the backend running?')
        const settings = await response.json()
        setModels(settings.models)
        setModel(settings.model)
        setReasoningEffort(settings.reasoning_effort)
      } catch (error) {
        if (error.name !== 'AbortError') {
          setModelError(error.message || 'Could not load model settings.')
        }
      }
    }

    loadModelSettings()
    return () => controller.abort()
  }, [])

  useEffect(() => {
    const controller = new AbortController()

    async function loadMemorySettings() {
      try {
        const response = await fetch('/api/ai/memory-config', { signal: controller.signal })
        if (!response.ok) throw new Error('Could not load the conversation limit. Is the backend running?')
        const settings = await response.json()
        setMaxRecentTurns(settings.max_recent_turns)
        setMemoryBounds({ min: settings.min, max: settings.max })
        setMemoryLoaded(true)
      } catch (error) {
        if (error.name !== 'AbortError') {
          setMemoryError(error.message || 'Could not load the conversation limit.')
        }
      }
    }

    loadMemorySettings()
    return () => controller.abort()
  }, [])

  const selectedModel = models.find((option) => option.id === model)

  function changeModel(nextModel) {
    const option = models.find((item) => item.id === nextModel)
    setModel(nextModel)
    setReasoningEffort((current) => (
      option.efforts.includes(current) ? current : option.efforts[0]
    ))
    setModelError('')
    setModelMessage('')
  }

  async function handleSaveModel(event) {
    event.preventDefault()
    setModelError('')
    setModelMessage('')
    setIsSavingModel(true)

    try {
      const response = await fetch('/api/ai/model-config', {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ model, reasoning_effort: reasoningEffort }),
      })
      const result = await response.json()
      if (!response.ok) throw new Error(result.detail || 'Could not save model settings.')
      setModel(result.model)
      setReasoningEffort(result.reasoning_effort)
      setModelMessage('Model settings saved. Future AI proposals will use them.')
    } catch (error) {
      setModelError(error.message || 'Could not save model settings.')
    } finally {
      setIsSavingModel(false)
    }
  }

  async function handleSaveMemory(event) {
    event.preventDefault()
    setMemoryError('')
    setMemoryMessage('')

    const limit = Number(maxRecentTurns)
    if (!Number.isInteger(limit) || limit < memoryBounds.min || limit > memoryBounds.max) {
      setMemoryError(`Choose a whole number from ${memoryBounds.min} to ${memoryBounds.max}.`)
      return
    }

    setIsSavingMemory(true)
    try {
      const response = await fetch('/api/ai/memory-config', {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ max_recent_turns: limit }),
      })
      const result = await response.json()
      if (!response.ok) throw new Error(result.detail || 'Could not save the conversation limit.')
      setMaxRecentTurns(result.max_recent_turns)
      setMemoryMessage('Conversation limit saved. It will apply to your next AI request.')
    } catch (error) {
      setMemoryError(error.message || 'Could not save the conversation limit.')
    } finally {
      setIsSavingMemory(false)
    }
  }

  async function handleSave(event) {
    event.preventDefault()
    if (keyRequest.current) return
    setSaveError('')
    setSaveMessage('')

    if (!keyInput.current.value.trim()) {
      setSaveError('Enter an API key first.')
      keyInput.current.focus()
      return
    }

    const controller = new AbortController()
    keyRequest.current = controller
    setIsSavingKey(true)
    try {
      const request = fetch('/api/ai/config', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        credentials: 'same-origin',
        cache: 'no-store',
        signal: controller.signal,
        body: JSON.stringify({ api_key: keyInput.current.value.trim() }),
      })
      // Never persist the secret in browser storage or keep it in React state.
      keyInput.current.value = ''
      const response = await request
      if (!response.ok) {
        setSaveError(response.status === 400 || response.status === 422
          ? 'Enter a valid API key without spaces.'
          : 'Could not save the API key locally. Check the backend and file permissions.')
        return
      }
      const result = await response.json()
      if (result.configured !== true) throw new Error()
      setConfigured(true)
      setSaveMessage('API key saved locally. This does not verify the key with OpenAI.')
    } catch (error) {
      if (error.name !== 'AbortError') setSaveError('Could not confirm the save. Check the backend, then reload to check the status.')
    } finally {
      if (keyInput.current) keyInput.current.value = ''
      keyRequest.current = null
      if (!controller.signal.aborted) setIsSavingKey(false)
    }
  }

  return (
    <main className="page">
      <h2>AI Settings</h2>
      <section className="ai-settings">
        <p role="status">{loadingKeyStatus ? 'Checking configuration...' : configured === null ? 'Configuration status unavailable' : configured ? 'Configured' : 'Not configured'}</p>
        <p id="ai-settings-note">Saved only in the backend's local .env file. The stored key is never returned to this page. Leave blank to keep your existing key.</p>

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
            disabled={isSavingKey || loadingKeyStatus}
          />
          <button type="submit" disabled={isSavingKey || loadingKeyStatus}>
            {isSavingKey ? 'Saving...' : 'Save API Key'}
          </button>
        </form>
        {saveError && <p role="alert">{saveError}</p>}
        {saveMessage && <p role="status">{saveMessage}</p>}
      </section>

      <section className="ai-settings ai-settings-model" aria-labelledby="ai-model-heading">
        <h3 id="ai-model-heading">AI Agent model</h3>
        <p>Choose an OpenAI model and how much it should think for the main agent. Higher effort can take longer and cost more. Routing stages keep their own settings.</p>
        <form className="ai-settings-form" onSubmit={handleSaveModel}>
          <label htmlFor="ai-agent-model">Model</label>
          <select
            id="ai-agent-model"
            value={model}
            onChange={(event) => changeModel(event.target.value)}
            disabled={!models.length || isSavingModel}
          >
            {!models.length && <option value="">Loading models...</option>}
            {models.map((option) => (
              <option key={option.id} value={option.id}>
                {modelLabels[option.id] || option.id}
              </option>
            ))}
          </select>

          <label htmlFor="ai-agent-effort">Thinking effort</label>
          <select
            id="ai-agent-effort"
            value={reasoningEffort}
            onChange={(event) => {
              setReasoningEffort(event.target.value)
              setModelMessage('')
            }}
            disabled={!selectedModel || isSavingModel}
          >
            {!selectedModel && <option value="">Loading efforts...</option>}
            {selectedModel?.efforts.map((effort) => (
              <option key={effort} value={effort}>
                {effortLabels[effort] || effort}
              </option>
            ))}
          </select>
          <button type="submit" disabled={!selectedModel || isSavingModel}>
            {isSavingModel ? 'Saving...' : 'Save Model Settings'}
          </button>
        </form>
        {modelError && <p role="alert">{modelError}</p>}
        {modelMessage && <p role="status">{modelMessage}</p>}
      </section>

      <section className="ai-settings ai-settings-model" aria-labelledby="ai-memory-heading">
        <h3 id="ai-memory-heading">Conversation context</h3>
        <p id="ai-memory-note">A turn is one message from you and one AI reply. Older turns are archived when the limit is exceeded. Higher limits send more conversation history to OpenAI, which can increase token usage and API costs.</p>
        <form className="ai-settings-form" onSubmit={handleSaveMemory} noValidate>
          <label htmlFor="ai-max-recent-turns">Recent conversation turns before archiving</label>
          <input
            id="ai-max-recent-turns"
            type="number"
            min={memoryBounds.min}
            max={memoryBounds.max}
            step="1"
            value={maxRecentTurns}
            onChange={(event) => {
              setMaxRecentTurns(event.target.value)
              setMemoryError('')
              setMemoryMessage('')
            }}
            aria-describedby="ai-memory-note"
            disabled={!memoryLoaded || isSavingMemory}
            required
          />
          <button type="submit" disabled={!memoryLoaded || isSavingMemory}>
            {isSavingMemory ? 'Saving...' : 'Save Conversation Limit'}
          </button>
        </form>
        {memoryError && <p role="alert">{memoryError}</p>}
        {memoryMessage && <p role="status">{memoryMessage}</p>}
      </section>
    </main>
  )
}

export default AISettings
