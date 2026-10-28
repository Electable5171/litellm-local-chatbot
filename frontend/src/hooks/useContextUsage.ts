import { useEffect, useState } from 'react'
import { getContextUsage } from '../api/conversations'
import type { ContextUsage } from '../api/types'

/** A summary is written in the background after an answer; look again once for it. */
export const SUMMARY_RECHECK_MS = 6000
const SUMMARY_FROM_PERCENT = 70

/**
 * How full the open chat is. It is read again whenever `refreshKey` changes (an answer finished, a
 * document was attached, the instructions changed). A failure just hides the indicator.
 */
export function useContextUsage(conversationId: string | null, refreshKey: string): ContextUsage | null {
  const [state, setState] = useState<{ id: string; usage: ContextUsage } | null>(null)

  useEffect(() => {
    if (conversationId === null) return
    const controller = new AbortController()
    let timer: ReturnType<typeof setTimeout> | undefined
    const read = (again: boolean) =>
      getContextUsage(conversationId, controller.signal)
        .then((usage) => {
          setState({ id: conversationId, usage })
          if (again && usage.percent >= SUMMARY_FROM_PERCENT && usage.summary === null) {
            timer = setTimeout(() => void read(false), SUMMARY_RECHECK_MS)
          }
        })
        .catch(() => undefined)
    void read(true)
    return () => {
      controller.abort()
      clearTimeout(timer)
    }
  }, [conversationId, refreshKey])

  return state !== null && state.id === conversationId ? state.usage : null
}
