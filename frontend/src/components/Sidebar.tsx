import { useState } from 'react'
import type { Conversation } from '../api/types'

interface Props {
  items: Conversation[]
  error: string | null
  query: string
  /** The search text the listed chats belong to; they are replaced a moment after typing. */
  shown: string
  onQuery: (query: string) => void
  activeId: string | null
  busy: boolean
  open: boolean
  onClose: () => void
  onNew: () => void
  /** Open the usage page. */
  onUsage: () => void
  usageActive: boolean
  onSelect: (id: string) => void
  onRename: (id: string, title: string) => void
  onDelete: (id: string) => void
}

const DAY = 24 * 60 * 60 * 1000

/** Group by when the conversation was last used: Today, Yesterday, Previous 7 days, Older. */
export function groupConversations(
  items: Conversation[],
  now = new Date(),
): { label: string; items: Conversation[] }[] {
  const startOfToday = new Date(now.getFullYear(), now.getMonth(), now.getDate()).getTime()
  const groups: { label: string; items: Conversation[] }[] = [
    { label: 'Today', items: [] },
    { label: 'Yesterday', items: [] },
    { label: 'Previous 7 days', items: [] },
    { label: 'Older', items: [] },
  ]
  for (const item of items) {
    const at = Date.parse(item.updated_at)
    const group = at >= startOfToday ? 0 : at >= startOfToday - DAY ? 1 : at >= startOfToday - 7 * DAY ? 2 : 3
    groups[group]!.items.push(item)
  }
  return groups.filter((g) => g.items.length > 0)
}

function Row({
  item,
  active,
  locked,
  onSelect,
  onRename,
  onDelete,
}: {
  item: Conversation
  active: boolean
  locked: boolean
  onSelect: () => void
  onRename: (title: string) => void
  onDelete: () => void
}) {
  const [mode, setMode] = useState<'view' | 'rename' | 'delete'>('view')
  const [draft, setDraft] = useState(item.title)
  const title = item.title || 'New chat'

  if (mode === 'rename') {
    const save = () => {
      const next = draft.trim()
      if (next && next !== item.title) onRename(next)
      setMode('view')
    }
    return (
      <li className="conv editing">
        <input
          aria-label="Chat title"
          value={draft}
          maxLength={200}
          autoFocus
          onChange={(event) => setDraft(event.target.value)}
          onKeyDown={(event) => {
            if (event.key === 'Enter') save()
            if (event.key === 'Escape') setMode('view')
          }}
          onBlur={save}
        />
      </li>
    )
  }

  if (mode === 'delete') {
    return (
      <li className="conv confirm">
        <span>Delete this chat?</span>
        <button
          type="button"
          className="ghost small danger"
          onClick={() => {
            setMode('view')
            onDelete()
          }}
        >
          Delete
        </button>
        <button type="button" className="ghost small" onClick={() => setMode('view')}>
          Cancel
        </button>
      </li>
    )
  }

  return (
    <li className={`conv${active ? ' active' : ''}`}>
      <button
        type="button"
        className="conv-title"
        aria-current={active ? 'true' : undefined}
        disabled={locked && !active}
        onClick={onSelect}
        title={title}
      >
        {title}
        {item.snippet && <small className="snippet">{item.snippet}</small>}
      </button>
      <button
        type="button"
        className="ghost small"
        aria-label={`Rename ${title}`}
        disabled={locked}
        onClick={() => {
          setDraft(item.title)
          setMode('rename')
        }}
      >
        Rename
      </button>
      <button
        type="button"
        className="ghost small"
        aria-label={`Delete ${title}`}
        disabled={locked}
        onClick={() => setMode('delete')}
      >
        Delete
      </button>
    </li>
  )
}

export function Sidebar({
  items,
  error,
  query,
  shown,
  onQuery,
  activeId,
  busy,
  open,
  onClose,
  onNew,
  onUsage,
  usageActive,
  onSelect,
  onRename,
  onDelete,
}: Props) {
  return (
    <>
      {open && <div className="scrim" onClick={onClose} aria-hidden="true" />}
      <nav className={`sidebar${open ? ' open' : ''}`} aria-label="Conversations">
        <button type="button" className="new-chat" onClick={onNew} disabled={busy}>
          New chat
        </button>
        <input
          type="search"
          className="search"
          aria-label="Search chats"
          placeholder="Search chats"
          value={query}
          maxLength={200}
          onChange={(event) => onQuery(event.target.value)}
        />
        {error && (
          <p className="side-note" role="alert">
            Could not load chats: {error}
          </p>
        )}
        {items.length === 0 && !error && (
          <p className="side-note">
            {shown ? 'No chat contains that text.' : 'Your chats are saved here, on this computer.'}
          </p>
        )}
        {(shown ? [{ label: `Results (${items.length})`, items }] : groupConversations(items))
          .filter((group) => group.items.length > 0)
          .map((group) => (
            <section key={group.label}>
              <h2>{group.label}</h2>
              <ul>
                {group.items.map((item) => (
                  <Row
                    key={item.id}
                    item={item}
                    active={item.id === activeId}
                    locked={busy}
                    onSelect={() => onSelect(item.id)}
                    onRename={(title) => onRename(item.id, title)}
                    onDelete={() => onDelete(item.id)}
                  />
                ))}
              </ul>
            </section>
          ))}
        <button
          type="button"
          className="usage-link"
          aria-current={usageActive ? 'page' : undefined}
          onClick={onUsage}
          disabled={busy}
        >
          Usage
        </button>
      </nav>
    </>
  )
}
