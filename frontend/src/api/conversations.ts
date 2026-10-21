import { toApiError } from './errors'
import type { Conversation, ConversationWithMessages } from './types'

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(path, init)
  if (!response.ok) throw await toApiError(response)
  return response.status === 204 ? (undefined as T) : ((await response.json()) as T)
}

const json = (method: string, body: object): RequestInit => ({
  method,
  headers: { 'content-type': 'application/json' },
  body: JSON.stringify(body),
})

const url = (id: string) => `/api/conversations/${encodeURIComponent(id)}`

export const listConversations = async (signal?: AbortSignal) =>
  (await request<{ conversations: Conversation[] }>('/api/conversations', { signal })).conversations

export const createConversation = (body: { model?: string; thinking: boolean }) =>
  request<Conversation>('/api/conversations', json('POST', body))

export const getConversation = (id: string, signal?: AbortSignal) =>
  request<ConversationWithMessages>(url(id), { signal })

export const updateConversation = (
  id: string,
  body: { title?: string; model?: string; thinking?: boolean },
) => request<Conversation>(url(id), json('PATCH', body))

export const deleteConversation = (id: string) => request<void>(url(id), { method: 'DELETE' })
