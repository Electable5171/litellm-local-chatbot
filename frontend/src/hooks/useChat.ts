import { useCallback, useEffect, useReducer, useRef, useState } from 'react'
import { streamTurn } from '../api/chat'
import { createConversation, getConversation } from '../api/conversations'
import { attachDocument } from '../api/documents'
import { ApiError, describeError } from '../api/errors'
import type { ChatEvent, ConversationWithMessages } from '../api/types'
import { chatReducer, fromStored, initialState, isBusy } from '../state/chatReducer'

export interface ChatOptions {
  /** The conversation shown now; null is a new chat that is saved when the first question is sent. */
  conversationId: string | null
  model?: string
  thinking: boolean
  /** Documents chosen for a new chat; they are attached when the chat is saved. */
  attachedIds: string[]
  /** The chat's instructions (system prompt); a new chat is saved with them. */
  instructions: string
  /** A new chat was saved under this id (with its documents attached). */
  onCreated: (id: string) => void
  /** The page address should show this conversation (called when a new chat gets saved). */
  onOpen: (id: string | null) => void
  /** A saved conversation was loaded: the header follows its model and Thinking setting. */
  onLoaded: (conversation: ConversationWithMessages) => void
  /** The list of conversations is out of date (new chat, new title, new order). */
  onChanged: () => void
}

let counter = 0
const nextId = () => `m${++counter}`

/** Streamed text is applied at most every 50 ms, so long answers do not re-render per token. */
const FLUSH_MS = 50

export function useChat(options: ChatOptions) {
  const [state, dispatch] = useReducer(chatReducer, initialState)
  // Which conversation's messages are on screen, and which one failed to load (derived below).
  const [loadedId, setLoadedId] = useState<string | null>(null)
  // A refused edit or similar: shown above the message box until the next action.
  const [actionError, setActionError] = useState<string | null>(null)
  const [failed, setFailed] = useState<{ id: string; message: string } | null>(null)
  const stateRef = useRef(state)
  const optionsRef = useRef(options)
  const abortRef = useRef<AbortController | null>(null)
  // The conversation this hook just created: it is already on screen, so it is not loaded again.
  const createdRef = useRef<string | null>(null)

  useEffect(() => {
    stateRef.current = state
    optionsRef.current = options
  })
  useEffect(() => () => abortRef.current?.abort(), [])

  const { conversationId } = options
  useEffect(() => {
    if (conversationId !== null && conversationId === createdRef.current) {
      createdRef.current = null
      return
    }
    abortRef.current?.abort()
    dispatch({ type: 'reset' })
    if (conversationId === null) return
    const controller = new AbortController()
    getConversation(conversationId, controller.signal)
      .then((conversation) => {
        dispatch({ type: 'load', messages: conversation.messages.map(fromStored) })
        optionsRef.current.onLoaded(conversation)
        setLoadedId(conversation.id)
      })
      .catch((error: unknown) => {
        if (controller.signal.aborted) return
        if (error instanceof ApiError && error.code === 'conversation_not_found') {
          optionsRef.current.onOpen(null)
        } else {
          setFailed({ id: conversationId, message: describeError(error).message })
        }
      })
    return () => controller.abort()
  }, [conversationId])

  /** Stream one turn into the last answer. `turn` creates the conversation first when needed. */
  const run = useCallback(
    async (
      turn: { kind: 'message'; content: string } | { kind: 'edit'; messageId: string; content: string } | { kind: 'regenerate' },
    ) => {
      const controller = new AbortController()
      abortRef.current = controller
      let pending: ChatEvent[] = []
      let timer: ReturnType<typeof setTimeout> | undefined
      let finished = false
      let started = false // any event of this answer has arrived

      const flush = () => {
        if (timer !== undefined) clearTimeout(timer)
        timer = undefined
        if (pending.length === 0) return
        const events = pending
        pending = []
        dispatch({ type: 'events', events, now: Date.now() })
      }

      try {
        let id = optionsRef.current.conversationId
        if (id === null) {
          const { model, thinking, instructions } = optionsRef.current
          id = (await createConversation({ model, thinking, system_prompt: instructions || undefined })).id
          createdRef.current = id
          setLoadedId(id)
          optionsRef.current.onCreated(id)
          optionsRef.current.onOpen(id)
          for (const documentId of optionsRef.current.attachedIds) await attachDocument(id, documentId)
        }
        for await (const event of streamTurn(id, turn, controller.signal)) {
          started = true
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
        if (turn.kind === 'edit' && !started) {
          // The server refused the edit, so nothing changed there: show what it still has.
          const id = optionsRef.current.conversationId
          setActionError(describeError(error).message)
          if (id !== null) {
            try {
              const conversation = await getConversation(id)
              dispatch({ type: 'load', messages: conversation.messages.map(fromStored) })
            } catch {
              // keep what is on screen; the error above says what went wrong
            }
          }
        } else {
          dispatch({ type: 'fail', error: describeError(error), now: Date.now() })
        }
      } finally {
        if (timer !== undefined) clearTimeout(timer)
        if (abortRef.current === controller) abortRef.current = null
        optionsRef.current.onChanged()
      }
    },
    [],
  )

  const send = useCallback(
    (text: string): boolean => {
      const question = text.trim()
      if (!question || isBusy(stateRef.current)) return false
      setActionError(null)
      dispatch({ type: 'send', userId: nextId(), assistantId: nextId(), text: question, now: Date.now() })
      void run({ kind: 'message', content: question })
      return true
    },
    [run],
  )

  /** Replace one of your messages (and everything after it) with new text and answer that. */
  const edit = useCallback(
    (serverId: string, text: string): boolean => {
      const question = text.trim()
      const index = stateRef.current.messages.findIndex((m) => m.role === 'user' && m.serverId === serverId)
      if (!question || index < 0 || isBusy(stateRef.current) || optionsRef.current.conversationId === null) {
        return false
      }
      setActionError(null)
      dispatch({ type: 'edit', index, userId: nextId(), assistantId: nextId(), text: question, now: Date.now() })
      void run({ kind: 'edit', messageId: serverId, content: question })
      return true
    },
    [run],
  )

  /**
   * Ask again after a failed or stopped answer. If the server stored the answer it makes a new one;
   * if the request never got that far, the question is sent again.
   */
  const retry = useCallback(() => {
    const messages = stateRef.current.messages
    const last = messages.at(-1)
    if (!last || last.role !== 'assistant' || last.status === 'streaming' || last.status === 'done') return
    if (last.saved) {
      dispatch({ type: 'dropLastAssistant' })
      dispatch({ type: 'restart', assistantId: nextId(), now: Date.now() })
      void run({ kind: 'regenerate' })
      return
    }
    const question = messages.at(-2)
    if (question?.role !== 'user') return
    dispatch({ type: 'dropLastTurn' })
    send(question.content)
  }, [run, send])

  /** Stop the answer. Closing the connection also stops the model; the text so far is kept. */
  const stop = useCallback(() => {
    abortRef.current?.abort()
    dispatch({ type: 'stop', now: Date.now() })
    optionsRef.current.onChanged()
  }, [])

  const loadError = failed?.id === conversationId ? failed.message : null
  const loading = conversationId !== null && loadedId !== conversationId && loadError === null
  return { messages: state.messages, busy: isBusy(state), loading, loadError, actionError, send, edit, retry, stop }
}
