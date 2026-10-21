import { useState } from 'react'

interface Props {
  reasoning: string
  /** True while the model is still thinking (no answer text yet). */
  active: boolean
  thinkingMs?: number
}

/** The model's reasoning: open while it thinks, folded away when the answer starts. */
export function ThinkingBlock({ reasoning, active, thinkingMs }: Props) {
  const [userOpen, setUserOpen] = useState<boolean | null>(null)
  const open = userOpen ?? active
  const label = active
    ? 'Thinking…'
    : thinkingMs !== undefined
      ? `Thought for ${(thinkingMs / 1000).toFixed(1)} s`
      : 'Thinking'
  return (
    <details
      className="thinking"
      open={open}
      onToggle={(event) => {
        if (event.currentTarget.open !== open) setUserOpen(event.currentTarget.open)
      }}
    >
      <summary>
        {active && <span className="spinner" aria-hidden="true" />}
        {label}
      </summary>
      <div className="thinking-text">{reasoning}</div>
    </details>
  )
}
