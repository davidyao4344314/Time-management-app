import useActionProposals from '../hooks/useActionProposals'
import ActionProposalCard from './ActionProposalCard'

export default function ActionProposalPanel({ disabled = false }) {
  const state = useActionProposals()
  const busy = state.loading || state.busyId !== null
  return <section className="action-proposal-panel" aria-labelledby="action-proposal-heading">
    <h3 id="action-proposal-heading">Proposed changes</h3>
    <p className="agent-context-note">Nothing is saved until you confirm a backend proposal. These proposals belong to this browser profile, not a particular chat.</p>
    <div className="action-proposal-controls">
      <button type="button" className="chat-secondary" disabled={disabled || busy} onClick={state.refresh}>Refresh proposals</button>
      {state.devEnabled && <button type="button" className="chat-secondary" disabled={disabled || busy || state.needsRefresh}
        onClick={state.createTestProposal}>Create test proposal</button>}
    </div>
    {state.devEnabled && <p className="agent-context-note">Development test only. Confirming the sample will add a real test activity to your local database. No AI request is made.</p>}
    {state.loading && <p role="status">Loading proposals…</p>}
    {state.error && <p className="chat-error" role="alert">{state.error}</p>}
    {!state.loading && !state.error && state.proposals.length === 0 && <p>No action proposals to review.</p>}
    {state.proposals.map(proposal => <ActionProposalCard key={proposal.id} proposal={proposal} onDecision={state.decide}
      disabled={disabled || busy || state.needsRefresh} busy={state.busyId === proposal.id} />)}
  </section>
}
