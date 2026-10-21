import { toApiError } from './errors'
import { parseSse } from './sse'
import type { ChatEvent, Health, ModelsResponse } from './types'

/**
 * Stream the answer to a new question, or a new answer to the last question ('regenerate').
 * Failures before the first event (model busy, key rejected, message too long, ...) are thrown as
 * ApiError; failures after the stream has started arrive as an 'error' event. Aborting the signal
 * closes the connection, which also stops the model; the server keeps the text written so far.
 */
export async function* streamTurn(
  conversationId: string,
  turn: { kind: 'message'; content: string } | { kind: 'regenerate' },
  signal: AbortSignal,
): AsyncGenerator<ChatEvent> {
  const base = `/api/conversations/${encodeURIComponent(conversationId)}`
  const response =
    turn.kind === 'message'
      ? await fetch(`${base}/messages`, {
          method: 'POST',
          headers: { 'content-type': 'application/json' },
          body: JSON.stringify({ content: turn.content }),
          signal,
        })
      : await fetch(`${base}/regenerate`, { method: 'POST', signal })
  if (!response.ok || !response.body) throw await toApiError(response)
  for await (const message of parseSse(response.body)) {
    yield { type: message.event, ...JSON.parse(message.data) } as ChatEvent
  }
}

async function getJson<T>(path: string, signal?: AbortSignal): Promise<T> {
  const response = await fetch(path, { signal })
  if (!response.ok) throw await toApiError(response)
  return (await response.json()) as T
}

export const getHealth = (signal?: AbortSignal) => getJson<Health>('/api/health', signal)
export const getModels = (signal?: AbortSignal) => getJson<ModelsResponse>('/api/models', signal)
