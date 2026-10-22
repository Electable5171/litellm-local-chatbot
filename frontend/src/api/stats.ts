import { toApiError } from './errors'
import type { StatsRange, StatsResponse } from './types'

export async function getStats(range: StatsRange, signal?: AbortSignal): Promise<StatsResponse> {
  // Days follow this browser's time zone (minutes east of UTC).
  const tz = -new Date().getTimezoneOffset()
  const response = await fetch(`/api/stats?range=${range}&tz=${tz}`, { signal })
  if (!response.ok) throw await toApiError(response)
  return (await response.json()) as StatsResponse
}
