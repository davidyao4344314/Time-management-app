import { useCallback, useEffect, useRef, useState } from 'react'

async function api(path, options = {}) {
  const response = await fetch(`/api/conversations${path}`, { credentials: 'same-origin', ...options })
  const data = await response.json()
  if (!response.ok) throw new Error(typeof data.detail === 'string' ? data.detail : 'Could not access this chat.')
  return data
}

export default function useConversation() {
  const [chats, setChats] = useState([])
  const [chat, setChat] = useState(null)
  const [messages, setMessages] = useState([])
  const [draft, setDraft] = useState('')
  const [loading, setLoading] = useState(true)
  const [sending, setSending] = useState(false)
  const [retryingMessageId, setRetryingMessageId] = useState(null)
  const [error, setError] = useState('')
  const [nextBefore, setNextBefore] = useState(null)
  const [loadingOlder, setLoadingOlder] = useState(false)
  const active = useRef(null)
  const pending = useRef(new Map())
  const load = useRef(null)
  const olderLoad = useRef(null)
  const mounted = useRef(false)
  const inFlight = useRef(false)
  const [retryAvailable, setRetryAvailable] = useState(false)
  const [summarizing, setSummarizing] = useState(false)
  const [summaryMessage, setSummaryMessage] = useState('')

  async function selectChat(id) {
    load.current?.abort()
    olderLoad.current?.abort()
    olderLoad.current = null
    const controller = new AbortController()
    load.current = controller
    active.current = id
    setLoading(true)
    setChat(null)
    setMessages([])
    setNextBefore(null)
    setLoadingOlder(false)
    setDraft('')
    setError('')
    setSummaryMessage('')
    setRetryAvailable(pending.current.has(id))
    try {
      const result = await api(`/${id}/messages`, { signal: controller.signal })
      if (controller.signal.aborted || !mounted.current || active.current !== id) return
      setChat(result.conversation)
      setMessages(result.messages)
      setNextBefore(result.next_before)
      const unresolved = pending.current.get(id)
      const saved = unresolved && result.messages.find(item => item.request_id === unresolved.request_id && item.role === 'user')
      if (saved && saved.status !== 'pending') pending.current.delete(id)
      const interrupted = result.messages.find(item => item.role === 'user' && item.status === 'pending')
      if (interrupted) pending.current.set(id, { id, request_id: interrupted.request_id, message: interrupted.content })
      const request = pending.current.get(id)
      setRetryAvailable(Boolean(request))
      if (request) setDraft(request.message)
      const url = new URL(window.location.href)
      url.searchParams.set('chat', id)
      window.history.replaceState(null, '', url)
    } catch (failure) {
      if (failure.name !== 'AbortError' && mounted.current && active.current === id) setError(failure.message)
    } finally {
      if (!controller.signal.aborted && mounted.current && active.current === id) setLoading(false)
    }
  }

  const refreshList = useCallback(async () => {
    const result = await api('')
    if (mounted.current) setChats(result.conversations)
    return result.conversations
  }, [])

  async function newChat() {
    setError('')
    setLoading(true)
    try {
      const result = await api('', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: '{}' })
      await refreshList()
      if (mounted.current) await selectChat(result.conversation_id)
    } catch (failure) {
      if (mounted.current) { setError(failure.message); setLoading(false) }
    }
  }

  useEffect(() => {
    mounted.current = true
    const controller = new AbortController()
    async function initialize() {
      try {
        const result = await api('', { signal: controller.signal })
        if (controller.signal.aborted) return
        setChats(result.conversations)
        const requested = new URL(window.location.href).searchParams.get('chat')
        const id = requested || result.conversations[0]?.conversation_id
        if (id) await selectChat(id)
        else { setLoading(false); setChat(null) }
      } catch (failure) {
        if (failure.name !== 'AbortError') { setError(failure.message); setLoading(false) }
      }
    }
    initialize()
    return () => { mounted.current = false; controller.abort(); load.current?.abort(); olderLoad.current?.abort() }
  }, [])

  const performRequest = useCallback(async request => {
    if (inFlight.current || !mounted.current) return
    inFlight.current = true
    pending.current.set(request.id, request)
    setSending(true)
    setError('')
    setRetryAvailable(false)
    try {
      const result = await api(`/${request.id}/messages`, {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ request_id: request.request_id, message: request.message }),
      })
      if (!mounted.current) return
      if (active.current === request.id) {
        setMessages((current) => [...current.filter((item) => item.request_id !== request.request_id), ...result.messages]
          .sort((a, b) => a.sequence_number - b.sequence_number))
        if (result.status === 'completed') {
          setDraft(current => current.trim() === request.message ? '' : current)
          if (result.memory_export_pending) setError('Reply saved. Memory export is pending; it can be retried later.')
        }
        else setError(result.status === 'pending' ? 'This request is pending. Check the last request to see its result.' : 'This request failed. Click Retry to resend it.')
        setRetryAvailable(result.status === 'pending')
      }
      if (result.status !== 'pending') pending.current.delete(request.id)
      try { await refreshList() }
      catch { if (mounted.current && active.current === request.id) setError('Reply status saved. Could not refresh the conversation list.') }
    } catch (failure) {
      if (mounted.current && active.current === request.id) {
        setError(`${failure.message} Your text is kept. Check the last request before sending again.`)
        setRetryAvailable(true)
      }
    } finally { inFlight.current = false; if (mounted.current) setSending(false) }
  }, [refreshList])

  function send(attempt = null) {
    if (inFlight.current || !chat || (!attempt && !draft.trim())) return
    const request = attempt || pending.current.get(chat.conversation_id)
      || { id: chat.conversation_id, request_id: crypto.randomUUID(), message: draft.trim() }
    return performRequest(request)
  }

  const retryMessage = useCallback(async messageId => {
    if (!chat || active.current !== chat.conversation_id || loading || summarizing || inFlight.current || pending.current.has(chat.conversation_id)) return
    const message = messages.find(item => item.message_id === messageId)
    if (!message || message.role !== 'user' || message.status !== 'failed') return
    setRetryingMessageId(messageId)
    try {
      // A confirmed failure needs a new request ID; uncertain requests retain their original ID.
      await performRequest({ id: chat.conversation_id, request_id: crypto.randomUUID(), message: message.content })
    } finally {
      if (mounted.current) setRetryingMessageId(null)
    }
  }, [chat, messages, loading, summarizing, performRequest])

  async function loadOlder() {
    if (!chat || !nextBefore || olderLoad.current || loading) return
    const id = chat.conversation_id
    const controller = new AbortController()
    olderLoad.current = controller
    setLoadingOlder(true)
    setError('')
    try {
      const result = await api(`/${id}/messages?before=${nextBefore}`, { signal: controller.signal })
      if (!controller.signal.aborted && mounted.current && active.current === id) {
        setMessages(current => {
          // Keep current messages if pages overlap; use a Set for a linear-time merge.
          const knownIds = new Set(current.map(item => item.message_id))
          const earlier = result.messages.filter(item => {
            if (knownIds.has(item.message_id)) return false
            knownIds.add(item.message_id)
            return true
          })
          return [...earlier, ...current]
        })
        setNextBefore(result.next_before)
      }
    } catch (failure) {
      if (!controller.signal.aborted && mounted.current && active.current === id) setError(failure.message)
    } finally {
      if (olderLoad.current === controller) {
        olderLoad.current = null
        if (mounted.current) setLoadingOlder(false)
      }
    }
  }

  async function setMemorySharing(enabled) {
    if (!chat) return
    const id = chat.conversation_id
    try {
      const result = await api(`/${id}/settings`, {method:'PATCH',headers:{'Content-Type':'application/json'},body:JSON.stringify({memory_sharing_enabled:enabled})})
      if (mounted.current && active.current === result.conversation_id) setChat(result)
      if (result.memory_export_pending && active.current === id) setError('Setting saved. Memory export is pending.')
    } catch (failure) { if (mounted.current && active.current === id) setError(failure.message) }
  }

  async function summarizeChat() {
    if (!chat || sending || summarizing) return
    const id = chat.conversation_id
    setSummarizing(true)
    setSummaryMessage('')
    try {
      const result = await api(`/${id}/summary`, {method:'POST'})
      if (mounted.current && active.current===id) setSummaryMessage(result.status==='updated'
        ? 'Older messages summarized for this chat. Your original messages are preserved.'
        : 'A summary is not needed yet. At least 10 older completed turns outside recent context are required.')
    } catch (failure) { if (mounted.current && active.current === id) setError(failure.message) }
    finally { if (mounted.current) setSummarizing(false) }
  }

  return { chats, chat, messages, draft, setDraft, loading, sending, error, nextBefore, loadingOlder,
    retryMessage, retryingMessageId,
    selectChat, newChat, send, loadOlder, setMemorySharing, summarizeChat, summarizing, summaryMessage,
    retryAvailable, checkLast: () => { const request = pending.current.get(active.current); if (request) return send(request) } }
}
