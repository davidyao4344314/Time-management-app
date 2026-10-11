import { memo } from 'react'
import AgentContextInspector from '../AgentContextInspector'
import FormattedMessage from './FormattedMessage'
import ActionProposalCard from '../ActionProposalCard'

function MessageBubble({ message, onRetry, retryDisabled, retrying, proposals, onDecision, proposalsDisabled, busyId }) {
  return (
    <article className={`chat-bubble chat-bubble-${message.role}`} aria-label={`${message.role} message`}>
      <strong>{message.role === 'user' ? 'You' : 'AI'}</strong>
      {message.role === 'assistant' && message.agent_context?.model && (
        <span className="agent-context-authority"> · {message.agent_context.model}</span>
      )}
      {message.role === 'assistant' ? <FormattedMessage text={message.content} />
        : <p className="ai-agent-response-text">{message.content}</p>}
      {message.role === 'assistant' && message.action_results?.map(result => (
        <p key={result.proposal_id} className={result.success ? 'agent-context-note' : 'chat-error'} role="status">
          {result.message}
        </p>
      ))}
      {message.role === 'assistant' && proposals?.map(proposal => <ActionProposalCard key={proposal.id}
        proposal={proposal} onDecision={onDecision} disabled={proposalsDisabled} busy={busyId === proposal.id} />)}
      {message.status !== 'completed' && <p role="status">{message.status === 'pending' ? 'Awaiting a response' : 'Request failed'}</p>}
      {message.role === 'user' && message.status === 'failed' && onRetry && (
        <button type="button" className="chat-secondary" disabled={retryDisabled || retrying}
          onClick={() => onRetry(message.message_id)}>
          {retrying ? 'Retrying…' : 'Retry'}
        </button>
      )}
      {message.role === 'assistant' && <AgentContextInspector context={message.agent_context} actions={message.proposal?.actions || []} />}
    </article>
  )
}

export default memo(MessageBubble)
