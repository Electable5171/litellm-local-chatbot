export type Role = 'user' | 'assistant' | 'system'

export interface ChatRequestBody {
  messages: { role: Role; content: string }[]
  model?: string
  thinking: boolean
  max_tokens?: number
}

export interface Usage {
  prompt_tokens: number
  completion_tokens: number
}

/** One server-sent event from POST /api/chat. */
export type ChatEvent =
  | { type: 'meta'; model: string; thinking: boolean; trimmed_messages: number }
  | { type: 'reasoning'; delta: string }
  | { type: 'content'; delta: string }
  | {
      type: 'done'
      finish_reason: string | null
      usage: Usage | null
      latency_ms: number
      ttft_ms: number | null
    }
  | { type: 'error'; code: string; message: string; retry_after_s?: number }

export interface Health {
  status: 'ok' | 'degraded'
  version: string
  litellm: {
    base_url: string
    reachable: boolean
    latency_ms: number | null
    error: string | null
    checked_age_s: number
  }
  chat_model: { id: string; available: boolean | null }
}

export interface ModelsResponse {
  default: string
  models: { id: string; available: boolean }[]
}
