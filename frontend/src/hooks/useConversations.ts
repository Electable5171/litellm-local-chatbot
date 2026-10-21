import { useCallback, useEffect, useRef, useState } from 'react'
import { deleteConversation, listConversations, updateConversation } from '../api/conversations'
import { describeError } from '../api/errors'
import type { Conversation } from '../api/types'

export function useConversations() {
  const [items, setItems] = useState<Conversation[]>([])
  const [error, setError] = useState<string | null>(null)
  const latest = useRef(0)

  const refresh = useCallback(async () => {
    const ticket = ++latest.current
    try {
      const list = await listConversations()
      if (ticket === latest.current) {
        setItems(list)
        setError(null)
      }
    } catch (e) {
      if (ticket === latest.current) setError(describeError(e).message)
    }
  }, [])

  useEffect(() => {
    const controller = new AbortController()
    listConversations(controller.signal)
      .then(setItems)
      .catch((e: unknown) => {
        if (!controller.signal.aborted) setError(describeError(e).message)
      })
    return () => controller.abort()
  }, [])

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

  return { items, error, refresh, rename, remove }
}
