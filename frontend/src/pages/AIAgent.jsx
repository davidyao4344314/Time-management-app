import useConversation from '../hooks/useConversation'
import MessageList from '../components/chat/MessageList'
import ChatComposer from '../components/chat/ChatComposer'
import './AIAgent.css'

const suggestions = [
  ['Manage Activities', 'Help me reorganize my activities this week.'],
  ['Add Future Activities', 'Plan study sessions for my upcoming exams.'],
  ['Study Planning', 'Help me decide what I should study tonight.'],
  ['Career Advice', 'Help me think about future career options.'],
]

function AIAgent() {
  const state = useConversation()
  return <main className="page ai-agent-page">
    <section className="ai-agent-content" aria-labelledby="ai-agent-heading">
      <p className="ai-agent-label">AI Agent</p>
      <div className="chat-toolbar">
        <button className="ai-agent-ask" onClick={state.newChat} disabled={state.loading || state.sending}>New Chat</button>
        <label htmlFor="active-chat">Conversation</label>
        <select id="active-chat" value={state.chat?.conversation_id || ''} disabled={state.loading || state.sending}
          onChange={event => state.selectChat(event.target.value)}>
          <option value="" disabled>Choose a chat</option>
          {state.chats.map(chat => <option key={chat.conversation_id} value={chat.conversation_id}>{chat.title || 'New conversation'}</option>)}
        </select>
      </div>
      <h2 id="ai-agent-heading">{state.chat?.title || 'What do you want help with?'}</h2>
      {state.loading && <p role="status">Loading conversation…</p>}
      {!state.chat && !state.loading && <p>Start a New Chat to begin.</p>}
      {state.nextBefore && <button onClick={state.loadOlder}>Load earlier messages</button>}
      <MessageList messages={state.messages} sending={state.sending} />
      {state.error && <p role="alert">{state.error}</p>}
      {state.retryAvailable && <button onClick={state.checkLast} disabled={state.sending}>Check last request</button>}
      {state.chat && <button onClick={() => state.selectChat(state.chat.conversation_id)} disabled={state.sending}>Refresh chat</button>}
      {state.messages.length === 0 && state.chat && <div className="ai-agent-suggestions" aria-label="Request suggestions">
        {suggestions.map(([title, request]) => <button key={title} className="ai-agent-suggestion" disabled={state.sending}
          onClick={() => state.setDraft(request)}><strong>{title}</strong><span>{request}</span></button>)}
      </div>}
      <ChatComposer draft={state.draft} setDraft={state.setDraft} disabled={!state.chat || state.loading}
        sending={state.sending} onSend={() => state.send()} />
    </section>
  </main>
}
export default AIAgent
