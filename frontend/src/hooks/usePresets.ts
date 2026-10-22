import { useCallback, useEffect, useState } from 'react'
import { createPreset, deletePreset, listPresets, updatePreset } from '../api/presets'
import { describeError } from '../api/errors'
import type { Preset } from '../api/types'

export function usePresets() {
  const [items, setItems] = useState<Preset[]>([])
  const [error, setError] = useState<string | null>(null)

  const refresh = useCallback(async () => {
    try {
      setItems(await listPresets())
    } catch (e) {
      setError(describeError(e).message)
    }
  }, [])

  useEffect(() => {
    const controller = new AbortController()
    listPresets(controller.signal)
      .then(setItems)
      .catch((e: unknown) => {
        if (!controller.signal.aborted) setError(describeError(e).message)
      })
    return () => controller.abort()
  }, [])

  /** Run a change, then reload the list. Returns the saved preset (or nothing on failure). */
  const change = useCallback(
    async <T>(action: () => Promise<T>): Promise<T | undefined> => {
      setError(null)
      try {
        const result = await action()
        await refresh()
        return result
      } catch (e) {
        setError(describeError(e).message)
        return undefined
      }
    },
    [refresh],
  )

  return {
    items,
    error,
    create: (name: string, content: string) => change(() => createPreset(name, content)),
    update: (id: string, content: string) => change(() => updatePreset(id, { content })),
    remove: (id: string) => change(() => deletePreset(id)),
  }
}
