import { memo, useEffect, useRef } from 'react'
import MessageBubble from './MessageBubble'
function MessageList({ messages, sending }) {
  const latestMessage = useRef(null)
  const lastMessageId = messages.at(-1)?.message_id

  useEffect(() => {
    if (sending || lastMessageId) latestMessage.current?.scrollIntoView({ block: 'end' })
  }, [sending, lastMessageId])

  return <div className="chat-message-list" aria-label="Conversation messages" aria-live="polite">
    {messages.map(message => <MessageBubble key={message.message_id} message={message} />)}
    {sending && <p role="status">AI is responding…</p>}
    <div ref={latestMessage} aria-hidden="true" />
  </div>
}

// Typing in the composer should not re-render the entire conversation.
export default memo(MessageList)
