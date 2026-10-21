import type { ChatEvent, Role } from '../api/types'

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
  role: 'user' | 'assistant'
  content: string
  reasoning: string
  status: MessageStatus
  startedAt: number
  /** How long the model thought before its first answer word. */
  thinkingMs?: number
  /** Older messages the server left out to fit the context budget. */
  trimmed: number
  error?: MessageError
  stats?: MessageStats
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
  | { type: 'dropLastAssistant' }
  | { type: 'reset' }

function newAssistant(id: string, now: number): UiMessage {
  return { id, role: 'assistant', content: '', reasoning: '', status: 'streaming', startedAt: now, trimmed: 0 }
}

function withThinkingTime(message: UiMessage, now: number): UiMessage {
  if (message.thinkingMs !== undefined || message.reasoning === '') return message
  return { ...message, thinkingMs: now - message.startedAt }
}

function applyEvent(message: UiMessage, event: ChatEvent, now: number): UiMessage {
  switch (event.type) {
    case 'meta':
      return { ...message, trimmed: event.trimmed_messages }
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
          },
          newAssistant(action.assistantId, action.now),
        ],
      }
    case 'restart':
      return { messages: [...state.messages, newAssistant(action.assistantId, action.now)] }
    case 'events':
      return updateStreaming(state, (m) =>
        action.events.reduce((message, event) => applyEvent(message, event, action.now), m),
      )
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
    case 'reset':
      return initialState
  }
}

export const isBusy = (state: ChatState): boolean => {
  const last = state.messages.at(-1)
  return last?.role === 'assistant' && last.status === 'streaming'
}

/** What to send to the model: questions, and answers that were completed or stopped part-way. */
export function buildHistory(messages: UiMessage[]): { role: Role; content: string }[] {
  return messages
    .filter(
      (m) => m.role === 'user' || (m.content !== '' && (m.status === 'done' || m.status === 'stopped')),
    )
    .map((m) => ({ role: m.role, content: m.content }))
}
