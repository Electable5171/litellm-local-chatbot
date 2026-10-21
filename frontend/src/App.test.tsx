import { render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import App from './App'
import type { ConversationWithMessages, Health, ModelsResponse, StoredMessage } from './api/types'

const encoder = new TextEncoder()

const HEALTH: Health = {
  status: 'ok',
  version: '0.1.0',
  litellm: { base_url: 'http://x/v1', reachable: true, latency_ms: 120, error: null, checked_age_s: 0 },
  chat_model: { id: 'qwen3.8', available: true },
}
const MODELS: ModelsResponse = { default: 'qwen3.8', models: [{ id: 'qwen3.8', available: true }] }

const frame = (event: string, data: object) => `event: ${event}\ndata: ${JSON.stringify(data)}\n\n`
const DONE = frame('done', {
  finish_reason: 'stop',
  usage: { prompt_tokens: 5, completion_tokens: 42 },
  latency_ms: 9000,
  ttft_ms: 300,
})
const META = frame('meta', { model: 'qwen3.8', thinking: true, trimmed_messages: 0 })

/** A chat response the test can feed piece by piece, like the real server does. */
function liveStream(signal?: AbortSignal | null) {
  let controller!: ReadableStreamDefaultController<Uint8Array>
  const body = new ReadableStream<Uint8Array>({
    start(c) {
      controller = c
      signal?.addEventListener('abort', () => c.error(new DOMException('Aborted', 'AbortError')))
    },
  })
  return {
    response: new Response(body, { headers: { 'content-type': 'text/event-stream' } }),
    push: (text: string) => controller.enqueue(encoder.encode(text)),
    close: () => controller.close(),
  }
}

function fullResponse(...frames: string[]): Response {
  return new Response(frames.join(''), { headers: { 'content-type': 'text/event-stream' } })
}

const stamp = (daysAgo = 0) => new Date(Date.now() - daysAgo * 86_400_000).toISOString()

function conversation(id: string, title: string, extra: Partial<ConversationWithMessages> = {}): ConversationWithMessages {
  return {
    id,
    title,
    model: 'qwen3.8',
    thinking: true,
    system_prompt: '',
    created_at: stamp(),
    updated_at: stamp(),
    messages: [],
    ...extra,
  }
}

function stored(role: 'user' | 'assistant', content: string, extra: Partial<StoredMessage> = {}): StoredMessage {
  return {
    id: `s-${content}`,
    role,
    content,
    reasoning: '',
    status: 'complete',
    error: null,
    finish_reason: null,
    usage: null,
    latency_ms: null,
    ttft_ms: null,
    thinking_ms: null,
    trimmed: false,
    created_at: stamp(),
    ...extra,
  }
}

interface Turn {
  kind: 'message' | 'regenerate'
  conversationId: string
  content?: string
  init: RequestInit
}
type TurnHandler = (turn: Turn) => Response | Promise<Response>

/** A small stand-in for the backend: conversations live in memory for the length of a test. */
function mockServer(
  turn: TurnHandler = () => fullResponse(DONE),
  options: { health?: Health; conversations?: ConversationWithMessages[] } = {},
) {
  const db = new Map((options.conversations ?? []).map((c) => [c.id, c]))
  let created = 0
  const calls: { method: string; url: string; body?: unknown }[] = []
  const mock = vi.fn(async (input: RequestInfo | URL, init: RequestInit = {}) => {
    const url = String(input)
    const method = init.method ?? 'GET'
    const body = typeof init.body === 'string' ? (JSON.parse(init.body) as Record<string, unknown>) : undefined
    calls.push({ method, url, body })
    if (url === '/api/health') return Response.json(options.health ?? HEALTH)
    if (url === '/api/models') return Response.json(MODELS)
    if (url === '/api/conversations') {
      if (method === 'POST') {
        created += 1
        const made = conversation(`new${created}`, '', { thinking: body?.thinking !== false })
        db.set(made.id, made)
        return Response.json(made, { status: 201 })
      }
      return Response.json({ conversations: [...db.values()].map((c) => ({ ...c, messages: undefined })) })
    }
    const match = /^\/api\/conversations\/([^/]+)(\/messages|\/regenerate)?$/.exec(url)
    if (match) {
      const id = decodeURIComponent(match[1]!)
      const found = db.get(id)
      if (!found) {
        return Response.json({ error: { code: 'conversation_not_found', message: 'gone' } }, { status: 404 })
      }
      if (match[2]) {
        const kind = match[2] === '/messages' ? 'message' : 'regenerate'
        const content = body?.content as string | undefined
        if (kind === 'message' && !found.title) found.title = content ?? ''
        return turn({ kind, conversationId: id, content, init })
      }
      if (method === 'DELETE') {
        db.delete(id)
        return new Response(null, { status: 204 })
      }
      if (method === 'PATCH') {
        Object.assign(found, body)
        return Response.json(found)
      }
      return Response.json(found)
    }
    throw new Error(`unexpected request to ${method} ${url}`)
  })
  vi.stubGlobal('fetch', mock)
  return { mock, calls, db }
}

const turnCalls = (server: ReturnType<typeof mockServer>) =>
  server.calls.filter((c) => c.method === 'POST' && /\/(messages|regenerate)$/.test(c.url))

const box = () => screen.getByRole('textbox', { name: 'Message' })

beforeEach(() => {
  localStorage.clear()
  window.location.hash = ''
})
afterEach(() => {
  vi.unstubAllGlobals()
})

describe('App', () => {
  it('shows that the model is ready', async () => {
    mockServer(() => fullResponse(DONE))
    render(<App />)
    expect(await screen.findByRole('status')).toHaveTextContent('Ready · 120 ms')
  })

  it('shows what is wrong when LiteLLM is not reachable', async () => {
    const degraded: Health = {
      ...HEALTH,
      status: 'degraded',
      litellm: { ...HEALTH.litellm, reachable: false, latency_ms: null, error: 'Cannot reach LiteLLM.' },
    }
    mockServer(() => fullResponse(DONE), { health: degraded })
    render(<App />)
    expect(await screen.findByText('Cannot reach LiteLLM.')).toBeInTheDocument()
  })

  it('shows the thinking live, folds it away when the answer starts, then shows the answer', async () => {
    const live = liveStream()
    mockServer(() => live.response)
    const user = userEvent.setup()
    render(<App />)

    await user.type(box(), 'What is 17*23?{Enter}')
    expect(screen.getByText('What is 17*23?')).toBeInTheDocument()

    live.push(META + frame('reasoning', { delta: '17*20 = 340, ' }) + frame('reasoning', { delta: '17*3 = 51' }))
    expect(await screen.findByText(/17\*20 = 340, 17\*3 = 51/)).toBeInTheDocument()
    const thinking = screen.getByText('Thinking…').closest('details')!
    expect(thinking).toHaveAttribute('open')
    expect(screen.getByRole('button', { name: 'Stop' })).toBeInTheDocument()

    live.push(frame('content', { delta: 'The answer is **391**.' }) + DONE)
    live.close()
    expect(await screen.findByText('391')).toBeInTheDocument()
    expect(screen.getByText(/Thought for/)).toBeInTheDocument()
    expect(screen.getByText(/Thought for/).closest('details')).not.toHaveAttribute('open')
    expect(await screen.findByText('42 tokens · 9.0 s · first token 0.3 s')).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Send' })).toBeDisabled() // empty box
  })

  it('saves the chat on the first question and keeps asking in the same chat', async () => {
    const server = mockServer(({ content }) =>
      fullResponse(
        frame('reasoning', { delta: 'secret thoughts' }),
        frame('content', { delta: `reply to: ${content}` }),
        DONE,
      ),
    )
    const user = userEvent.setup()
    render(<App />)
    await user.type(box(), 'first{Enter}')
    await screen.findByText('reply to: first')
    await user.type(box(), 'second{Enter}')
    await screen.findByText('reply to: second')

    expect(server.calls.filter((c) => c.method === 'POST' && c.url === '/api/conversations')).toHaveLength(1)
    expect(turnCalls(server).map((c) => [c.url, c.body])).toEqual([
      ['/api/conversations/new1/messages', { content: 'first' }],
      ['/api/conversations/new1/messages', { content: 'second' }],
    ])
    expect(window.location.hash).toBe('#/c/new1') // the address shows the chat
    // the sidebar lists it, titled by the first question
    expect(await within(screen.getByRole('navigation', { name: 'Conversations' })).findByText('first')).toBeInTheDocument()
  })

  it('Shift+Enter makes a new line instead of sending', async () => {
    const server = mockServer(() => fullResponse(DONE))
    const user = userEvent.setup()
    render(<App />)
    await user.type(box(), 'line one{Shift>}{Enter}{/Shift}line two')
    expect(box()).toHaveValue('line one\nline two')
    expect(turnCalls(server)).toHaveLength(0)
  })

  it('the Thinking switch is sent with the question and remembered', async () => {
    const server = mockServer(() => fullResponse(frame('content', { delta: 'hi' }), DONE))
    const user = userEvent.setup()
    const { unmount } = render(<App />)
    await user.click(screen.getByRole('switch', { name: 'Thinking' }))
    await user.type(box(), 'hello{Enter}')
    await screen.findByText('hi')
    const created = server.calls.find((c) => c.method === 'POST' && c.url === '/api/conversations')
    expect(created?.body).toMatchObject({ thinking: false })

    unmount()
    render(<App />)
    expect(screen.getByRole('switch', { name: 'Thinking' })).not.toBeChecked()
  })

  it('renders the answer as markdown with a copyable code block, and ignores raw HTML', async () => {
    const answer = 'Use **bold** text.\n\n```python\nprint("hi")\n```\n\n<script>window.pwned = 1</script>'
    mockServer(() => fullResponse(frame('content', { delta: answer }), DONE))
    const user = userEvent.setup()
    render(<App />)
    await user.type(box(), 'code please{Enter}')

    const bold = await screen.findByText('bold')
    expect(bold.tagName).toBe('STRONG')
    const block = screen.getByText('python').closest('.code-block') as HTMLElement
    expect(block).toHaveTextContent('print("hi")')
    await user.click(within(block).getByRole('button', { name: 'Copy' }))
    expect(await navigator.clipboard.readText()).toBe('print("hi")\n')
    expect(within(block).getByRole('button', { name: 'Copied' })).toBeInTheDocument()
    expect(document.querySelector('script')).toBeNull()
    expect((window as unknown as { pwned?: number }).pwned).toBeUndefined()
  })

  it('never turns the answer into live scripts, javascript: links or tracking images', async () => {
    const answer = [
      '[click me](javascript:alert(1))',
      '<img src=x onerror="window.pwned = 2">',
      '![pixel](https://tracker.example/pixel.png)',
      '[fine](https://example.com/page)',
    ].join('\n\n')
    mockServer(() => fullResponse(frame('content', { delta: answer }), DONE))
    const user = userEvent.setup()
    render(<App />)
    await user.type(box(), 'links{Enter}')

    const fine = await screen.findByRole('link', { name: 'fine' })
    expect(fine).toHaveAttribute('href', 'https://example.com/page')
    expect(fine).toHaveAttribute('target', '_blank')
    expect(fine).toHaveAttribute('rel', 'noopener noreferrer')
    for (const link of screen.getAllByRole('link')) {
      expect(link.getAttribute('href') ?? '').not.toMatch(/^javascript:/i)
    }
    expect(document.querySelector('img')).toBeNull() // nothing is fetched from another server
    expect(screen.getByText('[image: pixel]')).toBeInTheDocument()
    expect((window as unknown as { pwned?: number }).pwned).toBeUndefined()
  })

  it('explains that the model is busy and lets you try again', async () => {
    let calls = 0
    mockServer(() => {
      calls += 1
      if (calls === 1) {
        return Response.json(
          { error: { code: 'upstream_busy', message: 'busy', retry_after_s: 5 } },
          { status: 503 },
        )
      }
      return fullResponse(frame('content', { delta: 'Now it works.' }), DONE)
    })
    const user = userEvent.setup()
    render(<App />)
    await user.type(box(), 'hello{Enter}')
    expect(await screen.findByRole('alert')).toHaveTextContent('The model is busy right now')

    await user.click(screen.getByRole('button', { name: 'Try again' }))
    expect(await screen.findByText('Now it works.')).toBeInTheDocument()
    expect(screen.queryByRole('alert')).toBeNull()
    expect(within(screen.getByRole('log')).getAllByText('hello')).toHaveLength(1) // the question is not duplicated
  })

  it('an error in the middle of an answer keeps what arrived', async () => {
    mockServer(() =>
      fullResponse(
        frame('content', { delta: 'Half an ans' }),
        frame('error', { code: 'upstream_interrupted', message: 'The connection to LiteLLM was lost.' }),
      ),
    )
    const user = userEvent.setup()
    render(<App />)
    await user.type(box(), 'hi{Enter}')
    expect(await screen.findByText('Half an ans')).toBeInTheDocument()
    expect(await screen.findByRole('alert')).toHaveTextContent('The connection to LiteLLM was lost.')
  })

  it('an answer that ends without a done event is reported as an error', async () => {
    mockServer(() => fullResponse(frame('content', { delta: 'cut' })))
    const user = userEvent.setup()
    render(<App />)
    await user.type(box(), 'hi{Enter}')
    expect(await screen.findByRole('alert')).toHaveTextContent('ended unexpectedly')
  })

  it('Stop ends the answer, keeps the text so far and closes the connection', async () => {
    let signal: AbortSignal | null | undefined
    mockServer(({ init }) => {
      signal = init.signal
      const live = liveStream(init.signal)
      live.push(frame('content', { delta: 'Partial answer' }))
      return live.response
    })
    const user = userEvent.setup()
    render(<App />)
    await user.type(box(), 'long one{Enter}')
    expect(await screen.findByText('Partial answer')).toBeInTheDocument()

    await user.click(screen.getByRole('button', { name: 'Stop' }))
    await waitFor(() => expect(screen.getByRole('button', { name: 'Send' })).toBeInTheDocument())
    expect(signal?.aborted).toBe(true)
    expect(screen.getByText('Partial answer')).toBeInTheDocument()
    expect(screen.getByText('Stopped')).toBeInTheDocument()
    expect(screen.queryByRole('alert')).toBeNull()
  })

  it('New chat clears the conversation', async () => {
    mockServer(() => fullResponse(frame('content', { delta: 'an answer' }), DONE))
    const user = userEvent.setup()
    render(<App />)
    await user.type(box(), 'question{Enter}')
    await screen.findByText('an answer')
    await user.click(screen.getByRole('button', { name: 'New chat' }))
    expect(screen.queryByText('an answer')).toBeNull()
    expect(screen.getByText('What would you like to know?')).toBeInTheDocument()
  })
})

describe('saved conversations', () => {
  const sidebar = () => screen.getByRole('navigation', { name: 'Conversations' })

  it('lists saved chats grouped by day and opens one with its thinking and statistics', async () => {
    const old = conversation('c1', 'Old question', { updated_at: stamp(30) })
    const recent = conversation('c2', 'Fresh question', {
      thinking: false,
      messages: [
        stored('user', 'Fresh question'),
        stored('assistant', 'Fresh **answer**', {
          reasoning: 'some thinking',
          thinking_ms: 2000,
          usage: { prompt_tokens: 3, completion_tokens: 7 },
          latency_ms: 4000,
          ttft_ms: 500,
        }),
      ],
    })
    mockServer(() => fullResponse(DONE), { conversations: [old, recent] })
    const user = userEvent.setup()
    render(<App />)

    expect(await within(sidebar()).findByText('Today')).toBeInTheDocument()
    expect(within(sidebar()).getByText('Older')).toBeInTheDocument()
    await user.click(within(sidebar()).getByRole('button', { name: 'Fresh question' }))

    expect(await screen.findByText('answer')).toBeInTheDocument()
    expect(screen.getByText(/Thought for/)).toBeInTheDocument()
    expect(screen.getByText('7 tokens · 4.0 s · first token 0.5 s')).toBeInTheDocument()
    expect(screen.getByRole('switch', { name: 'Thinking' })).not.toBeChecked() // this chat has it off
    expect(window.location.hash).toBe('#/c/c2')
  })

  it('opens the chat named in the address after a reload, and goes home when it is gone', async () => {
    mockServer(() => fullResponse(DONE), {
      conversations: [conversation('c1', 'Kept', { messages: [stored('user', 'hello again')] })],
    })
    window.location.hash = '#/c/c1'
    const { unmount } = render(<App />)
    expect(await screen.findByText('hello again')).toBeInTheDocument()
    unmount()

    window.location.hash = '#/c/deleted-elsewhere'
    render(<App />)
    expect(await screen.findByText('What would you like to know?')).toBeInTheDocument()
    expect(window.location.hash).toBe('#/')
  })

  it('renames a chat', async () => {
    const server = mockServer(() => fullResponse(DONE), { conversations: [conversation('c1', 'Before')] })
    const user = userEvent.setup()
    render(<App />)
    await user.click(await within(sidebar()).findByRole('button', { name: 'Rename Before' }))
    const input = screen.getByRole('textbox', { name: 'Chat title' })
    await user.clear(input)
    await user.type(input, 'After{Enter}')
    expect(await within(sidebar()).findByText('After')).toBeInTheDocument()
    expect(server.calls.find((c) => c.method === 'PATCH')?.body).toEqual({ title: 'After' })
  })

  it('deletes a chat only after confirmation, and leaves the open chat when it is deleted', async () => {
    const server = mockServer(() => fullResponse(DONE), {
      conversations: [conversation('c1', 'Doomed', { messages: [stored('user', 'bye')] })],
    })
    window.location.hash = '#/c/c1'
    const user = userEvent.setup()
    render(<App />)
    await screen.findByText('bye')

    await user.click(within(sidebar()).getByRole('button', { name: 'Delete Doomed' }))
    await user.click(within(sidebar()).getByRole('button', { name: 'Cancel' }))
    expect(server.calls.some((c) => c.method === 'DELETE')).toBe(false)

    await user.click(within(sidebar()).getByRole('button', { name: 'Delete Doomed' }))
    await user.click(within(sidebar()).getByRole('button', { name: 'Delete' }))
    await waitFor(() => expect(server.calls.some((c) => c.method === 'DELETE')).toBe(true))
    expect(await screen.findByText('What would you like to know?')).toBeInTheDocument()
    expect(within(sidebar()).queryByText('Doomed')).toBeNull()
  })

  it('a changed Thinking switch is saved with the open chat', async () => {
    const server = mockServer(() => fullResponse(DONE), { conversations: [conversation('c1', 'Chat')] })
    window.location.hash = '#/c/c1'
    const user = userEvent.setup()
    render(<App />)
    await waitFor(() => expect(screen.getByRole('switch', { name: 'Thinking' })).toBeChecked())
    await user.click(screen.getByRole('switch', { name: 'Thinking' }))
    await waitFor(() =>
      expect(server.calls.find((c) => c.method === 'PATCH')?.body).toEqual({ thinking: false }),
    )
  })

  it('Try again asks the server for a new answer when the old one was stored', async () => {
    let calls = 0
    const server = mockServer(() => {
      calls += 1
      return calls === 1
        ? fullResponse(META, frame('content', { delta: 'Half' }), frame('error', { code: 'upstream_interrupted', message: 'lost' }))
        : fullResponse(META, frame('content', { delta: 'Whole answer' }), DONE)
    })
    const user = userEvent.setup()
    render(<App />)
    await user.type(box(), 'question{Enter}')
    await screen.findByRole('alert')
    await user.click(screen.getByRole('button', { name: 'Try again' }))

    expect(await screen.findByText('Whole answer')).toBeInTheDocument()
    expect(turnCalls(server).map((c) => c.url.split('/').pop())).toEqual(['messages', 'regenerate'])
    expect(within(screen.getByRole('log')).getAllByText('question')).toHaveLength(1)
  })

  it('cannot switch chats or start a new one while an answer is being written', async () => {
    const live = liveStream()
    mockServer(() => live.response, { conversations: [conversation('c1', 'Other')] })
    const user = userEvent.setup()
    render(<App />)
    await within(sidebar()).findByText('Other')
    await user.type(box(), 'working{Enter}')
    live.push(META + frame('content', { delta: 'part' }))
    await screen.findByText('part')
    expect(within(sidebar()).getByRole('button', { name: 'New chat' })).toBeDisabled()
    expect(within(sidebar()).getByRole('button', { name: 'Other' })).toBeDisabled()
    live.push(DONE)
    live.close()
    await waitFor(() => expect(within(sidebar()).getByRole('button', { name: 'New chat' })).toBeEnabled())
  })
})
