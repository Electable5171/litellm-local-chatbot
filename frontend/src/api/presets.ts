import { toApiError } from './errors'
import type { Preset } from './types'

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

export const listPresets = async (signal?: AbortSignal) =>
  (await request<{ presets: Preset[] }>('/api/presets', { signal })).presets

export const createPreset = (name: string, content: string) =>
  request<Preset>('/api/presets', json('POST', { name, content }))

export const updatePreset = (id: string, body: { name?: string; content?: string }) =>
  request<Preset>(`/api/presets/${encodeURIComponent(id)}`, json('PATCH', body))

export const deletePreset = (id: string) =>
  request<void>(`/api/presets/${encodeURIComponent(id)}`, { method: 'DELETE' })
