import { useState } from 'react'
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

function Sources({ message }: { message: UiMessage }) {
  const info = message.sources
  if (!info) return null
  const skipped = info.skipped.map((d) => `${d.filename} (${d.status})`)
  if (info.sources.length === 0 && skipped.length === 0) return null
  return (
    <details className="sources">
      <summary>
        {info.sources.length > 0
          ? `Sources (${info.sources.length})${info.mode === 'search' ? ' · best matches' : ''}`
          : 'No document was used'}
      </summary>
      {info.sources.length > 0 && (
        <ol>
          {info.sources.map((s) => (
            <li key={s.n} value={s.n}>
              {s.filename}
              {s.page ? `, page ${s.page}` : ''}
            </li>
          ))}
        </ol>
      )}
      {skipped.length > 0 && <p className="note">Not ready, so not used: {skipped.join(', ')}</p>}
    </details>
  )
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
      {stats?.finishReason === 'length' && <span className="note">Cut off at the output limit (thinking counts towards it)</span>}
      {message.trimmed > 0 && <span className="note">Older messages were left out to fit the model</span>}
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
  /** Present when the message can be edited now (saved, and no answer is being written). */
  onEdit?: (text: string) => void
  /** How many messages follow this one; they are replaced when it is edited. */
  laterCount?: number
}

function UserMessage({ message, onEdit, laterCount = 0 }: Pick<Props, 'message' | 'onEdit' | 'laterCount'>) {
  const [editing, setEditing] = useState(false)
  const [draft, setDraft] = useState(message.content)

  if (editing && onEdit) {
    const changed = draft.trim() !== '' && draft.trim() !== message.content.trim()
    return (
      <article className="msg user editing">
        <textarea
          aria-label="Edit message"
          value={draft}
          rows={Math.min(10, Math.max(2, draft.split('\n').length))}
          autoFocus
          onChange={(event) => setDraft(event.target.value)}
        />
        <p className="note">
          Saving removes {laterCount === 1 ? 'the 1 message' : `the ${laterCount} messages`} after this one and
          writes a new answer.
        </p>
        <div className="edit-actions">
          <button
            type="button"
            className="send"
            disabled={!changed}
            onClick={() => {
              setEditing(false)
              onEdit(draft)
            }}
          >
            Save and answer
          </button>
          <button type="button" className="ghost" onClick={() => setEditing(false)}>
            Cancel
          </button>
        </div>
      </article>
    )
  }
  return (
    <article className="msg user">
      <div className="bubble">{message.content}</div>
      {onEdit && (
        <button
          type="button"
          className="ghost small edit-button"
          onClick={() => {
            setDraft(message.content)
            setEditing(true)
          }}
        >
          Edit
        </button>
      )}
    </article>
  )
}

export function MessageView({ message, isLast, onRetry, onEdit, laterCount }: Props) {
  if (message.role === 'user') {
    return <UserMessage message={message} onEdit={onEdit} laterCount={laterCount} />
  }
  const streaming = message.status === 'streaming'
  const thinking = streaming && message.content === ''
  const canRetry = isLast && (message.status === 'error' || message.status === 'stopped')
  return (
    <article className="msg assistant" aria-busy={streaming}>
      {message.reasoning && <ThinkingBlock reasoning={message.reasoning} active={thinking} thinkingMs={message.thinkingMs} />}
      {thinking && !message.reasoning && <p className="waiting">Waiting for the model…</p>}
      {message.content && <Markdown text={message.content} />}
      {message.error && (
        <div className="error" role="alert">
          {explain(message.error)}
        </div>
      )}
      <Sources message={message} />
      <Footer message={message} />
      {canRetry && (
        <button type="button" className="ghost" onClick={onRetry}>
          Try again
        </button>
      )}
    </article>
  )
}
