import { useState } from 'react'
import type { StatsRange, StatsResponse, StatsSummary } from '../api/types'
import { useStats } from '../hooks/useStats'

const RANGES: { value: StatsRange; label: string }[] = [
  { value: 'today', label: 'Today' },
  { value: '7d', label: '7 days' },
  { value: '30d', label: '30 days' },
  { value: 'all', label: 'All time' },
]

const seconds = (ms: number | null) => (ms === null ? '–' : `${(ms / 1000).toFixed(1)} s`)
const count = (n: number) => n.toLocaleString('en-US')

function Card({ label, value, note }: { label: string; value: string; note?: string }) {
  return (
    <div className="stat-card">
      <dt>{label}</dt>
      <dd>{value}</dd>
      {note && <small>{note}</small>}
    </div>
  )
}

function timing(summary: StatsSummary): { value: string; note?: string } {
  if (summary.count === 0) return { value: '–' }
  return {
    value: seconds(summary.avg),
    note: `median ${seconds(summary.p50)} · slowest 5% above ${seconds(summary.p95)}`,
  }
}

function Chart({ days }: { days: StatsResponse['per_day'] }) {
  const peak = Math.max(1, ...days.map((d) => d.answers))
  const total = days.reduce((sum, d) => sum + d.answers, 0)
  return (
    <figure className="stat-chart">
      <figcaption>Answers per day</figcaption>
      <div
        className="bars"
        role="img"
        aria-label={`Answers per day: ${total} in ${days.length} days, most in one day ${peak}`}
      >
        {days.map((d) => (
          <div
            key={d.date}
            className="bar"
            title={`${d.date}: ${d.answers} ${d.answers === 1 ? 'answer' : 'answers'}`}
            style={{ height: `${(d.answers / peak) * 100}%` }}
          />
        ))}
      </div>
      <div className="bar-axis">
        <span>{days[0]?.date}</span>
        <span>{days.at(-1)?.date}</span>
      </div>
    </figure>
  )
}

export function StatsPage({ onBack, onOpenChat }: { onBack: () => void; onOpenChat: (id: string) => void }) {
  const [range, setRange] = useState<StatsRange>('7d')
  const { data, error, loading } = useStats(range)
  const answers = data?.answers.complete ?? 0

  return (
    <div className="app stats">
      <header className="header">
        <button type="button" className="ghost" onClick={onBack}>
          ← Back to chat
        </button>
        <h1>Usage</h1>
        <div className="spacer" />
        <div className="range" role="group" aria-label="Time range">
          {RANGES.map((r) => (
            <button
              key={r.value}
              type="button"
              className="ghost"
              aria-pressed={range === r.value}
              onClick={() => setRange(r.value)}
            >
              {r.label}
            </button>
          ))}
        </div>
      </header>
      <div className="stats-body" aria-busy={loading}>
        {error && (
          <p className="notice error" role="alert">
            Could not load the figures: {error}
          </p>
        )}
        {!data && !error && <p className="notice">Loading…</p>}
        {data && (
          <>
            <p className="docs-help">
              Counted from the answers stored on this computer. LiteLLM&apos;s own spend log covers everything the team
              uses.
            </p>
            {answers === 0 && data.answers.stopped + data.answers.failed === 0 ? (
              <p className="notice">No answers in this range yet.</p>
            ) : (
              <>
                <dl className="stat-grid">
                  <Card
                    label="Answers"
                    value={count(answers)}
                    note={`${count(data.conversations)} chats · ${data.answers.stopped} stopped · ${data.answers.failed} failed`}
                  />
                  <Card label="Answer tokens" value={count(data.tokens.completion)} note="written by the model" />
                  <Card
                    label="Prompt tokens"
                    value={count(data.tokens.prompt)}
                    note="read by the model, history included"
                  />
                  <Card label="Response time" {...timing(data.latency_ms)} />
                  <Card label="Time to first token" {...timing(data.ttft_ms)} />
                  <Card
                    label="Thinking time"
                    {...(data.thinking_ms.count === 0
                      ? { value: '–', note: 'no answer with thinking' }
                      : { value: seconds(data.thinking_ms.avg), note: `in ${count(data.thinking_ms.count)} answers` })}
                  />
                  <Card
                    label="Speed"
                    value={data.tokens_per_second === null ? '–' : `${data.tokens_per_second} tokens/s`}
                    note="answer tokens per second, thinking included"
                  />
                </dl>
                <Chart days={data.per_day} />
                {data.slowest.length > 0 && (
                  <section className="slowest">
                    <h2>Slowest answers</h2>
                    <ol>
                      {data.slowest.map((s) => (
                        <li key={s.message_id}>
                          <button type="button" className="ghost" onClick={() => onOpenChat(s.conversation_id)}>
                            {s.title}
                          </button>
                          <span>
                            {seconds(s.latency_ms)}
                            {s.completion_tokens !== null && ` · ${count(s.completion_tokens)} tokens`} ·{' '}
                            {new Date(s.created_at).toLocaleString()}
                          </span>
                        </li>
                      ))}
                    </ol>
                  </section>
                )}
              </>
            )}
          </>
        )}
      </div>
    </div>
  )
}
