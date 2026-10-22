import { useLayoutEffect, useRef } from 'react'
import type { UiMessage } from '../state/chatReducer'
import { MessageView } from './MessageView'

interface Props {
  messages: UiMessage[]
  busy: boolean
  onRetry: () => void
  onEdit: (serverId: string, text: string) => void
}

export function MessageList({ messages, busy, onRetry, onEdit }: Props) {
  const scroller = useRef<HTMLDivElement>(null)
  const stickToBottom = useRef(true)

  // Follow the answer as it streams, unless the reader scrolled up to look at something.
  useLayoutEffect(() => {
    const element = scroller.current
    if (element && stickToBottom.current) element.scrollTop = element.scrollHeight
  }, [messages])

  return (
    <div
      className="messages"
      ref={scroller}
      onScroll={() => {
        const el = scroller.current
        if (el) stickToBottom.current = el.scrollHeight - el.scrollTop - el.clientHeight < 80
      }}
    >
      <div className="messages-inner" role="log" aria-live="polite">
        {messages.length === 0 && (
          <div className="empty">
            <h2>What would you like to know?</h2>
            <p>
              The model thinks before it answers. You can watch it think, or switch Thinking off at the top for
              faster replies.
            </p>
          </div>
        )}
        {messages.map((message, index) => (
          <MessageView
            key={message.id}
            message={message}
            isLast={index === messages.length - 1}
            onRetry={onRetry}
            laterCount={messages.length - index - 1}
            onEdit={
              message.role === 'user' && message.serverId && !busy
                ? (text) => onEdit(message.serverId!, text)
                : undefined
            }
          />
        ))}
      </div>
    </div>
  )
}
