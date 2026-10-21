import { useCallback, useEffect, useState } from 'react'
import { deleteDocument, listDocuments, uploadDocument } from '../api/documents'
import { describeError } from '../api/errors'
import type { DocumentInfo } from '../api/types'

const POLL_MS = 2000

/** All uploaded documents. While one is being read and embedded, the list refreshes itself. */
export function useDocuments() {
  const [items, setItems] = useState<DocumentInfo[]>([])
  const [problems, setProblems] = useState<string[]>([])
  const [uploading, setUploading] = useState<string | null>(null)

  const refresh = useCallback(async () => {
    try {
      setItems(await listDocuments())
    } catch (error) {
      setProblems([describeError(error).message])
    }
  }, [])

  useEffect(() => {
    const controller = new AbortController()
    listDocuments(controller.signal)
      .then(setItems)
      .catch((error: unknown) => {
        if (!controller.signal.aborted) setProblems([describeError(error).message])
      })
    return () => controller.abort()
  }, [])

  const processing = items.some((d) => d.status === 'processing')
  useEffect(() => {
    if (!processing) return
    const timer = setInterval(() => void refresh(), POLL_MS)
    return () => clearInterval(timer)
  }, [processing, refresh])

  /** Upload one after the other (the model is shared). Returns the ids of the documents stored. */
  const upload = useCallback(
    async (files: File[]): Promise<string[]> => {
      const stored: string[] = []
      const failed: string[] = []
      for (const file of files) {
        setUploading(file.name)
        try {
          stored.push((await uploadDocument(file)).id)
        } catch (error) {
          failed.push(`${file.name}: ${describeError(error).message}`)
        }
      }
      setUploading(null)
      setProblems(failed)
      await refresh()
      return stored
    },
    [refresh],
  )

  const remove = useCallback(
    async (id: string) => {
      try {
        await deleteDocument(id)
        setProblems([])
      } catch (error) {
        setProblems([describeError(error).message])
      }
      await refresh()
    },
    [refresh],
  )

  return {
    items,
    problems,
    uploading,
    upload,
    remove,
    refresh,
    dismissProblems: () => setProblems([]),
  }
}
