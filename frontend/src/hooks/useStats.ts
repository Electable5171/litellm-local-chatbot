import { useEffect, useState } from 'react'
import { describeError } from '../api/errors'
import { getStats } from '../api/stats'
import type { StatsRange, StatsResponse } from '../api/types'

/** The usage figures for a range. `loading` is true while the figures on screen are for another range. */
export function useStats(range: StatsRange) {
  const [state, setState] = useState<{ range: StatsRange; data?: StatsResponse; error?: string } | null>(null)

  useEffect(() => {
    const controller = new AbortController()
    getStats(range, controller.signal)
      .then((data) => setState({ range, data }))
      .catch((error: unknown) => {
        if (!controller.signal.aborted) setState({ range, error: describeError(error).message })
      })
    return () => controller.abort()
  }, [range])

  const current = state?.range === range ? state : null
  return { data: current?.data ?? state?.data, error: current?.error, loading: current === null }
}
