import AgentContextInspector from '../AgentContextInspector'

export default function MessageBubble({ message }) {
  return (
    <article className={`chat-bubble chat-bubble-${message.role}`} aria-label={`${message.role} message`}>
      <strong>{message.role === 'user' ? 'You' : 'AI'}</strong>
      <p className="ai-agent-response-text">{message.content}</p>
      {message.status !== 'completed' && <p role="status">{message.status === 'pending' ? 'Awaiting a response' : 'Request failed'}</p>}
      {message.role === 'assistant' && <AgentContextInspector context={message.agent_context} actions={message.proposal?.actions || []} />}
    </article>
  )
}
