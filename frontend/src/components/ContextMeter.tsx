import type { ContextUsage } from '../api/types'

const tokens = (n: number) => (n >= 1000 ? `${(n / 1000).toFixed(1)}k` : String(n))

/** A thin bar that shows how much of the model's working budget this chat already uses. */
export function ContextMeter({ usage }: { usage: ContextUsage }) {
  if (usage.used === 0) return null
  const level = usage.would_trim > 0 || usage.percent >= 100 ? 'full' : usage.percent >= 75 ? 'warn' : 'ok'
  const shown = Math.min(usage.percent, 100)
  const details = [
    `Instructions ${tokens(usage.parts.instructions)}`,
    `Documents ${tokens(usage.parts.documents)}`,
    ...(usage.parts.summary > 0 ? [`Summary ${tokens(usage.parts.summary)}`] : []),
    `Messages ${tokens(usage.parts.messages)}`,
    `Kept free for the answer ${tokens(usage.reserved_for_answer)}`,
    `Working limit ${tokens(usage.limit)} tokens`,
  ].join(' · ')
  return (
    <div className={`context-meter ${level}`} title={details}>
      <div
        className="context-bar"
        role="meter"
        aria-label="Context used"
        aria-valuemin={0}
        aria-valuemax={100}
        aria-valuenow={shown}
      >
        <div style={{ width: `${shown}%` }} />
      </div>
      <span>
        {usage.percent > 100 ? 'Context full' : `Context ${usage.percent}%`} · {tokens(usage.used)} of{' '}
        {tokens(usage.budget)} tokens
      </span>
      {usage.summary && (
        <details className="context-summary">
          <summary>
            {usage.summarized === 1 ? '1 earlier message is' : `${usage.summarized} earlier messages are`} sent to the
            model as a summary
          </summary>
          <p>{usage.summary}</p>
        </details>
      )}
      {usage.would_trim > 0 && (
        <span className="context-warning" role="status">
          {usage.would_trim === 1 ? '1 older message' : `${usage.would_trim} older messages`} will be left out of the next
          request. Start a new chat or raise CONTEXT_BUDGET_TOKENS.
        </span>
      )}
    </div>
  )
}
