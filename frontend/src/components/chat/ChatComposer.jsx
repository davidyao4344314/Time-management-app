export default function ChatComposer({ draft, setDraft, disabled, sending, onSend }) {
  const canSend = !disabled && !sending && Boolean(draft.trim())

  function handleKeyDown(event) {
    if (event.key !== 'Enter' || event.shiftKey || event.nativeEvent.isComposing || event.keyCode === 229) return
    event.preventDefault()
    if (canSend && !event.repeat) event.currentTarget.form.requestSubmit()
  }

  return <form className="ai-agent-request" onSubmit={event => { event.preventDefault(); if (canSend) onSend() }}>
    <label htmlFor="ai-agent-input">Your message</label>
    <textarea id="ai-agent-input" rows={3} value={draft} onChange={event => setDraft(event.target.value)}
      onKeyDown={handleKeyDown} placeholder="Ask for help with your study or activities..." disabled={disabled || sending} maxLength={12000} />
    <button className="ai-agent-ask" type="submit" disabled={!canSend}>{sending ? 'Sending…' : 'Send'}</button>
    <p className="agent-context-note">Enter to send · Shift+Enter for a new line.</p>
    <p className="agent-context-note">Uses your configured OpenAI API key. Requests may incur charges.</p>
  </form>
}
