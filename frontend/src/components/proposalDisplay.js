export function groupActionProposals(proposals, conversationId, messages) {
  const replies = new Set(messages.filter(message => message.role === 'assistant').map(message => message.request_id))
  const byRequest = new Map(), pending = [], other = [], history = []
  for (const proposal of proposals) {
    if (proposal.status !== 'pending_approval') { history.push(proposal); continue }
    if (conversationId && proposal.conversation_id === conversationId) {
      if (proposal.request_id && replies.has(proposal.request_id)) {
        if (!byRequest.has(proposal.request_id)) byRequest.set(proposal.request_id, [])
        byRequest.get(proposal.request_id).push(proposal)
      } else pending.push(proposal)
    } else other.push(proposal)
  }
  return { byRequest, pending, other, history }
}
