import type { ChatEvent, SourcesInfo, StoredMessage } from '../api/types'

export type MessageStatus = 'streaming' | 'done' | 'stopped' | 'error'

export interface MessageError {
  code: string
  message: string
  retryAfterS?: number
}

export interface MessageStats {
  completionTokens: number | null
  latencyMs: number
  ttftMs: number | null
  finishReason: string | null
}

export interface UiMessage {
  id: string
  /** The id the server gave this message (known once it is saved); needed to edit it. */
  serverId?: string
  role: 'user' | 'assistant'
  content: string
  reasoning: string
  status: MessageStatus
  startedAt: number
  /** How long the model thought before its first answer word. */
  thinkingMs?: number
  /** Older messages the server left out to fit the context budget. */
  trimmed: number
  /** True once the server has stored this answer; retrying then asks the server to redo it. */
  saved: boolean
  error?: MessageError
  stats?: MessageStats
  /** The document parts the answer was based on, when documents were attached. */
  sources?: SourcesInfo
}

export interface ChatState {
  messages: UiMessage[]
}

export const initialState: ChatState = { messages: [] }

export type ChatAction =
  | { type: 'send'; userId: string; assistantId: string; text: string; now: number }
  | { type: 'restart'; assistantId: string; now: number }
  | { type: 'events'; events: ChatEvent[]; now: number }
  | { type: 'fail'; error: MessageError; now: number }
  | { type: 'stop'; now: number }
  | { type: 'edit'; index: number; userId: string; assistantId: string; text: string; now: number }
  | { type: 'dropLastAssistant' }
  | { type: 'dropLastTurn' }
  | { type: 'load'; messages: UiMessage[] }
  | { type: 'reset' }

function newAssistant(id: string, now: number): UiMessage {
  return { id, role: 'assistant', content: '', reasoning: '', status: 'streaming', startedAt: now, trimmed: 0, saved: false }
}

function withThinkingTime(message: UiMessage, now: number): UiMessage {
  if (message.thinkingMs !== undefined || message.reasoning === '') return message
  return { ...message, thinkingMs: now - message.startedAt }
}

function applyEvent(message: UiMessage, event: ChatEvent, now: number): UiMessage {
  switch (event.type) {
    case 'meta':
      return { ...message, trimmed: event.trimmed_messages, saved: true }
    case 'sources':
      return { ...message, sources: { mode: event.mode, sources: event.sources, skipped: event.skipped } }
    case 'reasoning':
      return { ...message, reasoning: message.reasoning + event.delta }
    case 'content': {
      const started = message.content === '' ? withThinkingTime(message, now) : message
      return { ...started, content: started.content + event.delta }
    }
    case 'done':
      return {
        ...withThinkingTime(message, now),
        status: 'done',
        stats: {
          completionTokens: event.usage?.completion_tokens ?? null,
          latencyMs: event.latency_ms,
          ttftMs: event.ttft_ms,
          finishReason: event.finish_reason,
        },
      }
    case 'error':
      return {
        ...withThinkingTime(message, now),
        status: 'error',
        error: { code: event.code, message: event.message, retryAfterS: event.retry_after_s },
      }
  }
}

function updateStreaming(state: ChatState, change: (m: UiMessage) => UiMessage): ChatState {
  const last = state.messages.at(-1)
  if (!last || last.role !== 'assistant' || last.status !== 'streaming') return state
  return { messages: [...state.messages.slice(0, -1), change(last)] }
}

export function chatReducer(state: ChatState, action: ChatAction): ChatState {
  switch (action.type) {
    case 'send':
      return {
        messages: [
          ...state.messages,
          {
            id: action.userId,
            role: 'user',
            content: action.text,
            reasoning: '',
            status: 'done',
            startedAt: action.now,
            trimmed: 0,
            saved: false,
          },
          newAssistant(action.assistantId, action.now),
        ],
      }
    case 'restart':
      return { messages: [...state.messages, newAssistant(action.assistantId, action.now)] }
    case 'events': {
      const next = updateStreaming(state, (m) =>
        action.events.reduce((message, event) => applyEvent(message, event, action.now), m),
      )
      // The first event tells which id the server gave the question that was just sent.
      const meta = action.events.find((e) => e.type === 'meta')
      const question = next.messages.at(-2)
      if (meta?.type === 'meta' && meta.user_message_id && question?.role === 'user') {
        return {
          messages: [...next.messages.slice(0, -2), { ...question, serverId: meta.user_message_id }, next.messages.at(-1)!],
        }
      }
      return next
    }
    case 'edit':
      return {
        messages: [
          ...state.messages.slice(0, action.index),
          {
            id: action.userId,
            role: 'user',
            content: action.text,
            reasoning: '',
            status: 'done',
            startedAt: action.now,
            trimmed: 0,
            saved: false,
          },
          newAssistant(action.assistantId, action.now),
        ],
      }
    case 'fail':
      return updateStreaming(state, (m) => ({
        ...withThinkingTime(m, action.now),
        status: 'error',
        error: action.error,
      }))
    case 'stop':
      return updateStreaming(state, (m) => ({ ...withThinkingTime(m, action.now), status: 'stopped' }))
    case 'dropLastAssistant': {
      const last = state.messages.at(-1)
      if (!last || last.role !== 'assistant' || last.status === 'streaming') return state
      return { messages: state.messages.slice(0, -1) }
    }
    case 'dropLastTurn': {
      const [question, answer] = state.messages.slice(-2)
      if (question?.role !== 'user' || answer?.role !== 'assistant' || answer.status === 'streaming') {
        return state
      }
      return { messages: state.messages.slice(0, -2) }
    }
    case 'load':
      return { messages: action.messages }
    case 'reset':
      return initialState
  }
}

export const isBusy = (state: ChatState): boolean => {
  const last = state.messages.at(-1)
  return last?.role === 'assistant' && last.status === 'streaming'
}

const STATUS: Record<StoredMessage['status'], MessageStatus> = {
  complete: 'done',
  cancelled: 'stopped',
  error: 'error',
  streaming: 'stopped', // another window may still be writing it; it cannot be followed from here
}

/** A message loaded from the server. */
export function fromStored(m: StoredMessage): UiMessage {
  const startedAt = Date.parse(m.created_at)
  const hasStats = m.latency_ms !== null || m.usage !== null
  return {
    id: m.id,
    serverId: m.id,
    role: m.role,
    content: m.content,
    reasoning: m.reasoning,
    status: STATUS[m.status],
    startedAt: Number.isNaN(startedAt) ? 0 : startedAt,
    thinkingMs: m.thinking_ms ?? undefined,
    trimmed: m.trimmed ? 1 : 0,
    saved: true,
    sources: m.sources ?? undefined,
    error: m.error ? { code: m.error.code, message: m.error.message } : undefined,
    stats: hasStats
      ? {
          completionTokens: m.usage?.completion_tokens ?? null,
          latencyMs: m.latency_ms ?? 0,
          ttftMs: m.ttft_ms,
          finishReason: m.finish_reason,
        }
      : undefined,
  }
}
