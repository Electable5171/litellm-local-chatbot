import type { ChatEvent } from '../api/types'
import { buildHistory, chatReducer, initialState, isBusy, type ChatState } from './chatReducer'

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

describe('buildHistory', () => {
  it('sends questions and finished or stopped answers, never reasoning or failed answers', () => {
    let state = send(initialState, 'q1')
    state = events(state, [{ type: 'reasoning', delta: 'secret' }, { type: 'content', delta: 'a1' }, DONE])
    state = chatReducer(state, { type: 'send', userId: 'u2', assistantId: 'a2', text: 'q2', now: 3000 })
    state = chatReducer(state, { type: 'fail', error: { code: 'x', message: 'x' }, now: 3100 })
    state = chatReducer(state, { type: 'send', userId: 'u3', assistantId: 'a3', text: 'q3', now: 4000 })
    expect(buildHistory(state.messages.slice(0, -1))).toEqual([
      { role: 'user', content: 'q1' },
      { role: 'assistant', content: 'a1' },
      { role: 'user', content: 'q2' },
      { role: 'user', content: 'q3' },
    ])
  })
})
