import { toApiError } from './errors'
import type { DocumentInfo } from './types'

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(path, init)
  if (!response.ok) throw await toApiError(response)
  return response.status === 204 ? (undefined as T) : ((await response.json()) as T)
}

export const listDocuments = async (signal?: AbortSignal) =>
  (await request<{ documents: DocumentInfo[] }>('/api/documents', { signal })).documents

/** The file is sent as the request body. Other web pages cannot send this content type unasked. */
export const uploadDocument = (file: File) =>
  request<DocumentInfo>('/api/documents', {
    method: 'POST',
    headers: {
      'content-type': 'application/octet-stream',
      'x-filename': encodeURIComponent(file.name),
    },
    body: file,
  })

export const deleteDocument = (id: string) =>
  request<void>(`/api/documents/${encodeURIComponent(id)}`, {
    method: 'DELETE',
  })

const attached = (conversationId: string, documentId?: string) =>
  `/api/conversations/${encodeURIComponent(conversationId)}/documents` + (documentId ? `/${encodeURIComponent(documentId)}` : '')

export const listAttached = async (conversationId: string, signal?: AbortSignal) =>
  (
    await request<{ documents: DocumentInfo[] }>(attached(conversationId), {
      signal,
    })
  ).documents

export const attachDocument = (conversationId: string, documentId: string) =>
  request<{ documents: DocumentInfo[] }>(attached(conversationId, documentId), {
    method: 'POST',
  })

export const detachDocument = (conversationId: string, documentId: string) =>
  request<{ documents: DocumentInfo[] }>(attached(conversationId, documentId), {
    method: 'DELETE',
  })
