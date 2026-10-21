import { useEffect, useState } from 'react'
import { getHealth, getModels } from '../api/chat'
import { describeError } from '../api/errors'
import type { Health, ModelsResponse } from '../api/types'

export interface HealthState {
  health?: Health
  error?: string
}

/** Poll the backend's health so the header can show whether the model is reachable. */
export function useHealth(intervalMs = 30_000): HealthState {
  const [state, setState] = useState<HealthState>({})
  useEffect(() => {
    const controller = new AbortController()
    const check = async () => {
      try {
        setState({ health: await getHealth(controller.signal) })
      } catch (error) {
        if (!controller.signal.aborted) setState({ error: describeError(error).message })
      }
    }
    void check()
    const timer = setInterval(() => void check(), intervalMs)
    return () => {
      controller.abort()
      clearInterval(timer)
    }
  }, [intervalMs])
  return state
}

export function useModels(): ModelsResponse | undefined {
  const [models, setModels] = useState<ModelsResponse>()
  useEffect(() => {
    const controller = new AbortController()
    getModels(controller.signal)
      .then(setModels)
      .catch(() => undefined) // the health badge already explains an unreachable backend
    return () => controller.abort()
  }, [])
  return models
}
