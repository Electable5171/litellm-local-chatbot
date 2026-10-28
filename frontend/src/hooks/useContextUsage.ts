import { useEffect, useState } from 'react'
import { getContextUsage } from '../api/conversations'
import type { ContextUsage } from '../api/types'

/**
 * How full the open chat is. It is read again whenever `refreshKey` changes (an answer finished, a
 * document was attached, the instructions changed). A failure just hides the indicator.
 */
export function useContextUsage(conversationId: string | null, refreshKey: string): ContextUsage | null {
  const [state, setState] = useState<{ id: string; usage: ContextUsage } | null>(null)

  useEffect(() => {
    if (conversationId === null) return
    const controller = new AbortController()
    getContextUsage(conversationId, controller.signal)
      .then((usage) => setState({ id: conversationId, usage }))
      .catch(() => undefined)
    return () => controller.abort()
  }, [conversationId, refreshKey])

  return state !== null && state.id === conversationId ? state.usage : null
}
