import { useState } from 'react'
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

  function chooseSuggestion(example) {
    setRequest(example)
    setMessage('')
  }

  function handleAsk(event) {
    event.preventDefault()
    setMessage('AI Agent connection will be added next.')
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
            onChange={(event) => {
              setRequest(event.target.value)
              setMessage('')
            }}
          />
          <button className="ai-agent-ask" type="submit">Ask AI</button>
        </form>

        <div className="ai-agent-suggestions" aria-label="Request suggestions">
          {suggestions.map((suggestion) => (
            <button
              className="ai-agent-suggestion"
              key={suggestion.title}
              type="button"
              onClick={() => chooseSuggestion(suggestion.request)}
            >
              <strong>{suggestion.title}</strong>
              <span>{suggestion.request}</span>
            </button>
          ))}
        </div>

        {message && <p className="ai-agent-message" role="status">{message}</p>}
      </section>
    </main>
  )
}

export default AIAgent
