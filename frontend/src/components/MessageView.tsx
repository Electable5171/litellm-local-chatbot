import type { MessageError, UiMessage } from '../state/chatReducer'
import { Markdown, useCopy } from './Markdown'
import { ThinkingBlock } from './ThinkingBlock'

function explain(error: MessageError): string {
  switch (error.code) {
    case 'upstream_busy':
      return 'The model is busy right now. Try again in a few seconds.'
    case 'context_too_long':
      return 'The conversation is too long for the model. Start a new chat or shorten your message.'
    case 'upstream_unreachable':
      return 'The app cannot reach the model server. Check your network.'
    default:
      return error.message
  }
}

function Footer({ message }: { message: UiMessage }) {
  const { copied, copy } = useCopy()
  const { stats } = message
  if (message.status === 'streaming') return null
  const parts: string[] = []
  if (stats?.completionTokens != null) parts.push(`${stats.completionTokens} tokens`)
  if (stats) parts.push(`${(stats.latencyMs / 1000).toFixed(1)} s`)
  if (stats?.ttftMs != null) parts.push(`first token ${(stats.ttftMs / 1000).toFixed(1)} s`)
  return (
    <footer className="meta">
      {message.status === 'stopped' && <span className="note">Stopped</span>}
      {stats?.finishReason === 'length' && (
        <span className="note">Cut off at the output limit (thinking counts towards it)</span>
      )}
      {message.trimmed > 0 && (
        <span className="note">{message.trimmed} older messages left out to fit the model</span>
      )}
      {parts.length > 0 && <span>{parts.join(' · ')}</span>}
      {message.content && (
        <button type="button" className="ghost small" onClick={() => copy(message.content)}>
          {copied ? 'Copied' : 'Copy answer'}
        </button>
      )}
    </footer>
  )
}

interface Props {
  message: UiMessage
  isLast: boolean
  onRetry: () => void
}

export function MessageView({ message, isLast, onRetry }: Props) {
  if (message.role === 'user') {
    return (
      <article className="msg user">
        <div className="bubble">{message.content}</div>
      </article>
    )
  }
  const streaming = message.status === 'streaming'
  const thinking = streaming && message.content === ''
  const canRetry = isLast && (message.status === 'error' || message.status === 'stopped')
  return (
    <article className="msg assistant" aria-busy={streaming}>
      {message.reasoning && (
        <ThinkingBlock reasoning={message.reasoning} active={thinking} thinkingMs={message.thinkingMs} />
      )}
      {thinking && !message.reasoning && <p className="waiting">Waiting for the model…</p>}
      {message.content && <Markdown text={message.content} />}
      {message.error && (
        <div className="error" role="alert">
          {explain(message.error)}
        </div>
      )}
      <Footer message={message} />
      {canRetry && (
        <button type="button" className="ghost" onClick={onRetry}>
          Try again
        </button>
      )}
    </article>
  )
}
