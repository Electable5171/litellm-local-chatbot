import { useCallback, useEffect, useReducer, useRef } from 'react'
import { streamChat } from '../api/chat'
import { describeError } from '../api/errors'
import type { ChatEvent, ChatRequestBody } from '../api/types'
import { buildHistory, chatReducer, initialState, isBusy } from '../state/chatReducer'

export interface ChatOptions {
  model?: string
  thinking: boolean
}

let counter = 0
const nextId = () => `m${++counter}`

/** Streamed text is applied at most every 50 ms, so long answers do not re-render per token. */
const FLUSH_MS = 50

export function useChat(options: ChatOptions) {
  const [state, dispatch] = useReducer(chatReducer, initialState)
  const stateRef = useRef(state)
  const optionsRef = useRef(options)
  const abortRef = useRef<AbortController | null>(null)

  useEffect(() => {
    stateRef.current = state
    optionsRef.current = options
  })
  useEffect(() => () => abortRef.current?.abort(), [])

  const run = useCallback(async (history: ChatRequestBody['messages']) => {
    const controller = new AbortController()
    abortRef.current = controller
    let pending: ChatEvent[] = []
    let timer: ReturnType<typeof setTimeout> | undefined
    let finished = false

    const flush = () => {
      if (timer !== undefined) clearTimeout(timer)
      timer = undefined
      if (pending.length === 0) return
      const events = pending
      pending = []
      dispatch({ type: 'events', events, now: Date.now() })
    }

    try {
      const { model, thinking } = optionsRef.current
      for await (const event of streamChat({ messages: history, model, thinking }, controller.signal)) {
        pending.push(event)
        if (event.type === 'done' || event.type === 'error') {
          finished = true
          flush()
        } else {
          timer ??= setTimeout(flush, FLUSH_MS)
        }
      }
      flush()
      if (!finished) {
        dispatch({
          type: 'fail',
          error: { code: 'stream_ended', message: 'The answer ended unexpectedly.' },
          now: Date.now(),
        })
      }
    } catch (error) {
      if (controller.signal.aborted) return
      flush()
      dispatch({ type: 'fail', error: describeError(error), now: Date.now() })
    } finally {
      if (timer !== undefined) clearTimeout(timer)
      if (abortRef.current === controller) abortRef.current = null
    }
  }, [])

  const send = useCallback(
    (text: string): boolean => {
      const question = text.trim()
      if (!question || isBusy(stateRef.current)) return false
      const history = [...buildHistory(stateRef.current.messages), { role: 'user' as const, content: question }]
      dispatch({ type: 'send', userId: nextId(), assistantId: nextId(), text: question, now: Date.now() })
      void run(history)
      return true
    },
    [run],
  )

  /** Ask again after a failed or stopped answer. */
  const retry = useCallback(() => {
    const messages = stateRef.current.messages
    const last = messages.at(-1)
    if (!last || last.role !== 'assistant' || last.status === 'streaming' || last.status === 'done') return
    const history = buildHistory(messages.slice(0, -1))
    dispatch({ type: 'dropLastAssistant' })
    dispatch({ type: 'restart', assistantId: nextId(), now: Date.now() })
    void run(history)
  }, [run])

  /** Stop the answer. Closing the connection also stops the model. */
  const stop = useCallback(() => {
    abortRef.current?.abort()
    dispatch({ type: 'stop', now: Date.now() })
  }, [])

  const newChat = useCallback(() => {
    abortRef.current?.abort()
    dispatch({ type: 'reset' })
  }, [])

  return { messages: state.messages, busy: isBusy(state), send, retry, stop, newChat }
}
