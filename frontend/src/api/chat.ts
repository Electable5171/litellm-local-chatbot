import { toApiError } from './errors'
import { parseSse } from './sse'
import type { ChatEvent, ChatRequestBody, Health, ModelsResponse } from './types'

/**
 * Ask a question and stream the answer. Failures before the first event (model busy, key rejected,
 * message too long, ...) are thrown as ApiError; failures after the stream has started arrive as
 * an 'error' event. Aborting the signal closes the connection, which also stops the model.
 */
export async function* streamChat(
  request: ChatRequestBody,
  signal: AbortSignal,
): AsyncGenerator<ChatEvent> {
  const response = await fetch('/api/chat', {
    method: 'POST',
    headers: { 'content-type': 'application/json' },
    body: JSON.stringify(request),
    signal,
  })
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
