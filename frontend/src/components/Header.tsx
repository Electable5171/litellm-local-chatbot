import type { HealthState } from '../hooks/useServer'
import type { ModelsResponse } from '../api/types'

interface Props {
  server: HealthState
  models?: ModelsResponse
  model?: string
  onModel: (model: string) => void
  thinking: boolean
  onThinking: (on: boolean) => void
  onMenu: () => void
  busy: boolean
}

function status(server: HealthState): { tone: 'ok' | 'warn' | 'bad' | 'wait'; text: string } {
  if (server.error) return { tone: 'bad', text: server.error }
  const health = server.health
  if (!health) return { tone: 'wait', text: 'Checking…' }
  if (health.status === 'ok') {
    const ms = health.litellm.latency_ms
    return { tone: 'ok', text: ms == null ? 'Ready' : `Ready · ${ms} ms` }
  }
  return {
    tone: 'warn',
    text: health.litellm.error ?? `${health.chat_model.id} is not available`,
  }
}

export function Header({ server, models, model, onModel, thinking, onThinking, onMenu, busy }: Props) {
  const state = status(server)
  return (
    <header className="header">
      <button type="button" className="ghost menu" onClick={onMenu} aria-label="Show chats">
        Chats
      </button>
      <h1>Local Chat</h1>
      <span className={`status ${state.tone}`} role="status">
        <span className="dot" aria-hidden="true" />
        {state.text}
      </span>
      <div className="spacer" />
      {models && models.models.length > 1 && (
        <select aria-label="Model" value={model} onChange={(event) => onModel(event.target.value)} disabled={busy}>
          {models.models.map((m) => (
            <option key={m.id} value={m.id} disabled={!m.available}>
              {m.id}
              {m.available ? '' : ' (unavailable)'}
            </option>
          ))}
        </select>
      )}
      <label className="switch">
        <input
          type="checkbox"
          role="switch"
          checked={thinking}
          onChange={(event) => onThinking(event.target.checked)}
          disabled={busy}
        />
        <span>Thinking</span>
      </label>
    </header>
  )
}
