import { useEffect, useRef, useState } from 'react'

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
  const [error, setError] = useState('')
  const [nextBefore, setNextBefore] = useState(null)
  const active = useRef(null)
  const pending = useRef(null)
  const load = useRef(null)
  const mounted = useRef(false)
  const [retryAvailable, setRetryAvailable] = useState(false)

  async function selectChat(id) {
    load.current?.abort()
    const controller = new AbortController()
    load.current = controller
    active.current = id
    setLoading(true)
    setMessages([])
    setDraft('')
    setError('')
    try {
      const result = await api(`/${id}/messages`, { signal: controller.signal })
      if (!mounted.current || active.current !== id) return
      setChat(result.conversation)
      setMessages(result.messages)
      setNextBefore(result.next_before)
      const url = new URL(window.location.href)
      url.searchParams.set('chat', id)
      window.history.replaceState(null, '', url)
    } catch (failure) {
      if (failure.name !== 'AbortError' && mounted.current) setError(failure.message)
    } finally {
      if (!controller.signal.aborted && mounted.current) setLoading(false)
    }
  }

  async function refreshList() {
    const result = await api('')
    if (mounted.current) setChats(result.conversations)
    return result.conversations
  }

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
    return () => { mounted.current = false; controller.abort(); load.current?.abort() }
  }, [])

  async function send(attempt = null) {
    if (sending || !chat || (!attempt && !draft.trim())) return
    const request = attempt || { id: chat.conversation_id, request_id: crypto.randomUUID(), message: draft.trim() }
    pending.current = request
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
          setDraft('')
          if (result.memory_export_pending) setError('Reply saved. Memory export is pending; it can be retried later.')
        }
        else setError(result.status === 'pending' ? 'This request is pending. Refresh the chat to check its result.' : 'This request failed. You can send a new request.')
      }
      await refreshList()
      pending.current = null
    } catch (failure) {
      if (mounted.current) {
        setError(`${failure.message} Your text is kept. Check the last request before sending again.`)
        setRetryAvailable(true)
      }
    } finally { if (mounted.current) setSending(false) }
  }

  async function loadOlder() {
    if (!chat || !nextBefore) return
    try {
      const id = chat.conversation_id
      const result = await api(`/${id}/messages?before=${nextBefore}`)
      if (mounted.current && active.current === id) {
        setMessages((current) => [...result.messages, ...current.filter(item => !result.messages.some(old => old.message_id === item.message_id))])
        setNextBefore(result.next_before)
      }
    } catch (failure) { if (mounted.current) setError(failure.message) }
  }

  async function setMemorySharing(enabled) {
    if (!chat) return
    try {
      const result = await api(`/${chat.conversation_id}/settings`, {method:'PATCH',headers:{'Content-Type':'application/json'},body:JSON.stringify({memory_sharing_enabled:enabled})})
      if (mounted.current && active.current === result.conversation_id) setChat(result)
      if (result.memory_export_pending) setError('Setting saved. Memory export is pending.')
    } catch (failure) { if (mounted.current) setError(failure.message) }
  }

  return { chats, chat, messages, draft, setDraft, loading, sending, error, nextBefore,
    selectChat, newChat, send, loadOlder, setMemorySharing, retryAvailable, checkLast: () => send(pending.current) }
}
