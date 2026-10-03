import MessageBubble from './MessageBubble'
export default function MessageList({ messages, sending }) {
  return <div className="chat-message-list" aria-label="Conversation messages" aria-live="polite">
    {messages.map(message => <MessageBubble key={message.message_id} message={message} />)}
    {sending && <p role="status">AI is responding…</p>}
  </div>
}
