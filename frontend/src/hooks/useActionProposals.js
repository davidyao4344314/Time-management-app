import { useEffect, useRef, useState } from 'react'

function isProposalView(value) {
  return value && typeof value.id === 'string' && typeof value.display_title === 'string'
    && typeof value.display_description === 'string' && typeof value.status === 'string'
    && typeof value.requires_approval === 'boolean'
}

export default function useActionProposals() {
  const [proposals, setProposals] = useState([])
  const [devEnabled, setDevEnabled] = useState(false)
  const [loading, setLoading] = useState(true)
  const [busyId, setBusyId] = useState(null)
  const [error, setError] = useState('')
  const [needsRefresh, setNeedsRefresh] = useState(false)
  const mounted = useRef(false)
  const request = useRef(null)
  const inFlight = useRef(false)
  const uncertain = useRef(false)
  const latest = useRef([])

  async function run(path, mode, options = {}) {
    if (!mounted.current || inFlight.current) return false
    inFlight.current = true
    const controller = new AbortController()
    request.current = controller
    setError('')
    if (mode === 'load') setLoading(true)
    else setBusyId(mode === 'create' ? 'create' : mode)
    try {
      const response = await fetch(`/api/actions${path}`, {
        credentials: 'same-origin', signal: controller.signal, cache: 'no-store', ...options,
      })
      const data = await response.json()
      if (!response.ok) throw new Error(typeof data.detail === 'string' ? data.detail : 'Could not update the proposal.')
      if (mode === 'load' ? !Array.isArray(data.proposals) || !data.proposals.every(isProposalView) : !isProposalView(data)) {
        throw new Error('The backend returned an invalid proposal response.')
      }
      if (!mounted.current || controller.signal.aborted) return false
      if (mode === 'load') {
        latest.current = data.proposals
        setDevEnabled(data.dev_enabled === true)
        uncertain.current = false
        setNeedsRefresh(false)
      } else {
        latest.current = mode === 'create' ? [...latest.current, data]
          : latest.current.map(proposal => proposal.id === data.id ? data : proposal)
      }
      setProposals(latest.current)
      return true
    } catch (failure) {
      if (!mounted.current || controller.signal.aborted) return false
      if (mode !== 'load') {
        // A network error is not proof the backend did nothing. Never retry
        // confirmation automatically; first reload authoritative status.
        uncertain.current = true
        setNeedsRefresh(true)
      }
      setError(`${failure.message}${mode !== 'load' ? ' Refresh proposals before trying again.' : ''}`)
      return false
    } finally {
      if (request.current === controller) {
        inFlight.current = false
        request.current = null
        if (mounted.current) { setLoading(false); setBusyId(null) }
      }
    }
  }

  const refresh = () => run('/proposals', 'load')
  function createTestProposal() {
    if (!devEnabled || uncertain.current) return false
    return run('/dev/proposals', 'create', {
      method: 'POST', headers: { 'Content-Type': 'application/json' }, body: '{}',
    })
  }
  function decide(proposalId, decision) {
    if (uncertain.current || !['confirm', 'cancel'].includes(decision)
      || !latest.current.some(proposal => proposal.id === proposalId && proposal.status === 'pending_approval')) return false
    return run(`/proposals/${encodeURIComponent(proposalId)}/decision`, proposalId, {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ decision }),
    })
  }

  useEffect(() => {
    mounted.current = true
    let cancelled = false
    Promise.resolve().then(() => { if (!cancelled) refresh() })
    return () => {
      cancelled = true
      mounted.current = false
      request.current?.abort()
      request.current = null
      inFlight.current = false
    }
  }, [])

  return { proposals, devEnabled, loading, busyId, error, needsRefresh, refresh, createTestProposal, decide }
}
