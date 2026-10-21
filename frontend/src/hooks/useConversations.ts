import { useCallback, useEffect, useRef, useState } from 'react'
import { deleteConversation, listConversations, updateConversation } from '../api/conversations'
import { describeError } from '../api/errors'
import type { Conversation } from '../api/types'

export function useConversations() {
  const [items, setItems] = useState<Conversation[]>([])
  const [error, setError] = useState<string | null>(null)
  const [query, setQuery] = useState('')
  // The search text the list on screen belongs to (it lags behind typing by one request).
  const [shown, setShown] = useState('')
  const queryRef = useRef(query)
  const latest = useRef(0)
  const timers = useRef<ReturnType<typeof setTimeout>[]>([])

  useEffect(() => {
    queryRef.current = query
  })

  const refresh = useCallback(async () => {
    const ticket = ++latest.current
    const asked = queryRef.current.trim()
    try {
      const list = await listConversations(asked)
      if (ticket === latest.current) {
        setItems(list)
        setShown(asked)
        setError(null)
      }
    } catch (e) {
      if (ticket === latest.current) setError(describeError(e).message)
    }
  }, [])

  // Load the list at start, and search a moment after the last key press.
  useEffect(() => {
    const timer = setTimeout(() => void refresh(), query.trim() ? 250 : 0)
    return () => clearTimeout(timer)
  }, [query, refresh])

  useEffect(() => () => timers.current.forEach(clearTimeout), [])

  /**
   * Refresh now, and twice more shortly after: the model writes a better title for a new chat in
   * the background once its first answer is done, which takes a few seconds.
   */
  const refreshSoon = useCallback(() => {
    void refresh()
    timers.current.forEach(clearTimeout)
    timers.current = [3000, 8000].map((ms) => setTimeout(() => void refresh(), ms))
  }, [refresh])

  const rename = useCallback(
    async (id: string, title: string) => {
      try {
        await updateConversation(id, { title })
      } catch (e) {
        setError(describeError(e).message)
      }
      await refresh()
    },
    [refresh],
  )

  const remove = useCallback(
    async (id: string) => {
      try {
        await deleteConversation(id)
      } catch (e) {
        setError(describeError(e).message)
      }
      await refresh()
    },
    [refresh],
  )

  return { items, error, query, shown, setQuery, refresh, refreshSoon, rename, remove }
}
