export interface Usage {
  prompt_tokens: number
  completion_tokens: number
}

/** One server-sent event while an answer is written. */
export type ChatEvent =
  | {
      type: 'meta'
      model: string
      thinking: boolean
      trimmed_messages: number
      conversation_id?: string
    }
  | ({ type: 'sources' } & SourcesInfo)
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

export interface Conversation {
  id: string
  title: string
  model: string
  thinking: boolean
  system_prompt: string
  created_at: string
  updated_at: string
}

export interface StoredMessage {
  id: string
  role: 'user' | 'assistant'
  content: string
  reasoning: string
  status: 'streaming' | 'complete' | 'cancelled' | 'error'
  error: { code: string; message: string } | null
  finish_reason: string | null
  usage: Usage | null
  latency_ms: number | null
  ttft_ms: number | null
  thinking_ms: number | null
  trimmed: boolean
  sources: SourcesInfo | null
  created_at: string
}

export interface ConversationWithMessages extends Conversation {
  messages: StoredMessage[]
}

/** Which parts of the attached documents an answer was based on. */
export interface SourcesInfo {
  mode: 'full' | 'search' | 'none'
  sources: {
    n: number
    document_id: string
    filename: string
    page: number | null
    score?: number | null
  }[]
  skipped: { document_id: string; filename: string; status: string }[]
}

export interface DocumentInfo {
  id: string
  filename: string
  mime: string
  size_bytes: number
  status: 'processing' | 'ready' | 'error'
  error: string | null
  page_count: number | null
  chunk_count: number
  embedded_count: number
  created_at: string
}
