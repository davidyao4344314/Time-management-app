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
  const [saveError, setSaveError] = useState('')
  const [saveMessage, setSaveMessage] = useState('')
  const [models, setModels] = useState([])
  const [model, setModel] = useState('')
  const [reasoningEffort, setReasoningEffort] = useState('')
  const [modelError, setModelError] = useState('')
  const [modelMessage, setModelMessage] = useState('')
  const [isSavingModel, setIsSavingModel] = useState(false)

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
    </main>
  )
}

export default AISettings
