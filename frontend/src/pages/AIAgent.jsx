import { useEffect, useState } from 'react'
import useConversation from '../hooks/useConversation'
import MessageList from '../components/chat/MessageList'
import ChatComposer from '../components/chat/ChatComposer'
import FileImportPanel from '../components/FileImportPanel'
import './AIAgent.css'

const suggestions = [
  ['Manage Activities', 'Help me reorganize my activities this week.'],
  ['Add Future Activities', 'Plan study sessions for my upcoming exams.'],
  ['Study Planning', 'Help me decide what I should study tonight.'],
  ['Career Advice', 'Help me think about future career options.'],
]

function AIAgent() {
  const state = useConversation()
  const [model, setModel] = useState('Loading model…')

  useEffect(() => {
    const controller = new AbortController()
    async function loadModel() {
      try {
        const response = await fetch('/api/ai/model-config', { signal: controller.signal, cache: 'no-store' })
        if (!response.ok) throw new Error()
        const settings = await response.json()
        if (typeof settings.model !== 'string' || !settings.model.trim()) throw new Error()
        if (!controller.signal.aborted) setModel(settings.model)
      } catch (error) {
        if (error.name !== 'AbortError') setModel('Unavailable')
      }
    }
    loadModel()
    return () => controller.abort()
  }, [])

  return <main className="page ai-agent-page">
    <section className="ai-agent-content" aria-labelledby="ai-agent-heading">
      <p className="ai-agent-label">AI Agent</p>
      <div className="chat-toolbar">
        <button className="ai-agent-ask" onClick={state.newChat} disabled={state.loading || state.sending}>New Chat</button>
        <div className="chat-picker">
          <label htmlFor="active-chat">Conversation</label>
          <select id="active-chat" value={state.chat?.conversation_id || ''} disabled={state.loading || state.sending}
            onChange={event => state.selectChat(event.target.value)}>
            <option value="" disabled>Choose a chat</option>
            {state.chats.map(chat => <option key={chat.conversation_id} value={chat.conversation_id}>{chat.title || 'New conversation'}</option>)}
          </select>
        </div>
      </div>
      <h2 id="ai-agent-heading">{state.chat?.title || 'What do you want help with?'}</h2>
      <p className="agent-context-note chat-model-label">Model for new replies: {model}</p>
      {!state.loading && <FileImportPanel disabled={state.sending || state.summarizing || state.retryAvailable} canAsk={Boolean(state.chat)}
        onUseFile={file => state.setDraft(`What does ${file.file_id} say?`)} />}
      {state.chat && <label className="chat-memory-setting"><input type="checkbox" checked={state.chat.memory_sharing_enabled} disabled={state.sending || state.loading}
        onChange={event => state.setMemorySharing(event.target.checked)} /> Allow older completed turns from this chat to be used as global memory</label>}
      {state.loading && <p role="status">Loading conversation…</p>}
      {!state.chat && !state.loading && <p>Start a New Chat to begin.</p>}
      {state.nextBefore && <button className="chat-secondary" onClick={state.loadOlder} disabled={state.loadingOlder || state.loading}>
        {state.loadingOlder ? 'Loading earlier messages…' : 'Load earlier messages'}
      </button>}
      <MessageList messages={state.messages} sending={state.sending} onRetry={state.retryMessage}
        retryingMessageId={state.retryingMessageId}
        retryDisabled={state.loading || state.sending || state.summarizing || state.retryAvailable} />
      {state.error && <p className="chat-error" role="alert">{state.error}</p>}
      {state.retryAvailable && <button className="chat-secondary" onClick={state.checkLast} disabled={state.sending}>Check last request</button>}
      {state.chat && <button className="chat-secondary" onClick={() => state.selectChat(state.chat.conversation_id)} disabled={state.sending}>Refresh chat</button>}
      {state.chat && <div>
        <button className="chat-secondary" onClick={state.summarizeChat} disabled={state.sending || state.summarizing || state.loading}>
          {state.summarizing ? 'Summarizing…' : 'Summarize older messages'}
        </button>
        <p className="agent-context-note">Optional for long chats. Updating a summary makes an additional AI request.</p>
        {state.summaryMessage && <p role="status">{state.summaryMessage}</p>}
      </div>}
      {state.messages.length === 0 && state.chat && <div className="ai-agent-suggestions" aria-label="Request suggestions">
        {suggestions.map(([title, request]) => <button key={title} className="ai-agent-suggestion" disabled={state.sending}
          onClick={() => state.setDraft(request)}><strong>{title}</strong><span>{request}</span></button>)}
      </div>}
      <ChatComposer draft={state.draft} setDraft={state.setDraft} disabled={!state.chat || state.loading || state.retryAvailable}
        sending={state.sending || state.summarizing} onSend={() => state.send()} />
    </section>
  </main>
}
export default AIAgent
