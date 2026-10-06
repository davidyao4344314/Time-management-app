import './ActionProposals.css'

export default function ActionProposalCard({ proposal, onDecision, disabled, busy }) {
  const pending = proposal.status === 'pending_approval'
  return <article className="action-proposal-card" aria-label={proposal.display_title}>
    <h4>{proposal.display_title}</h4>
    <p className="action-proposal-description">{proposal.display_description}</p>
    <p className="agent-context-note">Status: {proposal.status.replaceAll('_', ' ')}</p>
    {pending && <div className="action-proposal-controls">
      <button type="button" className="ai-agent-ask" disabled={disabled || busy}
        onClick={() => onDecision(proposal.id, 'confirm')}>Confirm</button>
      <button type="button" className="chat-secondary" disabled={disabled || busy}
        onClick={() => onDecision(proposal.id, 'cancel')}>Cancel</button>
    </div>}
    {busy && <p role="status">Sending your decision…</p>}
    {proposal.status === 'rejected' && <p role="status">Cancelled. No action was executed.</p>}
    {proposal.result && <p role={proposal.result.success ? 'status' : 'alert'}>{proposal.result.message}</p>}
    {proposal.result && !proposal.result.success && proposal.result.error && <p role="alert">{proposal.result.error}</p>}
  </article>
}
