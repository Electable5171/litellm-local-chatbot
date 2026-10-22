import { useState } from 'react'
import type { Preset } from '../api/types'

interface Props {
  /** The instructions this chat uses now. */
  current: string
  presets: Preset[]
  error: string | null
  locked: boolean
  onClose: () => void
  onUse: (text: string) => void
  onCreate: (name: string, content: string) => Promise<Preset | undefined>
  onUpdate: (id: string, content: string) => void
  onDelete: (id: string) => void
}

export function InstructionsPanel({
  current,
  presets,
  error,
  locked,
  onClose,
  onUse,
  onCreate,
  onUpdate,
  onDelete,
}: Props) {
  const [draft, setDraft] = useState(current)
  const [selected, setSelected] = useState<string | null>(() => presets.find((p) => p.content === current)?.id ?? null)
  const [name, setName] = useState('')
  const [confirming, setConfirming] = useState(false)

  const selectedPreset = presets.find((p) => p.id === selected)
  const active = presets.find((p) => p.content === current)
  const status = current.trim() === '' ? 'None' : active ? active.name : 'Custom'

  return (
    <aside className="docs-panel" role="dialog" aria-label="Instructions">
      <header>
        <h2>Instructions</h2>
        <button type="button" className="ghost" onClick={onClose}>
          Close
        </button>
      </header>
      <p className="docs-help">
        Tell the model how to behave in this chat. The text is copied into the chat, so changing or deleting a preset
        later does not change chats that used it.
      </p>
      <p className="docs-help">
        In use now: <strong>{status}</strong>
      </p>

      <h3 className="panel-title">Presets</h3>
      <ul className="preset-list">
        {presets.map((p) => (
          <li key={p.id}>
            <button
              type="button"
              className={`ghost${selected === p.id ? ' selected' : ''}`}
              aria-pressed={selected === p.id}
              title={p.content}
              onClick={() => {
                setSelected(p.id)
                setDraft(p.content)
                setConfirming(false)
              }}
            >
              {p.name}
            </button>
          </li>
        ))}
      </ul>

      <textarea
        aria-label="Instructions for this chat"
        className="instructions-box"
        value={draft}
        rows={8}
        maxLength={20000}
        placeholder="For example: Answer briefly and in British English."
        onChange={(event) => {
          setDraft(event.target.value)
          if (selectedPreset && event.target.value !== selectedPreset.content) setConfirming(false)
        }}
      />
      <div className="edit-actions">
        <button
          type="button"
          className="ghost"
          onClick={() => {
            setDraft('')
            setSelected(null)
          }}
        >
          Clear text
        </button>
        <button
          type="button"
          className="send"
          disabled={locked || draft.trim() === current.trim()}
          onClick={() => onUse(draft)}
        >
          Use in this chat
        </button>
      </div>
      {locked && <p className="docs-help">An answer is being written; you can change this when it is done.</p>}

      {selectedPreset && (
        <div className="preset-actions">
          <button
            type="button"
            className="ghost small"
            disabled={draft.trim() === '' || draft === selectedPreset.content}
            onClick={() => onUpdate(selectedPreset.id, draft)}
          >
            Update preset “{selectedPreset.name}”
          </button>
          {confirming ? (
            <span>
              Delete this preset?{' '}
              <button
                type="button"
                className="ghost small danger"
                onClick={() => {
                  setConfirming(false)
                  setSelected(null)
                  onDelete(selectedPreset.id)
                }}
              >
                Delete
              </button>{' '}
              <button type="button" className="ghost small" onClick={() => setConfirming(false)}>
                Cancel
              </button>
            </span>
          ) : (
            <button
              type="button"
              className="ghost small"
              aria-label={`Delete preset ${selectedPreset.name}`}
              onClick={() => setConfirming(true)}
            >
              Delete preset
            </button>
          )}
        </div>
      )}

      <form
        className="preset-save"
        onSubmit={(event) => {
          event.preventDefault()
          void onCreate(name, draft).then((made) => {
            if (made) {
              setSelected(made.id)
              setName('')
            }
          })
        }}
      >
        <input
          aria-label="Preset name"
          placeholder="Save the text above as a preset…"
          value={name}
          maxLength={60}
          onChange={(event) => setName(event.target.value)}
        />
        <button type="submit" className="ghost" disabled={name.trim() === '' || draft.trim() === ''}>
          Save as preset
        </button>
      </form>
      {error && (
        <p className="notice error" role="alert">
          {error}
        </p>
      )}
    </aside>
  )
}
