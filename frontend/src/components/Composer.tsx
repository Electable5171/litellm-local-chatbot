import { useEffect, useRef, useState, type KeyboardEvent } from 'react'

interface Props {
  busy: boolean
  /** Returns true when the message was accepted. */
  onSend: (text: string) => boolean
  onStop: () => void
  /** How many documents this chat uses, and the button that opens the document panel. */
  documentCount: number
  onDocuments: () => void
}

export function Composer({ busy, onSend, onStop, documentCount, onDocuments }: Props) {
  const [text, setText] = useState('')
  const input = useRef<HTMLTextAreaElement>(null)

  useEffect(() => {
    const element = input.current
    if (!element) return
    element.style.height = 'auto'
    element.style.height = `${Math.min(element.scrollHeight, 200)}px`
  }, [text])

  const submit = () => {
    if (onSend(text)) setText('')
  }
  const onKeyDown = (event: KeyboardEvent<HTMLTextAreaElement>) => {
    if (event.key === 'Enter' && !event.shiftKey && !event.nativeEvent.isComposing) {
      event.preventDefault()
      submit()
    }
  }

  return (
    <form
      className="composer"
      onSubmit={(event) => {
        event.preventDefault()
        submit()
      }}
    >
      <button type="button" className="ghost docs-button" onClick={onDocuments}>
        Documents{documentCount > 0 ? ` (${documentCount})` : ''}
      </button>
      <textarea
        ref={input}
        value={text}
        rows={1}
        placeholder="Message the model (Enter to send, Shift+Enter for a new line)"
        aria-label="Message"
        onChange={(event) => setText(event.target.value)}
        onKeyDown={onKeyDown}
        autoFocus
      />
      {busy ? (
        <button type="button" className="stop" onClick={onStop}>
          Stop
        </button>
      ) : (
        <button type="submit" className="send" disabled={text.trim() === ''}>
          Send
        </button>
      )}
    </form>
  )
}
