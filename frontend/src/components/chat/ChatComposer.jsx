export default function ChatComposer({ draft, setDraft, disabled, sending, onSend }) {
  return <form className="ai-agent-request" onSubmit={event => { event.preventDefault(); onSend() }}>
    <label htmlFor="ai-agent-input">Your message</label>
    <textarea id="ai-agent-input" rows={3} value={draft} onChange={event => setDraft(event.target.value)}
      placeholder="Ask for help with your study or activities..." disabled={disabled || sending} maxLength={12000} />
    <button className="ai-agent-ask" type="submit" disabled={disabled || sending || !draft.trim()}>{sending ? 'Sending…' : 'Send'}</button>
    <p className="agent-context-note">Uses your configured OpenAI API key. Requests may incur charges.</p>
  </form>
}
