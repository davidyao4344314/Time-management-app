import { memo } from 'react'
import AgentContextInspector from '../AgentContextInspector'

function MessageBubble({ message }) {
  return (
    <article className={`chat-bubble chat-bubble-${message.role}`} aria-label={`${message.role} message`}>
      <strong>{message.role === 'user' ? 'You' : 'AI'}</strong>
      {message.role === 'assistant' && message.agent_context?.model && (
        <span className="agent-context-authority"> · {message.agent_context.model}</span>
      )}
      <p className="ai-agent-response-text">{message.content}</p>
      {message.status !== 'completed' && <p role="status">{message.status === 'pending' ? 'Awaiting a response' : 'Request failed'}</p>}
      {message.role === 'assistant' && <AgentContextInspector context={message.agent_context} actions={message.proposal?.actions || []} />}
    </article>
  )
}

export default memo(MessageBubble)
