import { useEffect, useRef, useState } from 'react'
import AgentContextInspector from '../components/AgentContextInspector'
import './AIAgent.css'

const suggestions = [
  {
    title: 'Manage Activities',
    request: 'Help me reorganize my activities this week.',
  },
  {
    title: 'Add Future Activities',
    request: 'Plan study sessions for my upcoming exams.',
  },
  {
    title: 'Study Planning',
    request: 'Help me decide what I should study tonight.',
  },
  {
    title: 'Career Advice',
    request: 'Help me think about future career options.',
  },
]

function AIAgent() {
  const [request, setRequest] = useState('')
  const [message, setMessage] = useState('')
  const [proposal, setProposal] = useState(null)
  const [isLoading, setIsLoading] = useState(false)
  const pendingRequest = useRef(null)

  useEffect(() => () => pendingRequest.current?.abort(), [])

  function chooseSuggestion(example) {
    setRequest(example)
    setMessage('')
  }

  async function handleAsk(event) {
    event.preventDefault()
    if (pendingRequest.current) return
    if (!request.trim()) {
      setMessage('Enter a request first.')
      return
    }
    const controller = new AbortController()
    pendingRequest.current = controller
    setMessage('')
    setProposal(null)
    setIsLoading(true)
    try {
      const response = await fetch('/api/ai/propose', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        credentials: 'same-origin',
        body: JSON.stringify({ message: request.trim() }),
        signal: controller.signal,
      })
      const result = await response.json()
      if (!response.ok) throw new Error(typeof result.detail === 'string' ? result.detail : 'The AI request failed.')
      setProposal(result)
    } catch (error) {
      if (error.name !== 'AbortError') setMessage(error.message || 'Could not reach the backend.')
    } finally {
      if (pendingRequest.current === controller) {
        pendingRequest.current = null
        setIsLoading(false)
      }
    }
  }

  return (
    <main className="page ai-agent-page">
      <section className="ai-agent-content" aria-labelledby="ai-agent-heading">
        <p className="ai-agent-label">AI Agent</p>
        <h2 id="ai-agent-heading">What do you want help with?</h2>

        <form className="ai-agent-request" onSubmit={handleAsk}>
          <label htmlFor="ai-agent-input">Your request</label>
          <textarea
            id="ai-agent-input"
            rows={5}
            placeholder="Ask the AI to help plan your study, manage activities, or think about your future..."
            value={request}
            disabled={isLoading}
            onChange={(event) => {
              setRequest(event.target.value)
              setMessage('')
            }}
          />
          <button className="ai-agent-ask" type="submit" disabled={isLoading}>
            {isLoading ? 'Asking AI…' : 'Ask AI'}
          </button>
          <p className="agent-context-note">Uses your configured OpenAI API key. Requests may incur charges.</p>
        </form>

        <div className="ai-agent-suggestions" aria-label="Request suggestions">
          {suggestions.map((suggestion) => (
            <button
              className="ai-agent-suggestion"
              key={suggestion.title}
              type="button"
              disabled={isLoading}
              onClick={() => chooseSuggestion(suggestion.request)}
            >
              <strong>{suggestion.title}</strong>
              <span>{suggestion.request}</span>
            </button>
          ))}
        </div>

        {message && <p className="ai-agent-message" role="status">{message}</p>}
        {proposal && (
          <section className="ai-agent-response" aria-label="AI response">
            <p className="ai-agent-response-text">{proposal.message}</p>
            <AgentContextInspector context={proposal.agent_context} actions={proposal.actions} />
          </section>
        )}
      </section>
    </main>
  )
}

export default AIAgent
