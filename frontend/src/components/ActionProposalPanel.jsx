import ActionProposalCard from './ActionProposalCard'

export default function ActionProposalPanel({ disabled = false, state, groups, chats = [] }) {
  const busy = state.loading || state.busyId !== null
  function renderCard(proposal) {
    const title = chats.find(chat => chat.conversation_id === proposal.conversation_id)?.title
    const origin = proposal.conversation_id ? `From: ${title || 'Another saved conversation'}` : 'Standalone proposal (not linked to a chat)'
    return <div key={proposal.id}><p className="agent-context-note">{origin}</p>
      <ActionProposalCard proposal={proposal} onDecision={state.decide}
        disabled={disabled || busy || state.needsRefresh} busy={state.busyId === proposal.id} /></div>
  }
  return <section className="action-proposal-panel" aria-labelledby="action-proposal-heading">
    <details open={groups.pending.length > 0 || Boolean(state.error)}>
    <summary id="action-proposal-heading">More proposals and history ({groups.pending.length + groups.other.length + groups.history.length})</summary>
    <p className="agent-context-note">Confirm a proposal to save its changes. Pending proposals for loaded replies appear beside those replies.</p>
    <div className="action-proposal-controls">
      <button type="button" className="chat-secondary" disabled={disabled || busy} onClick={state.refresh}>Refresh proposals</button>
      {state.devEnabled && <button type="button" className="chat-secondary" disabled={disabled || busy || state.needsRefresh}
        onClick={state.createTestProposal}>Create test proposal</button>}
    </div>
    {state.devEnabled && <p className="agent-context-note">Development test only. Confirming the sample will add a real test activity to your local database. No AI request is made.</p>}
    {state.loading && <p role="status">Loading proposals…</p>}
    {state.error && <p className="chat-error" role="alert">{state.error}</p>}
    {!state.loading && !state.error && state.proposals.length === 0 && <p>No action proposals to review.</p>}
    {groups.pending.map(renderCard)}
    {groups.other.length > 0 && <details><summary>Other conversations / standalone proposals ({groups.other.length})</summary>
      {groups.other.map(renderCard)}</details>}
    {groups.history.length > 0 && <details><summary>Completed and cancelled proposals ({groups.history.length})</summary>
      {groups.history.map(renderCard)}</details>}
    </details>
  </section>
}
