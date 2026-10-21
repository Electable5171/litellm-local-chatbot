import type { ChatEvent } from '../api/types'
import { chatReducer, fromStored, initialState, isBusy, type ChatState } from './chatReducer'

const send = (state: ChatState, text = 'hi', now = 1000) =>
  chatReducer(state, { type: 'send', userId: 'u', assistantId: 'a', text, now })

const events = (state: ChatState, list: ChatEvent[], now = 2000) =>
  chatReducer(state, { type: 'events', events: list, now })

const DONE: ChatEvent = {
  type: 'done',
  finish_reason: 'stop',
  usage: { prompt_tokens: 5, completion_tokens: 42 },
  latency_ms: 9000,
  ttft_ms: 300,
}

describe('chatReducer', () => {
  it('sending adds the question and an empty streaming answer', () => {
    const state = send(initialState)
    expect(state.messages.map((m) => [m.role, m.status])).toEqual([
      ['user', 'done'],
      ['assistant', 'streaming'],
    ])
    expect(isBusy(state)).toBe(true)
  })

  it('collects reasoning and content, and times how long the model thought', () => {
    let state = send(initialState, 'hi', 1000)
    state = events(state, [{ type: 'reasoning', delta: 'think ' }, { type: 'reasoning', delta: 'more' }], 2000)
    expect(state.messages[1]).toMatchObject({ reasoning: 'think more', content: '' })
    expect(state.messages[1]!.thinkingMs).toBeUndefined()
    state = events(state, [{ type: 'content', delta: 'Answer' }], 4500)
    expect(state.messages[1]).toMatchObject({ content: 'Answer', thinkingMs: 3500 })
    state = events(state, [{ type: 'content', delta: '!' }, DONE], 6000)
    expect(state.messages[1]).toMatchObject({
      content: 'Answer!',
      status: 'done',
      thinkingMs: 3500,
      stats: { completionTokens: 42, latencyMs: 9000, ttftMs: 300, finishReason: 'stop' },
    })
    expect(isBusy(state)).toBe(false)
  })

  it('records how many older messages the server left out', () => {
    const state = events(send(initialState), [
      { type: 'meta', model: 'm', thinking: true, trimmed_messages: 4 },
    ])
    expect(state.messages[1]!.trimmed).toBe(4)
  })

  it('an error event keeps the partial answer and marks the message as failed', () => {
    let state = events(send(initialState), [{ type: 'content', delta: 'Hel' }])
    state = events(state, [{ type: 'error', code: 'upstream_interrupted', message: 'lost' }])
    expect(state.messages[1]).toMatchObject({
      status: 'error',
      content: 'Hel',
      error: { code: 'upstream_interrupted', message: 'lost' },
    })
  })

  it('failing or stopping before any text leaves an empty message', () => {
    const failed = chatReducer(send(initialState), {
      type: 'fail',
      error: { code: 'upstream_busy', message: 'busy', retryAfterS: 5 },
      now: 2000,
    })
    expect(failed.messages[1]).toMatchObject({ status: 'error', content: '', error: { retryAfterS: 5 } })
    const stopped = chatReducer(send(initialState), { type: 'stop', now: 2000 })
    expect(stopped.messages[1]!.status).toBe('stopped')
  })

  it('events that arrive after the answer was stopped are ignored', () => {
    let state = chatReducer(send(initialState), { type: 'stop', now: 2000 })
    state = events(state, [{ type: 'content', delta: 'late' }])
    expect(state.messages[1]!.content).toBe('')
  })

  it('dropLastAssistant removes a failed answer but never a streaming one', () => {
    const streaming = send(initialState)
    expect(chatReducer(streaming, { type: 'dropLastAssistant' })).toBe(streaming)
    const failed = chatReducer(streaming, { type: 'stop', now: 2000 })
    expect(chatReducer(failed, { type: 'dropLastAssistant' }).messages).toHaveLength(1)
  })

  it('reset empties the conversation', () => {
    expect(chatReducer(send(initialState), { type: 'reset' })).toEqual(initialState)
  })
})

describe('saved messages', () => {
  const base = {
    id: 'x',
    role: 'assistant' as const,
    content: 'answer',
    reasoning: 'thoughts',
    status: 'complete' as const,
    error: null,
    finish_reason: 'stop',
    usage: { prompt_tokens: 5, completion_tokens: 42 },
    latency_ms: 9000,
    ttft_ms: 300,
    thinking_ms: 3500,
    trimmed: false,
    sources: null,
    created_at: '2026-10-21T10:00:00.000Z',
  }

  it('a finished answer keeps its thinking time and statistics', () => {
    expect(fromStored(base)).toMatchObject({
      status: 'done',
      saved: true,
      thinkingMs: 3500,
      reasoning: 'thoughts',
      stats: { completionTokens: 42, latencyMs: 9000, ttftMs: 300, finishReason: 'stop' },
    })
  })

  it('stopped and failed answers come back as stopped and failed', () => {
    expect(fromStored({ ...base, status: 'cancelled' }).status).toBe('stopped')
    const failed = fromStored({
      ...base,
      status: 'error',
      usage: null,
      latency_ms: null,
      error: { code: 'interrupted', message: 'The app stopped.' },
    })
    expect(failed).toMatchObject({ status: 'error', error: { code: 'interrupted' } })
    expect(failed.stats).toBeUndefined()
  })

  it('the server confirms an answer is stored with its first event', () => {
    let state = send(initialState)
    expect(state.messages[1]!.saved).toBe(false)
    state = events(state, [{ type: 'meta', model: 'm', thinking: true, trimmed_messages: 0 }])
    expect(state.messages[1]!.saved).toBe(true)
  })

  it('load replaces the conversation', () => {
    const state = chatReducer(send(initialState), { type: 'load', messages: [fromStored(base)] })
    expect(state.messages).toHaveLength(1)
  })

  it('dropLastTurn removes the question and a failed answer together', () => {
    const failed = chatReducer(send(initialState), { type: 'stop', now: 2000 })
    expect(chatReducer(failed, { type: 'dropLastTurn' }).messages).toEqual([])
    const streaming = send(initialState)
    expect(chatReducer(streaming, { type: 'dropLastTurn' })).toBe(streaming)
  })
})
