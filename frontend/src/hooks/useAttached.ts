import { useCallback, useEffect, useRef, useState } from 'react'
import { attachDocument, detachDocument, listAttached } from '../api/documents'
import { describeError } from '../api/errors'

interface State {
  forId: string | null
  ids: string[]
}

/**
 * The documents used in the open chat. A new chat (no id yet) keeps its choice here until the
 * first question is sent; then the chat is saved and the documents are attached to it.
 */
export function useAttached(conversationId: string | null) {
  const [state, setState] = useState<State>({ forId: null, ids: [] })
  const [error, setError] = useState<string | null>(null)
  const idRef = useRef(conversationId)

  useEffect(() => {
    idRef.current = conversationId
  })

  const ids = state.forId === conversationId ? state.ids : []

  useEffect(() => {
    if (conversationId === null || state.forId === conversationId) return
    const controller = new AbortController()
    listAttached(conversationId, controller.signal)
      .then((docs) => setState({ forId: conversationId, ids: docs.map((d) => d.id) }))
      .catch((e: unknown) => {
        if (!controller.signal.aborted) setError(describeError(e).message)
      })
    return () => controller.abort()
  }, [conversationId, state.forId])

  const toggle = useCallback(
    async (documentId: string) => {
      const id = idRef.current
      const current = state.forId === id ? state.ids : []
      const on = !current.includes(documentId)
      setError(null)
      if (id === null) {
        setState({
          forId: null,
          ids: on ? [...current, documentId] : current.filter((d) => d !== documentId),
        })
        return
      }
      try {
        const docs = await (on ? attachDocument(id, documentId) : detachDocument(id, documentId))
        setState({ forId: id, ids: docs.documents.map((d) => d.id) })
      } catch (e) {
        setError(describeError(e).message)
      }
    },
    [state],
  )

  /** The new chat was saved with these documents: keep showing them under its id. */
  const adopt = useCallback((id: string) => setState((s) => ({ forId: id, ids: s.ids })), [])

  /** Forget a document that was deleted. */
  const forget = useCallback((documentId: string) => setState((s) => ({ ...s, ids: s.ids.filter((d) => d !== documentId) })), [])

  return { ids, error, toggle, adopt, forget }
}
